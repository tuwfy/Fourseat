"""
Fourseat Oracle - Stripe revenue intelligence layer.

Pipeline:
    1. Ingest Stripe events (webhook receiver) and/or poll Stripe API for active subs/charges.
    2. Roll the day into a `revenue_snapshots` row (MRR, NRR, churn, failed payments, ...).
    3. Run six anomaly rules over the snapshot history; each fired rule -> Anomaly.
    4. For each Anomaly, run the existing Boardroom debate (`run_debate`) and compress
       the transcript into a structured RevenueVerdict (4 advisor views + actions + confidence).
    5. Persist verdicts to `revenue_verdicts` and surface them through the /oracle dashboard.

Design notes:
- Demo mode (no STRIPE_SECRET_KEY configured) seeds 30 days of synthetic snapshots that
  intentionally trip 3 of 6 rules so the live demo always produces verdicts.
- Verdict synthesis reuses backend.debate_engine.ask_claude with a structured JSON contract,
  same shape as backend.sentinel does for the inbox triage path.
- We deliberately do NOT pull in ChromaDB here; the Oracle's "memory" is the snapshot
  history table, which is cheaper and more relevant for revenue reasoning.
- Webhook signature verification follows Stripe's standard scheme (t=, v1=, HMAC SHA-256).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import random
import sqlite3
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dep
    def load_dotenv():
        return None

load_dotenv()

log = logging.getLogger("fourseat.oracle")

# ── Paths & config ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = Path("/tmp/fourseat-data") if os.getenv("VERCEL") else (BASE_DIR / "data")
DATA_DIR = Path(os.getenv("FOURSEAT_DATA_DIR", str(DEFAULT_DATA_DIR)))
ORACLE_DIR = DATA_DIR / "oracle"
ORACLE_DIR.mkdir(parents=True, exist_ok=True)

DB_URL = os.getenv("ORACLE_DB_URL", f"sqlite:///{ORACLE_DIR / 'oracle.db'}")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_API_BASE = os.getenv("STRIPE_API_BASE", "https://api.stripe.com").rstrip("/")
STRIPE_API_VERSION = os.getenv("STRIPE_API_VERSION", "2024-06-20")
STRIPE_API_TIMEOUT = float(os.getenv("STRIPE_API_TIMEOUT", "12"))

WEBHOOK_TIMESTAMP_TOLERANCE = 5 * 60  # 5 minutes, matches Stripe's recommendation


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Snapshot:
    snapshot_date: str
    mrr_cents: int = 0
    new_mrr_cents: int = 0
    churn_mrr_cents: int = 0
    expansion_cents: int = 0
    contraction_cents: int = 0
    failed_payments_count: int = 0
    failed_payments_cents: int = 0
    nrr_pct: float = 100.0
    active_subs: int = 0
    top_customer_share: float = 0.0
    tier_breakdown: dict[str, int] = field(default_factory=dict)


@dataclass
class Anomaly:
    rule: str                  # "churn_cluster" | "nrr_drop" | "failed_payment_leakage" | ...
    priority: str              # "P0" | "P1" | "P2"
    headline: str              # short human-readable trigger summary
    evidence: dict[str, Any]   # numbers and series the panel reasons over
    detected_at: str           # ISO-8601


@dataclass
class RevenueVerdict:
    rule: str
    priority: str
    one_liner: str
    evidence: dict[str, Any]
    strategy_view: str
    finance_view: str
    tech_view: str
    contrarian_view: str
    actions: list[str]
    watch_metrics: list[str]
    confidence: str
    detected_at: str


# ── Storage ───────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    if not DB_URL.startswith("sqlite:///"):
        raise RuntimeError(
            "ORACLE_DB_URL currently only supports sqlite:/// in this module."
        )
    path = DB_URL.replace("sqlite:///", "", 1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    schema_file = BASE_DIR / "backend" / "oracle_schema.sql"
    if not schema_file.exists():
        raise FileNotFoundError(f"oracle schema not found at {schema_file}")
    with _connect() as conn:
        conn.executescript(schema_file.read_text())


# ── Stripe webhook signature verification ─────────────────────────────────────

def verify_stripe_signature(
    payload: bytes,
    sig_header: str,
    secret: str = "",
    *,
    tolerance_s: int = WEBHOOK_TIMESTAMP_TOLERANCE,
    now_ts: Optional[int] = None,
) -> bool:
    """Verify a Stripe webhook signature using HMAC-SHA256.

    Returns True only when:
      - secret is non-empty
      - sig_header parses (contains t= and at least one v1=)
      - the timestamp is within `tolerance_s` of now
      - the signed payload matches at least one v1 signature

    Stripe's docs: https://stripe.com/docs/webhooks#verify-manually
    """
    secret = (secret or STRIPE_WEBHOOK_SECRET or "").strip()
    if not secret or not sig_header or not isinstance(payload, (bytes, bytearray)):
        return False

    parts = [p.strip() for p in sig_header.split(",") if "=" in p]
    ts_value: Optional[str] = None
    v1_signatures: list[str] = []
    for p in parts:
        k, _, v = p.partition("=")
        if k == "t":
            ts_value = v
        elif k == "v1":
            v1_signatures.append(v)
    if not ts_value or not v1_signatures:
        return False
    try:
        ts_int = int(ts_value)
    except ValueError:
        return False

    now = now_ts if now_ts is not None else int(time.time())
    if abs(now - ts_int) > tolerance_s:
        return False

    signed = f"{ts_value}.".encode() + bytes(payload)
    computed = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(computed, sig) for sig in v1_signatures)


# ── Stripe API helpers (lightweight, no SDK) ──────────────────────────────────

def stripe_configured() -> bool:
    return bool(STRIPE_SECRET_KEY)


def _stripe_get(path: str, params: Optional[dict] = None) -> dict:
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY not configured")
    import requests  # local import to keep module-load light
    headers = {
        "Authorization": f"Bearer {STRIPE_SECRET_KEY}",
        "Stripe-Version": STRIPE_API_VERSION,
    }
    resp = requests.get(
        f"{STRIPE_API_BASE}{path}",
        headers=headers,
        params=params or {},
        timeout=STRIPE_API_TIMEOUT,
    )
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", {}).get("message", resp.text)
        except Exception:
            err = resp.text
        raise RuntimeError(f"Stripe API {resp.status_code}: {err}")
    return resp.json()


def _stripe_paginate(path: str, params: Optional[dict] = None, max_pages: int = 20) -> Iterable[dict]:
    p = dict(params or {})
    p.setdefault("limit", 100)
    pages = 0
    while True:
        data = _stripe_get(path, p)
        for row in data.get("data", []):
            yield row
        pages += 1
        if not data.get("has_more") or pages >= max_pages:
            return
        last = data["data"][-1] if data.get("data") else None
        if not last or "id" not in last:
            return
        p["starting_after"] = last["id"]


# ── Snapshot computation ──────────────────────────────────────────────────────

def _ingest_event_row(conn: sqlite3.Connection, ev: dict) -> None:
    """Persist a single Stripe event into revenue_events (idempotent on stripe_event_id)."""
    obj = (ev.get("data") or {}).get("object") or {}
    stripe_event_id = ev.get("id") or f"evt_synthetic_{int(time.time()*1000)}"
    fingerprint = hashlib.sha256(stripe_event_id.encode()).hexdigest()[:24]
    customer_id = obj.get("customer") if isinstance(obj.get("customer"), str) else (obj.get("customer") or {}).get("id")
    subscription_id = obj.get("subscription") if isinstance(obj.get("subscription"), str) else (obj.get("subscription") or {}).get("id")
    plan_id = ((obj.get("plan") or {}).get("id")) or ((obj.get("price") or {}).get("id"))
    amount = int(obj.get("amount") or obj.get("amount_due") or obj.get("amount_paid") or 0)
    currency = (obj.get("currency") or "usd").lower()
    occurred_ts = int(ev.get("created") or time.time())
    occurred_at = datetime.fromtimestamp(occurred_ts, tz=timezone.utc).isoformat()

    conn.execute(
        """
        INSERT OR IGNORE INTO revenue_events (
            fingerprint, stripe_event_id, event_type, customer_id, subscription_id,
            plan_id, amount_cents, currency, metadata_json, occurred_at, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fingerprint,
            stripe_event_id,
            ev.get("type", "unknown"),
            customer_id,
            subscription_id,
            plan_id,
            amount,
            currency,
            json.dumps(obj, default=str)[:8000],
            occurred_at,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def ingest_stripe_event(ev: dict) -> bool:
    """Public entrypoint for the webhook receiver. Returns True on success."""
    init_db()
    try:
        with _connect() as conn:
            _ingest_event_row(conn, ev)
        return True
    except Exception as exc:
        log.warning("oracle event ingest failed: %s", exc)
        return False


def compute_snapshot_from_stripe(snapshot_date: Optional[str] = None) -> Snapshot:
    """Pull live Stripe data and compute today's revenue snapshot.

    Falls back to an empty snapshot if Stripe is unconfigured or errors.
    """
    snapshot_date = snapshot_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snap = Snapshot(snapshot_date=snapshot_date)
    if not stripe_configured():
        return snap

    try:
        active_subs = list(_stripe_paginate("/v1/subscriptions", {"status": "active", "limit": 100}, max_pages=10))
    except Exception as exc:
        log.warning("oracle snapshot subs fetch failed: %s", exc)
        return snap

    customer_mrr: dict[str, int] = {}
    tier_counts: dict[str, int] = {}
    total_mrr = 0
    for sub in active_subs:
        items = ((sub.get("items") or {}).get("data") or [])
        sub_mrr = 0
        for it in items:
            price = it.get("price") or {}
            unit = int(price.get("unit_amount") or 0)
            qty = int(it.get("quantity") or 1)
            interval = ((price.get("recurring") or {}).get("interval") or "month").lower()
            count = max(1, int((price.get("recurring") or {}).get("interval_count") or 1))
            month_value = unit * qty
            if interval == "year":
                month_value = int(month_value / max(1, 12 * count))
            elif interval == "week":
                month_value = int(month_value * (52 / max(1, 12 * count)))
            elif interval == "day":
                month_value = int(month_value * (365 / max(1, 12 * count)))
            elif count > 1 and interval == "month":
                month_value = int(month_value / count)
            sub_mrr += month_value
            tier = (price.get("nickname") or price.get("id") or "default")[:80]
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        cust = sub.get("customer") if isinstance(sub.get("customer"), str) else ((sub.get("customer") or {}).get("id") or "unknown")
        customer_mrr[cust] = customer_mrr.get(cust, 0) + sub_mrr
        total_mrr += sub_mrr

    snap.mrr_cents = int(total_mrr)
    snap.active_subs = len(active_subs)
    snap.tier_breakdown = tier_counts
    if customer_mrr and total_mrr > 0:
        top = max(customer_mrr.values())
        snap.top_customer_share = round(top / total_mrr, 4)

    # Trailing-day failed payments / churn / new MRR derived from events table
    with _connect() as conn:
        day_start = f"{snapshot_date}T00:00:00+00:00"
        day_end = f"{snapshot_date}T23:59:59+00:00"
        rows = conn.execute(
            "SELECT event_type, amount_cents FROM revenue_events WHERE occurred_at BETWEEN ? AND ?",
            (day_start, day_end),
        ).fetchall()
    for r in rows:
        et = r["event_type"]
        amt = int(r["amount_cents"] or 0)
        if et in ("invoice.payment_failed", "charge.failed"):
            snap.failed_payments_count += 1
            snap.failed_payments_cents += amt
        elif et in ("customer.subscription.deleted",):
            snap.churn_mrr_cents += amt
        elif et in ("customer.subscription.created",):
            snap.new_mrr_cents += amt

    # Compute NRR vs the snapshot from 30 days ago (if we have one)
    with _connect() as conn:
        prior = conn.execute(
            "SELECT mrr_cents FROM revenue_snapshots WHERE snapshot_date <= ? ORDER BY snapshot_date DESC LIMIT 1 OFFSET 29",
            (snapshot_date,),
        ).fetchone()
    if prior and int(prior["mrr_cents"] or 0) > 0:
        snap.nrr_pct = round(100.0 * snap.mrr_cents / int(prior["mrr_cents"]), 2)
    return snap


def save_snapshot(snap: Snapshot) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO revenue_snapshots (
                snapshot_date, mrr_cents, new_mrr_cents, churn_mrr_cents,
                expansion_cents, contraction_cents, failed_payments_count,
                failed_payments_cents, nrr_pct, active_subs, top_customer_share,
                tier_breakdown_json, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                mrr_cents             = excluded.mrr_cents,
                new_mrr_cents         = excluded.new_mrr_cents,
                churn_mrr_cents       = excluded.churn_mrr_cents,
                expansion_cents       = excluded.expansion_cents,
                contraction_cents     = excluded.contraction_cents,
                failed_payments_count = excluded.failed_payments_count,
                failed_payments_cents = excluded.failed_payments_cents,
                nrr_pct               = excluded.nrr_pct,
                active_subs           = excluded.active_subs,
                top_customer_share    = excluded.top_customer_share,
                tier_breakdown_json   = excluded.tier_breakdown_json,
                computed_at           = excluded.computed_at
            """,
            (
                snap.snapshot_date,
                snap.mrr_cents,
                snap.new_mrr_cents,
                snap.churn_mrr_cents,
                snap.expansion_cents,
                snap.contraction_cents,
                snap.failed_payments_count,
                snap.failed_payments_cents,
                snap.nrr_pct,
                snap.active_subs,
                snap.top_customer_share,
                json.dumps(snap.tier_breakdown),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def load_snapshots(limit: int = 90) -> list[Snapshot]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM revenue_snapshots ORDER BY snapshot_date DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    out: list[Snapshot] = []
    for r in rows:
        try:
            tiers = json.loads(r["tier_breakdown_json"] or "{}")
        except Exception:
            tiers = {}
        out.append(Snapshot(
            snapshot_date=r["snapshot_date"],
            mrr_cents=int(r["mrr_cents"] or 0),
            new_mrr_cents=int(r["new_mrr_cents"] or 0),
            churn_mrr_cents=int(r["churn_mrr_cents"] or 0),
            expansion_cents=int(r["expansion_cents"] or 0),
            contraction_cents=int(r["contraction_cents"] or 0),
            failed_payments_count=int(r["failed_payments_count"] or 0),
            failed_payments_cents=int(r["failed_payments_cents"] or 0),
            nrr_pct=float(r["nrr_pct"] or 100.0),
            active_subs=int(r["active_subs"] or 0),
            top_customer_share=float(r["top_customer_share"] or 0.0),
            tier_breakdown=tiers,
        ))
    out.reverse()  # chronological order
    return out


# ── Demo seeders (no Stripe key required) ─────────────────────────────────────

def _seed_demo_snapshots(reset: bool = True) -> list[Snapshot]:
    """30 days of synthetic snapshots designed to trip churn cluster, failed
    payment leakage, and NRR drop. Deterministic via a fixed seed."""
    init_db()
    if reset:
        with _connect() as conn:
            conn.execute("DELETE FROM revenue_snapshots")
            conn.execute("DELETE FROM revenue_verdicts")

    rng = random.Random(0xF0_4_5EA7)
    today = datetime.now(timezone.utc).date()
    snapshots: list[Snapshot] = []

    # Baseline trajectory: steady growth for first 21 days, then trouble.
    base_mrr = 184_000_00  # $184k MRR in cents
    base_subs = 312
    tiers_base = {"Starter ($49)": 198, "Growth ($149)": 92, "Studio ($399)": 22}

    for i in range(30):
        d = today - timedelta(days=29 - i)
        ds = d.isoformat()

        if i < 21:
            mrr = int(base_mrr * (1 + 0.012 * i))                # ~1.2% daily ramp
            churn_mrr = int(rng.uniform(800_00, 1_400_00))       # ~$800-$1.4k/day churn
            new_mrr  = int(rng.uniform(2_400_00, 3_200_00))      # healthy net add
            failed_n = int(rng.uniform(2, 6))
            failed_c = int(rng.uniform(400_00, 900_00))
            subs     = int(base_subs + i * 1.4)
            top_share = round(rng.uniform(0.07, 0.10), 3)
        else:
            # Last 9 days: churn cluster (~3x baseline) + failed payment leakage spike.
            day_in_cluster = i - 20
            mrr = int(base_mrr * (1 + 0.012 * 21) - day_in_cluster * 1_900_00)
            churn_mrr = int(rng.uniform(3_400_00, 5_100_00))
            new_mrr  = int(rng.uniform(2_100_00, 2_800_00))
            failed_n = int(rng.uniform(28, 42))
            failed_c = int(rng.uniform(11_500_00, 16_400_00))
            subs     = int(base_subs + 21 * 1.4 - day_in_cluster * 4)
            top_share = round(rng.uniform(0.18, 0.24), 3)        # concentration crept up

        nrr = 100.0 if i == 0 else round(100.0 * mrr / snapshots[0].mrr_cents, 2)

        # Slight tier collapse in the back half on Starter.
        tiers = dict(tiers_base)
        if i >= 21:
            tiers["Starter ($49)"] = int(tiers_base["Starter ($49)"] * (1 - 0.04 * (i - 20)))
            tiers["Growth ($149)"] = int(tiers_base["Growth ($149)"] * (1 + 0.005 * (i - 20)))

        snap = Snapshot(
            snapshot_date=ds,
            mrr_cents=mrr,
            new_mrr_cents=new_mrr,
            churn_mrr_cents=churn_mrr,
            expansion_cents=int(rng.uniform(200_00, 600_00)),
            contraction_cents=int(rng.uniform(80_00, 300_00)),
            failed_payments_count=failed_n,
            failed_payments_cents=failed_c,
            nrr_pct=nrr,
            active_subs=subs,
            top_customer_share=top_share,
            tier_breakdown=tiers,
        )
        snapshots.append(snap)
        save_snapshot(snap)
    return snapshots


# ── Anomaly rules ─────────────────────────────────────────────────────────────

def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


def detect_anomalies(snapshots: list[Snapshot]) -> list[Anomaly]:
    """Run the six anomaly rules over the snapshot history.

    Each rule is intentionally conservative: it fires only when there is enough
    history (>= 7 days) and the deviation is material.
    """
    if not snapshots:
        return []
    today = snapshots[-1]
    history = snapshots[:-1]
    out: list[Anomaly] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1) CHURN CLUSTER -- 7d trailing churn vs 90d baseline
    if len(history) >= 7:
        last7 = [s.churn_mrr_cents for s in snapshots[-7:]]
        baseline_window = snapshots[-min(len(snapshots), 90):-7] or history
        baseline = _avg([s.churn_mrr_cents for s in baseline_window])
        recent = _avg(last7)
        if baseline > 0 and recent / baseline >= 1.5:
            out.append(Anomaly(
                rule="churn_cluster",
                priority="P0",
                headline=f"7d churn rate {recent/baseline:.1f}x trailing 90d baseline",
                evidence={
                    "last7_avg_churn_cents": int(recent),
                    "baseline_avg_churn_cents": int(baseline),
                    "ratio": round(recent / baseline, 2),
                    "series": [{"date": s.snapshot_date, "churn_cents": s.churn_mrr_cents} for s in snapshots[-14:]],
                },
                detected_at=now_iso,
            ))

    # 2) NRR DROP -- crossed below 100% for the first time in 30 days
    if len(snapshots) >= 30:
        recent_nrr = today.nrr_pct
        prior_30 = [s.nrr_pct for s in snapshots[-30:-1]]
        if recent_nrr < 100.0 and all(n >= 100.0 for n in prior_30[-7:]) and recent_nrr <= 99.5:
            out.append(Anomaly(
                rule="nrr_drop",
                priority="P0",
                headline=f"NRR fell to {recent_nrr:.1f}% (first dip below 100% in 30d)",
                evidence={
                    "current_nrr_pct": recent_nrr,
                    "previous_7d_min": min(prior_30[-7:]) if prior_30 else None,
                    "series": [{"date": s.snapshot_date, "nrr_pct": s.nrr_pct} for s in snapshots[-30:]],
                },
                detected_at=now_iso,
            ))

    # 3) FAILED PAYMENT LEAKAGE -- failed $ > 5% of MRR for 7+ days
    if len(snapshots) >= 7:
        recent7 = snapshots[-7:]
        breaches = sum(
            1 for s in recent7
            if s.mrr_cents > 0 and (s.failed_payments_cents / s.mrr_cents) > 0.05
        )
        if breaches >= 5:
            avg_pct = _avg([100.0 * s.failed_payments_cents / s.mrr_cents for s in recent7 if s.mrr_cents > 0])
            out.append(Anomaly(
                rule="failed_payment_leakage",
                priority="P1",
                headline=f"Failed payments averaging {avg_pct:.1f}% of MRR over 7 days",
                evidence={
                    "avg_pct_of_mrr": round(avg_pct, 2),
                    "total_failed_cents_7d": sum(s.failed_payments_cents for s in recent7),
                    "series": [{"date": s.snapshot_date, "failed_cents": s.failed_payments_cents, "mrr_cents": s.mrr_cents} for s in recent7],
                },
                detected_at=now_iso,
            ))

    # 4) CONCENTRATION RISK -- top customer > 20% of ARR
    if today.top_customer_share >= 0.20:
        out.append(Anomaly(
            rule="concentration_risk",
            priority="P1",
            headline=f"Top customer is {today.top_customer_share*100:.1f}% of ARR (board-meeting question)",
            evidence={
                "top_share_pct": round(today.top_customer_share * 100, 2),
                "active_subs": today.active_subs,
                "mrr_cents": today.mrr_cents,
            },
            detected_at=now_iso,
        ))

    # 5) EXPANSION STALL -- expansion MRR < 50% of trailing 90d avg
    if len(snapshots) >= 14:
        recent_exp = _avg([s.expansion_cents for s in snapshots[-7:]])
        baseline_exp = _avg([s.expansion_cents for s in snapshots[-min(len(snapshots), 90):-7]])
        if baseline_exp > 0 and recent_exp < baseline_exp * 0.5:
            out.append(Anomaly(
                rule="expansion_stall",
                priority="P2",
                headline=f"Expansion MRR collapsed to {100*recent_exp/baseline_exp:.0f}% of 90d baseline",
                evidence={
                    "recent_avg_expansion_cents": int(recent_exp),
                    "baseline_avg_expansion_cents": int(baseline_exp),
                    "series": [{"date": s.snapshot_date, "expansion_cents": s.expansion_cents} for s in snapshots[-30:]],
                },
                detected_at=now_iso,
            ))

    # 6) PRICING TIER COLLAPSE -- any tier loses > 25% of subs in 30d
    if len(snapshots) >= 30:
        first = snapshots[-30].tier_breakdown or {}
        last = today.tier_breakdown or {}
        for tier, start_count in first.items():
            end_count = last.get(tier, 0)
            if start_count >= 20 and end_count <= 0.75 * start_count:
                drop_pct = 100.0 * (start_count - end_count) / start_count
                out.append(Anomaly(
                    rule="pricing_tier_collapse",
                    priority="P1",
                    headline=f"{tier} tier lost {drop_pct:.0f}% of subs in 30d",
                    evidence={
                        "tier": tier,
                        "start_count": int(start_count),
                        "end_count": int(end_count),
                        "drop_pct": round(drop_pct, 1),
                    },
                    detected_at=now_iso,
                ))
                break  # one tier-collapse verdict per scan
    return out


# ── Verdict synthesis (uses the existing 4-advisor debate) ────────────────────

VERDICT_INSTRUCTIONS = """You are the FOURSEAT ORACLE verdict engine.

You receive: (a) a structured revenue anomaly with evidence, and (b) a transcript
of a 4-advisor Boardroom debate (Strategy, Finance, Tech, Contrarian).

Compress this into ONE machine-readable verdict. Be ruthless. No prose outside JSON.
No em dashes anywhere.

Output ONLY valid JSON with this exact shape:
{
  "one_liner":       "max 24 words, the single sentence the founder must read",
  "strategy_view":   "max 35 words, Chief Strategy Officer angle",
  "finance_view":    "max 35 words, CFO angle, prefer numbers",
  "tech_view":       "max 35 words, CTO / data-systems angle",
  "contrarian_view": "max 35 words, contrarian stress-test",
  "actions":         ["action 1", "action 2", "action 3"],
  "watch_metrics":   ["metric 1 to confirm/falsify next week", "metric 2"],
  "confidence":      "High | Medium | Low"
}
Return ONLY the JSON object.
"""


def _build_debate_question(anomaly: Anomaly) -> tuple[str, str]:
    evidence_blob = json.dumps(anomaly.evidence, default=str)[:1800]
    question = (
        "An anomaly was just detected in the company's Stripe revenue data. "
        "Should the founder treat this as urgent, what is the single best next action, "
        "and what should they watch next week to confirm or falsify the hypothesis?\n\n"
        f"ANOMALY RULE: {anomaly.rule}\n"
        f"PRIORITY (heuristic): {anomaly.priority}\n"
        f"HEADLINE: {anomaly.headline}\n"
        f"EVIDENCE (JSON): {evidence_blob}"
    )
    context = (
        f"Detected at: {anomaly.detected_at}\n"
        "Channel: stripe-oracle\n"
        "The advisor panel should answer with crisp opinions, not generic frameworks."
    )
    return question, context


_UPSTREAM_ERROR_PREFIXES = (
    "[claude unavailable", "[gpt-4 unavailable", "[gemini unavailable",
    "[nia.ai unavailable", "[cerebras unavailable", "[nvidia unavailable",
    "[summary unavailable",
)


def _is_upstream_error(text: str) -> bool:
    if not text:
        return False
    head = text.strip().lower()[:64]
    return any(head.startswith(p) for p in _UPSTREAM_ERROR_PREFIXES)


def _advisor_text(src: str, lens: str) -> str:
    text = (src or "").strip()
    if not text or _is_upstream_error(text):
        return f"[{lens} advisor offline; review raw debate]"
    return text[:280]


def synthesize_verdict(anomaly: Anomaly) -> RevenueVerdict:
    """Run the 4-advisor debate and compress it into a structured verdict."""
    from backend.debate_engine import run_debate, ask_claude  # local import

    question, context = _build_debate_question(anomaly)
    try:
        debate = run_debate(question=question, context=context)
    except Exception as exc:
        log.warning("oracle debate failed for %s: %s", anomaly.rule, exc)
        debate = {"chairman": {}, "round2": {}, "round1": {}}

    chairman = debate.get("chairman", {}) if isinstance(debate.get("chairman"), dict) else {}
    round2 = debate.get("round2", {}) if isinstance(debate.get("round2"), dict) else {}

    transcript = json.dumps({
        "strategy":   round2.get("claude", ""),
        "finance":    round2.get("gpt4", ""),
        "tech":       round2.get("gemini", ""),
        "contrarian": round2.get("contrarian", ""),
        "chairman":   chairman,
    }, ensure_ascii=False)

    prompt = (
        f"ANOMALY:\nRule: {anomaly.rule}\nPriority: {anomaly.priority}\n"
        f"Headline: {anomaly.headline}\nEvidence: {json.dumps(anomaly.evidence, default=str)[:1500]}\n\n"
        f"BOARDROOM DEBATE (JSON):\n{transcript}\n\n"
        f"Produce the Oracle verdict JSON now."
    )

    raw = ""
    try:
        raw = ask_claude(prompt, VERDICT_INSTRUCTIONS) or ""
    except Exception as exc:
        log.warning("oracle verdict synth failed: %s", exc)

    data: dict = {}
    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        if cleaned:
            data = json.loads(cleaned)
    except Exception:
        data = {}

    def _pick(key: str, default: str) -> str:
        v = data.get(key)
        return v if isinstance(v, str) and v.strip() else default

    actions_raw = data.get("actions")
    actions = [str(a)[:200] for a in actions_raw if isinstance(a, str) and a.strip()] if isinstance(actions_raw, list) else []
    if not actions:
        actions = _fallback_actions(anomaly)
    actions = actions[:5]

    watch_raw = data.get("watch_metrics")
    watch = [str(w)[:160] for w in watch_raw if isinstance(w, str) and w.strip()] if isinstance(watch_raw, list) else []
    if not watch:
        watch = _fallback_watch(anomaly)
    watch = watch[:4]

    confidence = _pick("confidence", chairman.get("confidence", "Medium") if isinstance(chairman, dict) else "Medium")
    if confidence not in ("High", "Medium", "Low"):
        confidence = "Medium"

    chairman_verdict = chairman.get("verdict") if isinstance(chairman, dict) else ""
    default_one_liner = (
        chairman_verdict
        if chairman_verdict and not _is_upstream_error(chairman_verdict) and not _looks_like_free_template(chairman_verdict)
        else _fallback_one_liner(anomaly)
    )

    def _resolve_view(role: str, llm_field: str, debate_field: str) -> str:
        # Order of preference: structured JSON synth > 4-advisor debate > rule-specific fallback.
        for candidate in (data.get(llm_field), round2.get(debate_field)):
            text = (candidate or "").strip()
            if text and not _is_upstream_error(text) and not _looks_like_free_template(text):
                return text[:280]
        return _fallback_panel_view(anomaly.rule, role)

    return RevenueVerdict(
        rule=anomaly.rule,
        priority=anomaly.priority,
        one_liner=_pick("one_liner", default_one_liner)[:280],
        evidence=anomaly.evidence,
        strategy_view=_resolve_view("Strategy",   "strategy_view",   "claude"),
        finance_view=_resolve_view("Finance",     "finance_view",    "gpt4"),
        tech_view=_resolve_view("Technology",     "tech_view",       "gemini"),
        contrarian_view=_resolve_view("Contrarian","contrarian_view","contrarian"),
        actions=actions,
        watch_metrics=watch,
        confidence=confidence,
        detected_at=anomaly.detected_at,
    )


_FREE_MODE_GIVEAWAYS = (
    "proceed in staged milestones",
    "position (",
    "key adjustment:",
)


def _looks_like_free_template(text: str) -> bool:
    if not text:
        return True
    head = text.strip().lower()[:90]
    return any(g in head for g in _FREE_MODE_GIVEAWAYS)


_FALLBACK_PANELS = {
    "churn_cluster": {
        "Strategy":   "A 3x churn spike in one segment is a positioning signal, not a retention problem. Investigate which ICP just stopped fitting.",
        "Finance":    "If this rate continues, you'll lose roughly one quarter's worth of NRR by month-end. The recovery cost is 4-6x save vs replace.",
        "Technology": "Cross-reference cancellation events against the last 14 days of releases and feature flag flips. Suspect a regression first, not a market shift.",
        "Contrarian": "Maybe this is healthy churn and you're shedding the wrong ICP. Don't fix it, accelerate it; reroute the saved CAC to your real customer.",
    },
    "nrr_drop": {
        "Strategy":   "NRR below 100% kills the SaaS expansion narrative for fundraising. You have one quarter to fix it before the metric becomes a story.",
        "Finance":    "Model contracted revenue replaced through expansion. If contraction outruns net-new for 60 days, growth is now a leaky bucket.",
        "Technology": "Wire a daily NRR alert and tag every churned account with its last 30 days of usage data. You need cause attribution, not a dashboard.",
        "Contrarian": "You raised the price 90 days ago and called it 'pricing strength'. This is the cost. Roll back grandfathered accounts before more leave.",
    },
    "failed_payment_leakage": {
        "Strategy":   "Failed payments at this rate signal payment-method decay or bot-driven sign-ups. Don't conflate with churn until you triage.",
        "Finance":    "At 5%+ of MRR, this is real money on the floor every week. Smart Retries plus a 14-day rescue email plays back ~40% in industry benchmarks.",
        "Technology": "Enable Stripe Smart Retries with a custom 3/7/14 cadence and surface payment-update prompts in-app, not just email.",
        "Contrarian": "Your dunning copy is bank-form English. Send a one-line founder email to anyone over $1k - friction beats automation here.",
    },
    "concentration_risk": {
        "Strategy":   "20%+ ARR concentration kills enterprise valuations and stalls late-stage rounds. Get ahead of it before the board asks.",
        "Finance":    "Stress-test your model assuming the top customer churns at renewal. If that breaks the next 12 months, you have a single-customer business.",
        "Technology": "Audit data isolation, SLA exposure, and integration depth for the top customer. Concentration risk is also operational risk.",
        "Contrarian": "Don't de-risk the customer, expand them. The fastest way out of concentration is multi-product penetration, not new logos.",
    },
    "expansion_stall": {
        "Strategy":   "Expansion stall almost always precedes net-new stall by 60 days. Your acquisition pipeline doesn't know yet, but it will.",
        "Finance":    "Re-run the upsell motion that worked best last quarter and double the trigger threshold for 14 days. Cheap to reverse if wrong.",
        "Technology": "Identify usage spikes in non-paying accounts; the upsell list lives in the product analytics, not the CRM.",
        "Contrarian": "If your roadmap killed the upsell trigger, that's not stall, that's a self-inflicted wound. Audit the last release.",
    },
    "pricing_tier_collapse": {
        "Strategy":   "A 25%+ tier drop is product-market mismatch on that tier, not pricing. The cure is value props, not discounts.",
        "Finance":    "Compute LTV by tier before you act. If the collapsing tier had the worst LTV anyway, this is healthy collapse, not a fire.",
        "Technology": "Survey downgraders inline at the cancel step with one mandatory question. You'll hear the real reason within a week.",
        "Contrarian": "Kill the tier. Tiers exist to herd customers; if no one wants this one, it's a tax on your roadmap, not a feature.",
    },
}


def _fallback_panel_view(rule: str, role: str) -> str:
    table = _FALLBACK_PANELS.get(rule, {})
    return table.get(role, f"[{role} advisor view unavailable for {rule}]")


def _fallback_one_liner(a: Anomaly) -> str:
    if a.rule == "churn_cluster":
        return "A concentrated churn cluster just appeared in your $500-$2k ARR segment; treat it as a product-market signal, not a pricing one."
    if a.rule == "nrr_drop":
        return "NRR fell below 100% for the first time in 30 days; expansion isn't covering churn anymore."
    if a.rule == "failed_payment_leakage":
        return "Failed payments are leaking real money; rescue cadence is the highest-ROI lever this week."
    if a.rule == "concentration_risk":
        return "Your top customer is now an unhealthy share of ARR; the board will ask, prepare a story before they do."
    if a.rule == "expansion_stall":
        return "Expansion MRR collapsed; your growth motion is now reliant on net-new only, which is more fragile."
    if a.rule == "pricing_tier_collapse":
        return "A pricing tier is rapidly losing subscribers; this is usually product-market mismatch, not pricing."
    return f"Revenue anomaly detected: {a.headline}."


def _fallback_actions(a: Anomaly) -> list[str]:
    if a.rule == "churn_cluster":
        return [
            "Pull churned customer list and run 5 same-day exit interviews",
            "Cross-reference churn cohort with last 14 days of product releases",
            "Pause non-critical pricing changes until cluster cause is known",
        ]
    if a.rule == "nrr_drop":
        return [
            "Identify top 10 contracted accounts at expansion risk this quarter",
            "Convert one usage-based contract to a guaranteed minimum",
            "Brief CSM on a 14-day proactive expansion outreach push",
        ]
    if a.rule == "failed_payment_leakage":
        return [
            "Enable Stripe Smart Retries with custom 3/7/14 day cadence",
            "Send personal outreach on any failed invoice over $1,000",
            "Ship dunning email v2 with payment-method update link",
        ]
    if a.rule == "concentration_risk":
        return [
            "Draft a 1-slide concentration narrative for next board meeting",
            "Audit contract for renewal date and termination clauses",
            "Build a top-customer succession plan in case of churn",
        ]
    if a.rule == "expansion_stall":
        return [
            "Re-run the expansion campaign that worked best in the prior 90 days",
            "Identify usage spikes in non-paying accounts as expansion targets",
            "Tighten the upsell trigger threshold by 20% for 2 weeks",
        ]
    if a.rule == "pricing_tier_collapse":
        return [
            "Survey the 10 most recent tier-downgraders for the real reason",
            "Audit the tier's value props vs. the next tier up",
            "Test a feature-gate rollback for the affected tier",
        ]
    return ["Triage manually with finance lead", "Document and revisit in 7 days"]


def _fallback_watch(a: Anomaly) -> list[str]:
    if a.rule == "churn_cluster":
        return ["Churn rate by ARR segment, daily for the next 14 days", "Net new logos in the same segment"]
    if a.rule == "nrr_drop":
        return ["NRR weekly", "Expansion MRR week-over-week"]
    if a.rule == "failed_payment_leakage":
        return ["Failed invoice $ recovered within 14 days", "Payment-method update rate from dunning emails"]
    if a.rule == "concentration_risk":
        return ["Top-3 customer ARR as % of total", "ARR pipeline weighted by stage"]
    if a.rule == "expansion_stall":
        return ["Expansion MRR weekly", "Upsell email click-through rate"]
    if a.rule == "pricing_tier_collapse":
        return ["Subscriber count by tier weekly", "Downgrade reason categorical breakdown"]
    return ["MRR daily", "NRR weekly"]


# ── Persistence for verdicts ──────────────────────────────────────────────────

def _verdict_fingerprint(v: RevenueVerdict) -> str:
    # One verdict per rule per UTC day; re-runs update rather than duplicate.
    day = v.detected_at[:10]
    return hashlib.sha256(f"{v.rule}:{day}".encode()).hexdigest()[:24]


def save_verdict(v: RevenueVerdict) -> int:
    init_db()
    fp = _verdict_fingerprint(v)
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO revenue_verdicts (
                fingerprint, rule, priority, one_liner, evidence_json,
                strategy_view, finance_view, tech_view, contrarian_view,
                actions_json, watch_metrics_json, confidence, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                priority           = excluded.priority,
                one_liner          = excluded.one_liner,
                evidence_json      = excluded.evidence_json,
                strategy_view      = excluded.strategy_view,
                finance_view       = excluded.finance_view,
                tech_view          = excluded.tech_view,
                contrarian_view    = excluded.contrarian_view,
                actions_json       = excluded.actions_json,
                watch_metrics_json = excluded.watch_metrics_json,
                confidence         = excluded.confidence,
                detected_at        = excluded.detected_at
            """,
            (
                fp, v.rule, v.priority, v.one_liner, json.dumps(v.evidence, default=str),
                v.strategy_view, v.finance_view, v.tech_view, v.contrarian_view,
                json.dumps(v.actions), json.dumps(v.watch_metrics), v.confidence,
                v.detected_at,
            ),
        )
        return int(cur.lastrowid or 0)


def list_verdicts(limit: int = 20, *, include_resolved: bool = False) -> list[dict]:
    init_db()
    where = "" if include_resolved else "WHERE resolved = 0"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM revenue_verdicts {where} ORDER BY "
            "CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END, "
            "detected_at DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        try:
            evidence = json.loads(r["evidence_json"] or "{}")
        except Exception:
            evidence = {}
        try:
            actions = json.loads(r["actions_json"] or "[]")
        except Exception:
            actions = []
        try:
            watch = json.loads(r["watch_metrics_json"] or "[]")
        except Exception:
            watch = []
        out.append({
            "id": r["id"],
            "rule": r["rule"],
            "priority": r["priority"],
            "one_liner": r["one_liner"],
            "evidence": evidence,
            "strategy_view": r["strategy_view"],
            "finance_view": r["finance_view"],
            "tech_view": r["tech_view"],
            "contrarian_view": r["contrarian_view"],
            "actions": actions,
            "watch_metrics": watch,
            "confidence": r["confidence"],
            "detected_at": r["detected_at"],
            "resolved": bool(r["resolved"]),
            "deck_filename": r["deck_filename"],
        })
    return out


def mark_verdict_resolved(verdict_id: int, resolved: bool = True) -> bool:
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE revenue_verdicts SET resolved = ? WHERE id = ?",
            (1 if resolved else 0, int(verdict_id)),
        )
        return cur.rowcount > 0


def attach_deck_filename(verdict_id: int, filename: str) -> bool:
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE revenue_verdicts SET deck_filename = ? WHERE id = ?",
            (filename[:200], int(verdict_id)),
        )
        return cur.rowcount > 0


def verdict_stats() -> dict:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT priority, COUNT(*) AS n FROM revenue_verdicts WHERE resolved = 0 GROUP BY priority"
        ).fetchall()
    counts = {r["priority"]: int(r["n"]) for r in rows}
    return {
        "total_open": sum(counts.values()),
        "by_priority": {p: counts.get(p, 0) for p in ("P0", "P1", "P2", "P3")},
    }


def latest_snapshot() -> Optional[Snapshot]:
    snaps = load_snapshots(limit=1)
    return snaps[-1] if snaps else None


def snapshot_summary(limit: int = 90) -> dict:
    snaps = load_snapshots(limit=limit)
    if not snaps:
        return {"count": 0}
    today = snaps[-1]
    prior = snaps[-2] if len(snaps) >= 2 else None
    week_ago = snaps[-8] if len(snaps) >= 8 else snaps[0]

    def _pct_change(now: float, then: float) -> Optional[float]:
        if then == 0:
            return None
        return round(100.0 * (now - then) / then, 2)

    return {
        "count": len(snaps),
        "today": {
            "snapshot_date": today.snapshot_date,
            "mrr_cents": today.mrr_cents,
            "active_subs": today.active_subs,
            "nrr_pct": today.nrr_pct,
            "failed_payments_cents": today.failed_payments_cents,
            "failed_payments_count": today.failed_payments_count,
            "top_customer_share": today.top_customer_share,
        },
        "deltas": {
            "mrr_d1_pct": _pct_change(today.mrr_cents, prior.mrr_cents) if prior else None,
            "mrr_d7_pct": _pct_change(today.mrr_cents, week_ago.mrr_cents),
            "nrr_d7_delta": round(today.nrr_pct - week_ago.nrr_pct, 2),
        },
        "series": [
            {
                "date": s.snapshot_date,
                "mrr_cents": s.mrr_cents,
                "nrr_pct": s.nrr_pct,
                "churn_mrr_cents": s.churn_mrr_cents,
                "failed_payments_cents": s.failed_payments_cents,
            }
            for s in snaps
        ],
    }


def connector_status() -> dict[str, Any]:
    return {
        "stripe": {
            "configured": stripe_configured(),
            "webhook_signed": bool(STRIPE_WEBHOOK_SECRET),
            "api_version": STRIPE_API_VERSION,
        }
    }


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_oracle_scan(*, demo: Optional[bool] = None, force_reseed: bool = False) -> dict:
    """End-to-end: refresh snapshot, detect anomalies, debate, persist verdicts."""
    init_db()

    if demo is None:
        demo = not stripe_configured()

    if demo:
        snaps = load_snapshots(limit=90)
        if force_reseed or len(snaps) < 30:
            _seed_demo_snapshots(reset=True)
            snaps = load_snapshots(limit=90)
    else:
        try:
            snap = compute_snapshot_from_stripe()
            save_snapshot(snap)
        except Exception as exc:
            log.warning("oracle live snapshot failed, falling back to last-known: %s", exc)
        snaps = load_snapshots(limit=90)

    anomalies = detect_anomalies(snaps)
    verdicts: list[RevenueVerdict] = []
    for a in anomalies:
        try:
            v = synthesize_verdict(a)
        except Exception as exc:
            log.warning("oracle verdict failed for %s: %s", a.rule, exc)
            v = RevenueVerdict(
                rule=a.rule,
                priority=a.priority,
                one_liner=_fallback_one_liner(a),
                evidence=a.evidence,
                strategy_view="[Strategy advisor offline]",
                finance_view="[Finance advisor offline]",
                tech_view="[Technology advisor offline]",
                contrarian_view="[Contrarian advisor offline]",
                actions=_fallback_actions(a),
                watch_metrics=_fallback_watch(a),
                confidence="Low",
                detected_at=a.detected_at,
            )
        save_verdict(v)
        verdicts.append(v)

    return {
        "mode": "demo" if demo else "live",
        "snapshot_count": len(snaps),
        "anomalies_detected": len(anomalies),
        "verdicts_persisted": len(verdicts),
        "summary": snapshot_summary(limit=60),
        "verdicts": list_verdicts(limit=20),
        "stats": verdict_stats(),
        "connectors": connector_status(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Deck generation handoff ──────────────────────────────────────────────────

def build_deck_payload(verdict: dict, *, company_name: str = "Fourseat") -> dict:
    """Translate a stored verdict into the shape board_brief.generate_board_deck expects."""
    period = datetime.now(timezone.utc).strftime("Revenue Health, %B %d %Y")
    ev = verdict.get("evidence", {}) or {}
    metrics = {}
    if "ratio" in ev:
        metrics["Churn vs baseline"] = f"{ev['ratio']:.2f}x"
    if "current_nrr_pct" in ev:
        metrics["NRR today"] = f"{ev['current_nrr_pct']:.1f}%"
    if "avg_pct_of_mrr" in ev:
        metrics["Failed $ / MRR"] = f"{ev['avg_pct_of_mrr']:.1f}%"
    if "top_share_pct" in ev:
        metrics["Top customer ARR"] = f"{ev['top_share_pct']:.1f}%"
    if "drop_pct" in ev:
        metrics["Tier subscriber drop"] = f"{ev['drop_pct']:.0f}%"
    if not metrics:
        metrics["Priority"] = verdict.get("priority", "P2")
        metrics["Confidence"] = verdict.get("confidence", "Medium")

    highlights = "\n".join(f"- {a}" for a in verdict.get("actions", []) or [])
    challenges = (
        f"Strategy: {verdict.get('strategy_view','')}\n"
        f"Finance: {verdict.get('finance_view','')}\n"
        f"Tech: {verdict.get('tech_view','')}\n"
        f"Contrarian: {verdict.get('contrarian_view','')}"
    )
    ask = "\n".join(f"- Watch: {m}" for m in verdict.get("watch_metrics", []) or [])
    return {
        "company_name": company_name,
        "period": period,
        "metrics": metrics,
        "highlights": highlights or verdict.get("one_liner", ""),
        "challenges": challenges,
        "ask": ask or "Confirm or falsify the hypothesis next week.",
    }


if __name__ == "__main__":
    out = run_oracle_scan(demo=True, force_reseed=True)
    print(json.dumps({k: v for k, v in out.items() if k != "verdicts"}, indent=2))
    for v in out["verdicts"]:
        print(f"\n[{v['priority']}] {v['rule']}: {v['one_liner']}")
