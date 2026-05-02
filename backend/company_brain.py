"""
Fourseat Company Brain.

The unified ingestion + reasoning layer that makes a company legible to AI by default.

Connectors (token-based, no OAuth dance):
    - Slack          : SLACK_BOT_TOKEN + SLACK_CHANNEL_IDS
    - GitHub         : GITHUB_TOKEN + GITHUB_REPOS  (comma-separated owner/repo)
    - Linear         : LINEAR_API_KEY
    - QuickBooks     : QUICKBOOKS_ACCESS_TOKEN + QUICKBOOKS_REALM_ID
    - Notion         : NOTION_API_KEY (stub for now)

Pipeline:
    fetch_<source>()  -> [Artifact]
    ingest_<source>() -> persist into `artifacts` (FTS5-indexed, idempotent)
    detect_closed_loop_signals() -> cross-source signals fired into `brain_signals`
    synthesize_signal_verdict()  -> 4-advisor debate + structured JSON verdict
    query_brain(question)        -> FTS5 retrieval + LLM-or-fallback synthesis

Demo mode:
    With no tokens, seed_demo_artifacts() produces ~40 realistic artifacts that
    intentionally trip 3+ closed-loop rules so the live demo is always sharp.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(): return None

load_dotenv()
log = logging.getLogger("fourseat.brain")


# ── Paths & config ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = Path("/tmp/fourseat-data") if os.getenv("VERCEL") else (BASE_DIR / "data")
DATA_DIR = Path(os.getenv("FOURSEAT_DATA_DIR", str(DEFAULT_DATA_DIR)))
BRAIN_DIR = DATA_DIR / "brain"
BRAIN_DIR.mkdir(parents=True, exist_ok=True)

DB_URL = os.getenv("BRAIN_DB_URL", f"sqlite:///{BRAIN_DIR / 'brain.db'}")

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "").strip()
SLACK_CHANNEL_IDS = [c.strip() for c in os.getenv("SLACK_CHANNEL_IDS", "").split(",") if c.strip()]
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "").strip()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPOS = [r.strip() for r in os.getenv("GITHUB_REPOS", "").split(",") if r.strip()]
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()

LINEAR_API_KEY = os.getenv("LINEAR_API_KEY", "").strip()
LINEAR_WEBHOOK_SECRET = os.getenv("LINEAR_WEBHOOK_SECRET", "").strip()

QUICKBOOKS_ACCESS_TOKEN = os.getenv("QUICKBOOKS_ACCESS_TOKEN", "").strip()
QUICKBOOKS_REALM_ID = os.getenv("QUICKBOOKS_REALM_ID", "").strip()
QUICKBOOKS_BASE_URL = os.getenv("QUICKBOOKS_BASE_URL", "https://quickbooks.api.intuit.com").rstrip("/")

NOTION_API_KEY = os.getenv("NOTION_API_KEY", "").strip()

HTTP_TIMEOUT = float(os.getenv("BRAIN_HTTP_TIMEOUT", "12"))
INGEST_PAGE_LIMIT = int(os.getenv("BRAIN_INGEST_LIMIT", "60"))


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Artifact:
    source: str           # slack | github | linear | notion | quickbooks
    artifact_type: str    # message | pr | issue | doc | invoice
    external_id: str
    title: str
    body: str
    author: str = ""
    url: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: str = ""

    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.source}:{self.external_id}".encode()).hexdigest()[:24]


@dataclass
class ClosedLoopSignal:
    rule: str
    priority: str
    headline: str
    evidence: dict[str, Any]
    involved_artifact_ids: list[int]
    detected_at: str


@dataclass
class SignalVerdict:
    rule: str
    priority: str
    one_liner: str
    evidence: dict[str, Any]
    involved_artifact_ids: list[int]
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
        raise RuntimeError("BRAIN_DB_URL only supports sqlite:/// here.")
    path = DB_URL.replace("sqlite:///", "", 1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    schema_file = BASE_DIR / "backend" / "brain_schema.sql"
    if not schema_file.exists():
        raise FileNotFoundError(f"brain schema missing at {schema_file}")
    with _connect() as conn:
        conn.executescript(schema_file.read_text())


def _upsert_artifact(conn: sqlite3.Connection, art: Artifact) -> int:
    """Idempotent insert into artifacts + FTS mirror. Returns row id."""
    fp = art.fingerprint()
    cur = conn.execute(
        """
        INSERT INTO artifacts (
            fingerprint, source, artifact_type, external_id, title, body, author, url,
            tags_json, metadata_json, occurred_at, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fingerprint) DO UPDATE SET
            title         = excluded.title,
            body          = excluded.body,
            author        = excluded.author,
            url           = excluded.url,
            tags_json     = excluded.tags_json,
            metadata_json = excluded.metadata_json,
            occurred_at   = excluded.occurred_at
        """,
        (
            fp, art.source, art.artifact_type, art.external_id,
            art.title[:500], art.body[:6000], art.author[:200], art.url[:500],
            json.dumps(art.tags), json.dumps(art.metadata, default=str),
            art.occurred_at or datetime.now(timezone.utc).isoformat(),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    row = conn.execute("SELECT id FROM artifacts WHERE fingerprint=?", (fp,)).fetchone()
    rid = int(row["id"]) if row else int(cur.lastrowid or 0)
    # Refresh FTS row.
    conn.execute("DELETE FROM artifacts_fts WHERE rowid=?", (rid,))
    conn.execute(
        "INSERT INTO artifacts_fts(rowid, title, body, author, tags) VALUES (?,?,?,?,?)",
        (rid, art.title[:500], art.body[:6000], art.author[:200], " ".join(art.tags)),
    )
    return rid


def upsert_artifacts(arts: Iterable[Artifact]) -> list[int]:
    init_db()
    ids: list[int] = []
    with _connect() as conn:
        for a in arts:
            try:
                ids.append(_upsert_artifact(conn, a))
            except Exception as exc:
                log.warning("artifact upsert failed (%s/%s): %s", a.source, a.external_id, exc)
    return ids


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _http_get(url: str, headers: dict, params: Optional[dict] = None) -> dict:
    import requests
    resp = requests.get(url, headers=headers, params=params or {}, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"GET {url} -> {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _http_post(url: str, headers: dict, json_body: Optional[dict] = None) -> dict:
    import requests
    resp = requests.post(url, headers=headers, json=json_body, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"POST {url} -> {resp.status_code}: {resp.text[:200]}")
    return resp.json()


# ── Slack connector ───────────────────────────────────────────────────────────

def slack_configured() -> bool:
    return bool(SLACK_BOT_TOKEN) and bool(SLACK_CHANNEL_IDS)


def fetch_slack(limit_per_channel: int = 25) -> list[Artifact]:
    if not slack_configured():
        return []
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    out: list[Artifact] = []
    for channel_id in SLACK_CHANNEL_IDS:
        try:
            data = _http_get(
                "https://slack.com/api/conversations.history",
                headers,
                {"channel": channel_id, "limit": limit_per_channel},
            )
        except Exception as exc:
            log.warning("slack fetch failed for %s: %s", channel_id, exc)
            continue
        if not data.get("ok"):
            log.warning("slack api error for %s: %s", channel_id, data.get("error"))
            continue
        for msg in data.get("messages", []):
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            ts = str(msg.get("ts") or "")
            try:
                occurred = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
            except Exception:
                occurred = datetime.now(timezone.utc).isoformat()
            sender = msg.get("user") or msg.get("bot_id") or "unknown"
            out.append(Artifact(
                source="slack",
                artifact_type="message",
                external_id=f"{channel_id}:{ts}",
                title=text.split("\n", 1)[0][:200],
                body=text,
                author=f"slack:{sender}",
                url=f"https://slack.com/archives/{channel_id}/p{ts.replace('.', '')}",
                tags=[f"channel:{channel_id}"],
                metadata={"channel_id": channel_id, "ts": ts, "thread_ts": msg.get("thread_ts")},
                occurred_at=occurred,
            ))
    return out


def verify_slack_signature(body: bytes, ts: str, sig: str, secret: str = "") -> bool:
    """Slack v0 signing: https://api.slack.com/authentication/verifying-requests-from-slack"""
    secret = (secret or SLACK_SIGNING_SECRET).strip()
    if not secret or not ts or not sig:
        return False
    try:
        ts_int = int(ts)
    except ValueError:
        return False
    if abs(int(time.time()) - ts_int) > 5 * 60:
        return False
    base = f"v0:{ts}:".encode() + bytes(body)
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


# ── GitHub connector ──────────────────────────────────────────────────────────

def github_configured() -> bool:
    return bool(GITHUB_TOKEN) and bool(GITHUB_REPOS)


def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_github(per_repo_limit: int = 25) -> list[Artifact]:
    if not github_configured():
        return []
    out: list[Artifact] = []
    for repo in GITHUB_REPOS:
        if "/" not in repo:
            continue
        # Pull recent PRs (open + closed, sorted by updated)
        try:
            prs = _http_get(
                f"https://api.github.com/repos/{repo}/pulls",
                _gh_headers(),
                {"state": "all", "per_page": per_repo_limit, "sort": "updated", "direction": "desc"},
            )
        except Exception as exc:
            log.warning("github PR fetch failed for %s: %s", repo, exc)
            prs = []
        for pr in prs if isinstance(prs, list) else []:
            body = (pr.get("body") or "").strip()
            tags = ["pr", "merged" if pr.get("merged_at") else pr.get("state", "open")]
            for lbl in (pr.get("labels") or []):
                name = (lbl.get("name") if isinstance(lbl, dict) else str(lbl)).strip()
                if name:
                    tags.append(f"label:{name}")
            occurred = pr.get("updated_at") or pr.get("created_at") or datetime.now(timezone.utc).isoformat()
            out.append(Artifact(
                source="github",
                artifact_type="pr",
                external_id=f"{repo}#pr-{pr.get('number')}",
                title=(pr.get("title") or "")[:300],
                body=body[:5000] or (pr.get("title") or ""),
                author=(pr.get("user") or {}).get("login", "")[:200],
                url=pr.get("html_url", ""),
                tags=tags,
                metadata={
                    "repo": repo,
                    "number": pr.get("number"),
                    "state": pr.get("state"),
                    "merged_at": pr.get("merged_at"),
                    "draft": pr.get("draft"),
                    "additions": pr.get("additions"),
                    "deletions": pr.get("deletions"),
                },
                occurred_at=occurred,
            ))
        # Pull recent issues (excluding PRs)
        try:
            issues = _http_get(
                f"https://api.github.com/repos/{repo}/issues",
                _gh_headers(),
                {"state": "all", "per_page": per_repo_limit, "sort": "updated", "direction": "desc"},
            )
        except Exception as exc:
            log.warning("github issue fetch failed for %s: %s", repo, exc)
            issues = []
        for it in issues if isinstance(issues, list) else []:
            if it.get("pull_request"):
                continue
            body = (it.get("body") or "").strip()
            tags = ["issue", it.get("state", "open")]
            for lbl in (it.get("labels") or []):
                name = (lbl.get("name") if isinstance(lbl, dict) else str(lbl)).strip()
                if name:
                    tags.append(f"label:{name}")
            occurred = it.get("updated_at") or it.get("created_at") or datetime.now(timezone.utc).isoformat()
            out.append(Artifact(
                source="github",
                artifact_type="issue",
                external_id=f"{repo}#issue-{it.get('number')}",
                title=(it.get("title") or "")[:300],
                body=body[:4000] or (it.get("title") or ""),
                author=(it.get("user") or {}).get("login", "")[:200],
                url=it.get("html_url", ""),
                tags=tags,
                metadata={"repo": repo, "number": it.get("number"), "state": it.get("state")},
                occurred_at=occurred,
            ))
    return out


def verify_github_signature(body: bytes, sig_header: str, secret: str = "") -> bool:
    """GitHub: X-Hub-Signature-256 header, value 'sha256=<hex>', HMAC-SHA-256."""
    secret = (secret or GITHUB_WEBHOOK_SECRET).strip()
    if not secret or not sig_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), bytes(body), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header)


# ── Linear connector ──────────────────────────────────────────────────────────

LINEAR_GQL = """
query RecentIssues($first: Int!) {
  issues(first: $first, orderBy: updatedAt) {
    nodes {
      id identifier title description url priority state { name type }
      assignee { name email }
      team { key name }
      labels { nodes { name } }
      createdAt updatedAt completedAt
    }
  }
}
"""


def linear_configured() -> bool:
    return bool(LINEAR_API_KEY)


def fetch_linear(limit: int = 50) -> list[Artifact]:
    if not linear_configured():
        return []
    headers = {
        "Authorization": LINEAR_API_KEY,  # Linear accepts raw API keys (no Bearer prefix)
        "Content-Type": "application/json",
    }
    try:
        data = _http_post(
            "https://api.linear.app/graphql",
            headers,
            {"query": LINEAR_GQL, "variables": {"first": limit}},
        )
    except Exception as exc:
        log.warning("linear fetch failed: %s", exc)
        return []
    nodes = (((data or {}).get("data") or {}).get("issues") or {}).get("nodes") or []
    out: list[Artifact] = []
    for it in nodes:
        body = (it.get("description") or "").strip() or (it.get("title") or "")
        labels = [l.get("name") for l in ((it.get("labels") or {}).get("nodes") or []) if l.get("name")]
        tags = ["linear-issue"]
        if it.get("state"):
            tags.append(f"state:{it['state'].get('name','').lower()}")
            tags.append(f"state-type:{it['state'].get('type','').lower()}")
        for l in labels:
            tags.append(f"label:{l}")
        occurred = it.get("updatedAt") or it.get("createdAt") or datetime.now(timezone.utc).isoformat()
        out.append(Artifact(
            source="linear",
            artifact_type="issue",
            external_id=it.get("id") or it.get("identifier") or "",
            title=(it.get("identifier", "") + " " + (it.get("title") or "")).strip()[:300],
            body=body[:5000],
            author=((it.get("assignee") or {}).get("name") or "")[:200],
            url=it.get("url", ""),
            tags=tags,
            metadata={
                "identifier": it.get("identifier"),
                "priority": it.get("priority"),
                "state_name": (it.get("state") or {}).get("name"),
                "state_type": (it.get("state") or {}).get("type"),
                "team": (it.get("team") or {}).get("key"),
                "completed_at": it.get("completedAt"),
            },
            occurred_at=occurred,
        ))
    return out


def verify_linear_signature(body: bytes, sig_header: str, secret: str = "") -> bool:
    """Linear webhook: linear-signature header, raw HMAC-SHA-256 hex."""
    secret = (secret or LINEAR_WEBHOOK_SECRET).strip()
    if not secret or not sig_header:
        return False
    expected = hmac.new(secret.encode(), bytes(body), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header.strip())


# ── QuickBooks connector ──────────────────────────────────────────────────────

def quickbooks_configured() -> bool:
    return bool(QUICKBOOKS_ACCESS_TOKEN) and bool(QUICKBOOKS_REALM_ID)


def fetch_quickbooks(limit: int = 25) -> list[Artifact]:
    if not quickbooks_configured():
        return []
    headers = {
        "Authorization": f"Bearer {QUICKBOOKS_ACCESS_TOKEN}",
        "Accept": "application/json",
    }
    url = f"{QUICKBOOKS_BASE_URL}/v3/company/{QUICKBOOKS_REALM_ID}/query"
    out: list[Artifact] = []
    for entity, sql in (
        ("Invoice",  f"SELECT * FROM Invoice ORDER BY MetaData.LastUpdatedTime DESC MAXRESULTS {limit}"),
        ("Customer", f"SELECT * FROM Customer ORDER BY MetaData.LastUpdatedTime DESC MAXRESULTS {limit}"),
    ):
        try:
            data = _http_get(url, headers, {"query": sql})
        except Exception as exc:
            log.warning("quickbooks fetch failed for %s: %s", entity, exc)
            continue
        rows = ((data or {}).get("QueryResponse") or {}).get(entity) or []
        for row in rows:
            qb_id = str(row.get("Id") or row.get("DocNumber") or "")
            if not qb_id:
                continue
            title = f"{entity} {row.get('DocNumber', qb_id)}"
            body_lines: list[str] = []
            if entity == "Invoice":
                amt = row.get("TotalAmt")
                bal = row.get("Balance")
                cust = (row.get("CustomerRef") or {}).get("name") or ""
                body_lines.append(f"Customer: {cust}")
                body_lines.append(f"Total: {amt}  Balance: {bal}")
                if row.get("DueDate"):
                    body_lines.append(f"Due: {row['DueDate']}")
            else:
                body_lines.append(f"DisplayName: {row.get('DisplayName','')}")
                body_lines.append(f"PrimaryEmail: {((row.get('PrimaryEmailAddr') or {}).get('Address',''))}")
                body_lines.append(f"Active: {row.get('Active', True)}")
            occurred = ((row.get("MetaData") or {}).get("LastUpdatedTime")) or datetime.now(timezone.utc).isoformat()
            out.append(Artifact(
                source="quickbooks",
                artifact_type=entity.lower(),
                external_id=f"{entity.lower()}:{qb_id}",
                title=title[:300],
                body="\n".join(body_lines)[:5000],
                author="quickbooks",
                url="",
                tags=[entity.lower()],
                metadata={"raw": {k: row.get(k) for k in ("Id","DocNumber","TotalAmt","Balance","DueDate","DisplayName","Active")}},
                occurred_at=occurred,
            ))
    return out


# ── Notion connector (stub: status-only for now) ─────────────────────────────

def notion_configured() -> bool:
    return bool(NOTION_API_KEY)


def fetch_notion(limit: int = 20) -> list[Artifact]:
    """Minimal: search recent pages and ingest title + summary excerpt."""
    if not notion_configured():
        return []
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    try:
        data = _http_post(
            "https://api.notion.com/v1/search",
            headers,
            {"page_size": limit, "sort": {"direction": "descending", "timestamp": "last_edited_time"}},
        )
    except Exception as exc:
        log.warning("notion fetch failed: %s", exc)
        return []
    out: list[Artifact] = []
    for page in (data or {}).get("results", []):
        title = ""
        props = (page.get("properties") or {})
        for v in props.values():
            if isinstance(v, dict) and v.get("type") == "title":
                segs = v.get("title") or []
                title = "".join(s.get("plain_text", "") for s in segs)
                break
        url = page.get("url", "")
        page_id = page.get("id", "")
        if not page_id:
            continue
        out.append(Artifact(
            source="notion",
            artifact_type="doc",
            external_id=page_id,
            title=(title or url or page_id)[:300],
            body=(title or "")[:5000],
            author=((page.get("created_by") or {}).get("id") or "")[:200],
            url=url,
            tags=["notion-page"],
            metadata={"last_edited_time": page.get("last_edited_time")},
            occurred_at=page.get("last_edited_time") or datetime.now(timezone.utc).isoformat(),
        ))
    return out


# ── Demo seeders ──────────────────────────────────────────────────────────────

def _now_iso(days_ago: float = 0.0, hours_ago: float = 0.0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours_ago)
    return dt.isoformat()


# A coherent story: revenue churn cluster on $99 tier <-> bug spike around
# checkout flow <-> recent PRs touching checkout <-> a #customers Slack thread
# with no founder reply for >24h. Designed to fire 4 closed-loop rules.
DEMO_ARTIFACTS: list[dict] = [
    # SLACK · customers channel (no reply >24h)
    {"source":"slack","artifact_type":"message","external_id":"C-CUST:1742839200.001","title":"Checkout broken on Starter plan","body":"Hey team, our customer @acme is blocking on checkout. They get a 'card_declined' but Stripe shows the charge succeeded. Has been failing since Tuesday. They're threatening to churn. Anyone seen this?","author":"slack:U01CUST_AM","url":"#","tags":["channel:C-CUST","customer:acme"],"days_ago":1.4,"meta":{"channel_id":"C-CUST","reply_count":0}},
    {"source":"slack","artifact_type":"message","external_id":"C-CUST:1742889200.002","title":"3 enterprise customers report slow API","body":"Heads up - tickets piling up about API latency. Customers on Growth plan reporting >2s response times. Anyone monitoring infra?","author":"slack:U02CUST_AM","url":"#","tags":["channel:C-CUST"],"days_ago":1.1,"meta":{"channel_id":"C-CUST","reply_count":0}},
    {"source":"slack","artifact_type":"message","external_id":"C-CUST:1742939200.003","title":"acme followed up - still broken","body":"Acme just emailed again. They're moving to a competitor by EOW unless we fix the Starter checkout. This is the 3rd time I'm pinging here.","author":"slack:U01CUST_AM","url":"#","tags":["channel:C-CUST","customer:acme"],"days_ago":0.4,"meta":{"channel_id":"C-CUST","reply_count":0}},
    # SLACK · engineering channel
    {"source":"slack","artifact_type":"message","external_id":"C-ENG:1742839200.004","title":"Anyone own checkout code path?","body":"There's been weird behavior in the Starter checkout since the Tuesday deploy. I see a bunch of `payment_intent` race conditions in the logs. Maya - wasn't this in your PR?","author":"slack:U03ENG_BO","url":"#","tags":["channel:C-ENG"],"days_ago":2.2,"meta":{"channel_id":"C-ENG","reply_count":3}},
    {"source":"slack","artifact_type":"message","external_id":"C-ENG:1742871200.005","title":"Re: checkout - investigating","body":"Looking into it. I think it's the Stripe webhook idempotency change in #2847. Will revert if confirmed.","author":"slack:U04ENG_MP","url":"#","tags":["channel:C-ENG"],"days_ago":2.0,"meta":{"channel_id":"C-ENG","thread_ts":"1742839200.004","reply_count":1}},
    {"source":"slack","artifact_type":"message","external_id":"C-ENG:1743039200.006","title":"PR review queue is 14 deep","body":"FYI review queue is 14 PRs deep, oldest is 5 days. We're falling behind on Linear stuff. Need to triage.","author":"slack:U05ENG_RK","url":"#","tags":["channel:C-ENG"],"days_ago":0.6,"meta":{"channel_id":"C-ENG","reply_count":2}},
    # SLACK · leadership
    {"source":"slack","artifact_type":"message","external_id":"C-LEAD:1742939200.007","title":"Board meeting talking points","body":"Reminder: I need slides for Tuesday's board on (1) ARR trajectory, (2) churn cohort breakdown, (3) eng velocity. Send drafts by Monday EOD.","author":"slack:U06LEAD_TY","url":"#","tags":["channel:C-LEAD"],"days_ago":0.8,"meta":{"channel_id":"C-LEAD","reply_count":1}},
    {"source":"slack","artifact_type":"message","external_id":"C-LEAD:1743099200.008","title":"Series A timing","body":"Conviction asked about timing again. I think we have 6 weeks before we need to decide. Need cleaner NRR numbers first.","author":"slack:U06LEAD_TY","url":"#","tags":["channel:C-LEAD"],"days_ago":0.2,"meta":{"channel_id":"C-LEAD","reply_count":0}},

    # GITHUB · fourseat/api
    {"source":"github","artifact_type":"pr","external_id":"fourseat/api#pr-2847","title":"Stripe webhook idempotency - dedupe by event id","body":"Fixes duplicate charge processing when Stripe retries webhooks. Adds an idempotency key check against `processed_events` table. \n\nNo Linear ticket - small fix discovered while debugging customer report. Should be safe.","author":"maya.patel","url":"https://github.com/fourseat/api/pull/2847","tags":["pr","merged","label:bug","label:checkout"],"days_ago":3.0,"meta":{"repo":"fourseat/api","number":2847,"state":"closed","merged_at":True}},
    {"source":"github","artifact_type":"pr","external_id":"fourseat/api#pr-2849","title":"Add rate limit to /v1/scan endpoint","body":"FUR-412: limits unauthenticated scan attempts to 6/min. Closes the abuse vector spotted by SecOps.","author":"raj.k","url":"https://github.com/fourseat/api/pull/2849","tags":["pr","merged","label:security"],"days_ago":2.0,"meta":{"repo":"fourseat/api","number":2849,"state":"closed","merged_at":True}},
    {"source":"github","artifact_type":"pr","external_id":"fourseat/api#pr-2853","title":"Refactor billing module","body":"Refactor of billing.py - extracts checkout flow into its own module. No ticket; thought I'd clean this up while I was in there. Touches some checkout code paths.","author":"maya.patel","url":"https://github.com/fourseat/api/pull/2853","tags":["pr","open","label:refactor","label:checkout"],"days_ago":1.0,"meta":{"repo":"fourseat/api","number":2853,"state":"open","merged_at":None,"draft":False}},
    {"source":"github","artifact_type":"pr","external_id":"fourseat/api#pr-2855","title":"FUR-401: oracle endpoints","body":"Implements the oracle scan endpoints per the linear spec. Fixes the early 503 bug on missing webhook secret.","author":"raj.k","url":"https://github.com/fourseat/api/pull/2855","tags":["pr","open","label:feature"],"days_ago":0.3,"meta":{"repo":"fourseat/api","number":2855,"state":"open"}},
    {"source":"github","artifact_type":"issue","external_id":"fourseat/api#issue-512","title":"Starter plan: card_declined despite Stripe success","body":"Multiple customers (acme, sundial, foursquare) report card_declined banner even though Stripe shows the charge succeeded. Reproduces on Starter plan only. Investigating.","author":"maya.patel","url":"https://github.com/fourseat/api/issues/512","tags":["issue","open","label:bug","label:checkout","label:p0"],"days_ago":1.5,"meta":{"repo":"fourseat/api","number":512,"state":"open"}},

    # LINEAR
    {"source":"linear","artifact_type":"issue","external_id":"FUR-401","title":"FUR-401 Build Oracle endpoints + dashboard","body":"Implement /api/oracle/scan and the verdict UI. Spec attached.","author":"raj.k","url":"https://linear.app/fourseat/issue/FUR-401","tags":["linear-issue","state:in progress","state-type:started","label:engineering","label:oracle"],"days_ago":0.5,"meta":{"identifier":"FUR-401","priority":1,"state_name":"In Progress","state_type":"started","team":"FUR"}},
    {"source":"linear","artifact_type":"issue","external_id":"FUR-410","title":"FUR-410 Checkout: card_declined on successful charges","body":"Customers on Starter plan see card_declined despite Stripe charging successfully. P0. Reported by acme, sundial, foursquare. Suspect the idempotency change in #2847.","author":"maya.patel","url":"https://linear.app/fourseat/issue/FUR-410","tags":["linear-issue","state:todo","state-type:unstarted","label:bug","label:p0","label:checkout"],"days_ago":0.4,"meta":{"identifier":"FUR-410","priority":0,"state_name":"Todo","state_type":"unstarted","team":"FUR"}},
    {"source":"linear","artifact_type":"issue","external_id":"FUR-411","title":"FUR-411 Investigate API latency reports","body":"Multiple Growth customers reporting >2s response on /v1/scan. Need APM trace and cohort analysis.","author":"raj.k","url":"https://linear.app/fourseat/issue/FUR-411","tags":["linear-issue","state:todo","state-type:unstarted","label:bug","label:performance"],"days_ago":1.1,"meta":{"identifier":"FUR-411","priority":1,"state_name":"Todo","state_type":"unstarted","team":"FUR"}},
    {"source":"linear","artifact_type":"issue","external_id":"FUR-412","title":"FUR-412 Rate limit /v1/scan","body":"Add rate limiting per token to /v1/scan to prevent abuse. Spec: 6/min for unauthenticated, 60/min authenticated.","author":"raj.k","url":"https://linear.app/fourseat/issue/FUR-412","tags":["linear-issue","state:done","state-type:completed","label:security"],"days_ago":2.0,"meta":{"identifier":"FUR-412","priority":2,"state_name":"Done","state_type":"completed","team":"FUR"}},
    {"source":"linear","artifact_type":"issue","external_id":"FUR-415","title":"FUR-415 Migrate billing to subscription pricing v3","body":"Major project. Spec doc in Notion (#fourseat/billing-v3-spec). Blocked on legal review.","author":"raj.k","url":"https://linear.app/fourseat/issue/FUR-415","tags":["linear-issue","state:blocked","state-type:unstarted","label:billing"],"days_ago":3.0,"meta":{"identifier":"FUR-415","priority":1,"state_name":"Blocked","state_type":"unstarted","team":"FUR"}},
    {"source":"linear","artifact_type":"issue","external_id":"FUR-417","title":"FUR-417 Acme onboarding follow-up","body":"Customer success: Acme is still on the migration path. They blocked on the checkout bug. Need engineering to pair.","author":"sales.cs","url":"https://linear.app/fourseat/issue/FUR-417","tags":["linear-issue","state:todo","state-type:unstarted","label:customer-success"],"days_ago":0.3,"meta":{"identifier":"FUR-417","priority":1,"state_name":"Todo","state_type":"unstarted","team":"CS"}},
    {"source":"linear","artifact_type":"issue","external_id":"FUR-418","title":"FUR-418 Reduce Starter tier churn","body":"Starter tier subs down 36% over 30 days. Need a project owner. Customer interviews needed.","author":"sales.cs","url":"https://linear.app/fourseat/issue/FUR-418","tags":["linear-issue","state:todo","state-type:unstarted","label:retention","label:starter-tier"],"days_ago":0.6,"meta":{"identifier":"FUR-418","priority":0,"state_name":"Todo","state_type":"unstarted","team":"GTM"}},
    {"source":"linear","artifact_type":"issue","external_id":"FUR-420","title":"FUR-420 Update docs site - new connector list","body":"Docs site still says 'Slack and Gmail' under integrations. Update to current connector matrix.","author":"raj.k","url":"https://linear.app/fourseat/issue/FUR-420","tags":["linear-issue","state:todo","state-type:unstarted","label:docs"],"days_ago":1.4,"meta":{"identifier":"FUR-420","priority":3,"state_name":"Todo","state_type":"unstarted","team":"FUR"}},

    # NOTION (stub-style docs)
    {"source":"notion","artifact_type":"doc","external_id":"page-billing-v3-spec","title":"Billing v3 Pricing Migration · spec","body":"Owner: Raj. Status: draft. Last edited 31 days ago. Outstanding: Stripe Tax integration story; backfill plan for Studio tier.","author":"raj.k","url":"https://notion.so/fourseat/billing-v3-spec","tags":["notion-page","spec"],"days_ago":31.0,"meta":{"last_edited_time":"31d ago"}},
    {"source":"notion","artifact_type":"doc","external_id":"page-q3-okrs","title":"Q3 OKRs","body":"O1: Reach $400k MRR. KR1: 30 net new logos. KR2: Reduce Starter churn by 30%. KR3: Ship Oracle live verdicts to 5 paying customers.","author":"tyler","url":"https://notion.so/fourseat/q3-okrs","tags":["notion-page","okr"],"days_ago":12.0,"meta":{}},
    {"source":"notion","artifact_type":"doc","external_id":"page-runbook-checkout","title":"Runbook · Checkout incident","body":"Step 1: revert offending webhook PR. Step 2: replay queued events from Stripe. Step 3: notify affected customers. Owner: Maya.","author":"maya.patel","url":"https://notion.so/fourseat/runbook-checkout","tags":["notion-page","runbook"],"days_ago":2.0,"meta":{}},

    # QUICKBOOKS (just a couple of demo rows)
    {"source":"quickbooks","artifact_type":"invoice","external_id":"invoice:1042","title":"Invoice 1042","body":"Customer: Acme Corp\nTotal: 12000\nBalance: 12000\nDue: 14d overdue","author":"quickbooks","url":"","tags":["invoice","overdue"],"days_ago":17.0,"meta":{"raw":{"Id":"1042","TotalAmt":12000,"Balance":12000,"DueDate":"overdue"}}},
    {"source":"quickbooks","artifact_type":"invoice","external_id":"invoice:1051","title":"Invoice 1051","body":"Customer: Sundial\nTotal: 4500\nBalance: 0","author":"quickbooks","url":"","tags":["invoice","paid"],"days_ago":3.0,"meta":{"raw":{"Id":"1051","TotalAmt":4500,"Balance":0}}},
]


def seed_demo_artifacts(reset: bool = True) -> list[Artifact]:
    init_db()
    if reset:
        with _connect() as conn:
            conn.execute("DELETE FROM artifacts")
            # Contentless FTS5 tables don't support DELETE FROM directly;
            # the 'delete-all' command is the documented way to clear them.
            try:
                conn.execute("INSERT INTO artifacts_fts(artifacts_fts) VALUES('delete-all')")
            except Exception:
                # Some SQLite builds emit this differently; rebuild as a safety net.
                conn.execute("INSERT INTO artifacts_fts(artifacts_fts) VALUES('rebuild')")
    arts: list[Artifact] = []
    for spec in DEMO_ARTIFACTS:
        meta = spec.get("meta") or {}
        # Translate boolean merged_at hint into a real timestamp.
        if meta.get("merged_at") is True:
            meta["merged_at"] = _now_iso(days_ago=spec.get("days_ago", 0))
        arts.append(Artifact(
            source=spec["source"],
            artifact_type=spec["artifact_type"],
            external_id=spec["external_id"],
            title=spec["title"],
            body=spec["body"],
            author=spec.get("author", ""),
            url=spec.get("url", ""),
            tags=list(spec.get("tags", [])),
            metadata=meta,
            occurred_at=_now_iso(days_ago=spec.get("days_ago", 0), hours_ago=spec.get("hours_ago", 0)),
        ))
    upsert_artifacts(arts)
    return arts


# ── Closed-loop signal detection (cross-source rules) ─────────────────────────

def _select_artifacts(where: str = "", params: tuple = (), limit: int = 200) -> list[sqlite3.Row]:
    init_db()
    sql = "SELECT * FROM artifacts"
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY occurred_at DESC LIMIT ?"
    with _connect() as conn:
        rows = conn.execute(sql, params + (limit,)).fetchall()
    return list(rows)


def _is_in_window(occurred_iso: str, days: float) -> bool:
    try:
        dt = datetime.fromisoformat(occurred_iso.replace("Z", "+00:00"))
    except Exception:
        return False
    return (datetime.now(timezone.utc) - dt) <= timedelta(days=days)


def _has_label(tags_json: str, prefix: str) -> bool:
    try:
        tags = json.loads(tags_json or "[]")
    except Exception:
        tags = []
    return any(isinstance(t, str) and t == prefix for t in tags) or any(
        isinstance(t, str) and t.startswith(prefix) for t in tags
    )


def _tags(tags_json: str) -> list[str]:
    try:
        return list(json.loads(tags_json or "[]"))
    except Exception:
        return []


def detect_closed_loop_signals() -> list[ClosedLoopSignal]:
    """Cross-source rules. Each one collects involved artifact ids so the
    verdict can cite the underlying evidence."""
    rows = _select_artifacts(limit=400)
    by_source: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_source.setdefault(r["source"], []).append(r)

    out: list[ClosedLoopSignal] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1) ENG_CAPACITY_GAP
    linear_open = [r for r in by_source.get("linear", []) if "state-type:unstarted" in _tags(r["tags_json"]) or "state:todo" in _tags(r["tags_json"])]
    gh_merged_7d = [r for r in by_source.get("github", []) if r["artifact_type"] == "pr" and "merged" in _tags(r["tags_json"]) and _is_in_window(r["occurred_at"], 7)]
    if len(linear_open) >= 4 and len(linear_open) >= 1.5 * max(1, len(gh_merged_7d)):
        out.append(ClosedLoopSignal(
            rule="eng_capacity_gap",
            priority="P1",
            headline=f"{len(linear_open)} open Linear issues vs {len(gh_merged_7d)} PRs merged in 7d",
            evidence={"open_linear": len(linear_open), "merged_prs_7d": len(gh_merged_7d)},
            involved_artifact_ids=[int(r["id"]) for r in (linear_open[:5] + gh_merged_7d[:3])],
            detected_at=now_iso,
        ))

    # 2) SPEC_DRIFT - PR with no Linear identifier reference in title or body
    linear_idents = {(r["title"].split(" ", 1)[0] or "").upper() for r in by_source.get("linear", []) if r["title"]}
    linear_idents = {x for x in linear_idents if re.match(r"^[A-Z]{2,5}-\d+$", x)}
    drifted: list[sqlite3.Row] = []
    for r in by_source.get("github", []):
        if r["artifact_type"] != "pr" or "open" not in _tags(r["tags_json"]):
            continue
        text = (r["title"] + " " + (r["body"] or "")).upper()
        if not any(ident in text for ident in linear_idents):
            drifted.append(r)
    if drifted:
        out.append(ClosedLoopSignal(
            rule="spec_drift",
            priority="P2",
            headline=f"{len(drifted)} open PR{'s' if len(drifted)>1 else ''} with no linked Linear ticket",
            evidence={"drifted_prs": [r["title"] for r in drifted[:5]]},
            involved_artifact_ids=[int(r["id"]) for r in drifted[:5]],
            detected_at=now_iso,
        ))

    # 3) QUIET_CUSTOMER - Slack message in customer channel with no reply over 24h
    quiet: list[sqlite3.Row] = []
    for r in by_source.get("slack", []):
        tags = _tags(r["tags_json"])
        if not any(t.startswith("channel:C-CUST") for t in tags):
            continue
        try:
            meta = json.loads(r["metadata_json"] or "{}")
        except Exception:
            meta = {}
        if int(meta.get("reply_count") or 0) == 0 and _is_in_window(r["occurred_at"], 5) and not _is_in_window(r["occurred_at"], 1):
            quiet.append(r)
    if quiet:
        out.append(ClosedLoopSignal(
            rule="quiet_customer",
            priority="P0" if len(quiet) >= 2 else "P1",
            headline=f"{len(quiet)} customer Slack thread{'s' if len(quiet)>1 else ''} with no reply over 24h",
            evidence={"threads": [r["title"] for r in quiet[:4]]},
            involved_artifact_ids=[int(r["id"]) for r in quiet[:5]],
            detected_at=now_iso,
        ))

    # 4) FEATURE_DECAY - Linear bug ticket about a feature + GitHub issue/PR touching same feature in last 14d
    feature_bugs: list[sqlite3.Row] = []
    for r in by_source.get("linear", []):
        tags = _tags(r["tags_json"])
        if not any(t in tags for t in ("label:bug", "label:p0")):
            continue
        if not _is_in_window(r["occurred_at"], 14):
            continue
        keywords = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", r["title"]) if w.lower() not in {"with","that","from","this","need","customers","report","still"}]
        for gh in by_source.get("github", []):
            if not _is_in_window(gh["occurred_at"], 14):
                continue
            text = (gh["title"] + " " + (gh["body"] or "")).lower()
            if sum(1 for k in keywords if k in text) >= 2:
                feature_bugs.append(r)
                feature_bugs.append(gh)
                break
    if feature_bugs:
        unique_ids = list(dict.fromkeys(int(r["id"]) for r in feature_bugs))
        out.append(ClosedLoopSignal(
            rule="feature_decay",
            priority="P0",
            headline="Bug ticket and recent code changes overlap on the same feature - likely regression",
            evidence={"correlated_artifacts": len(unique_ids)},
            involved_artifact_ids=unique_ids[:6],
            detected_at=now_iso,
        ))

    # 5) STALE_SPEC - Notion doc tagged 'spec' last edited >21d, referenced by recent PRs/issues
    stale: list[sqlite3.Row] = []
    for r in by_source.get("notion", []):
        if "spec" not in _tags(r["tags_json"]):
            continue
        if _is_in_window(r["occurred_at"], 21):
            continue
        # Check if any PR title mentions this spec keyword
        title_words = [w.lower() for w in re.findall(r"[A-Za-z]{5,}", r["title"]) if w.lower() not in {"draft","status","spec","page"}]
        for gh in by_source.get("github", []):
            text = (gh["title"] + " " + (gh["body"] or "")).lower()
            if sum(1 for k in title_words if k in text) >= 1:
                stale.append(r)
                break
    if stale:
        out.append(ClosedLoopSignal(
            rule="stale_spec",
            priority="P2",
            headline=f"{len(stale)} spec doc{'s' if len(stale)>1 else ''} stale over 21d but actively referenced",
            evidence={"specs": [r["title"] for r in stale[:5]]},
            involved_artifact_ids=[int(r["id"]) for r in stale[:5]],
            detected_at=now_iso,
        ))

    return out


# ── Verdict synthesis (4-advisor debate) ─────────────────────────────────────

VERDICT_INSTRUCTIONS = """You are the FOURSEAT BRAIN verdict engine.

You receive a cross-source closed-loop signal (rule, evidence, involved artifacts)
plus a transcript of a 4-advisor Boardroom debate.

Compress this into ONE machine-readable verdict. Be specific, no em dashes.

Output ONLY valid JSON with this shape:
{
  "one_liner":       "max 26 words. The single sentence the founder must read.",
  "strategy_view":   "max 35 words, CSO angle.",
  "finance_view":    "max 35 words, CFO angle, prefer numbers.",
  "tech_view":       "max 35 words, CTO angle.",
  "contrarian_view": "max 35 words, contrarian stress-test.",
  "actions":         ["action 1","action 2","action 3"],
  "watch_metrics":   ["metric to watch","metric to watch"],
  "confidence":      "High | Medium | Low"
}
Return ONLY the JSON.
"""


_FALLBACK_PANELS = {
    "eng_capacity_gap": {
        "Strategy":   "Capacity gap means engineering is shipping reactive work, not the roadmap. Re-prioritize before the gap eats the next quarter.",
        "Finance":    "If two engineers fall behind for four weeks, you've lost about $30k in burn for zero net progress. Cap WIP today.",
        "Technology": "Apply a ruthless WIP limit. Every new ticket needs a closed one. Cancel anything that hasn't moved in 14 days.",
        "Contrarian": "Maybe you don't have a capacity gap. You have a tickets-as-noise problem. Delete half the backlog and watch nothing break.",
    },
    "spec_drift": {
        "Strategy":   "Untracked PRs become tribal knowledge. The customer-facing surface area drifts away from what the team thinks it ships.",
        "Finance":    "Refactor PRs without specs are how you hide six weeks of unfunded work. Quantify what's in flight before next forecast.",
        "Technology": "Block merges from PRs without a Linear ticket reference in description. Two-line CI rule, fixed today.",
        "Contrarian": "Spec drift is sometimes signal that the spec is wrong. Ask the engineer what they shipped before forcing the ticket.",
    },
    "quiet_customer": {
        "Strategy":   "Customer silence is not patience, it is exit. A churned-but-still-paying customer is the most expensive kind.",
        "Finance":    "Replace this account at current CAC and you spend 4-6x what a save costs. Act today, save tomorrow.",
        "Technology": "Wire a Slack reaction-driven SLA: any unanswered customer-channel post in 12h pages the on-call founder.",
        "Contrarian": "If you only respond when they ping three times, you have already lost the trust. Charge less or fix the root cause.",
    },
    "feature_decay": {
        "Strategy":   "Revenue-correlated bugs are the highest-leverage fix in the company. Treat them as P0 even if engineering doesn't.",
        "Finance":    "Each churned account from this bug costs roughly two months of LTV. Fix burns hours, churn burns months.",
        "Technology": "Revert the suspect commit, replay the affected events, then root-cause without time pressure.",
        "Contrarian": "Maybe the customer was always going to churn and the bug just gave them an excuse. Audit the cohort, not the code.",
    },
    "stale_spec": {
        "Strategy":   "Stale specs become political weapons. Someone will ship against the wrong version and call it strategy.",
        "Finance":    "Specs older than 21 days have a 60% rewrite rate by the time the work ships. Resync before kickoff.",
        "Technology": "Add a CI lint that fails any PR referencing a spec doc not edited in 21 days. Forces resync.",
        "Contrarian": "Specs were always stale. Engineers shipped fine without them. Ask whether the doc was load-bearing or theatre.",
    },
}


def _fallback_actions(rule: str) -> list[str]:
    return {
        "eng_capacity_gap": [
            "Cap WIP per engineer at 2 tickets in progress",
            "Delete or archive any Linear ticket untouched for 14 days",
            "Move next sprint's roadmap items to 'On deck' and freeze new arrivals",
        ],
        "spec_drift": [
            "Add CI rule requiring linear ticket reference in PR description",
            "Audit open PRs and pair each with a backfilled Linear ticket",
            "Surface untracked PRs in the weekly engineering review",
        ],
        "quiet_customer": [
            "Reply to the oldest unanswered customer thread within the hour",
            "Set a 12-hour SLA paging on customer-channel messages",
            "Schedule a 20-minute call with the customer threatening churn",
        ],
        "feature_decay": [
            "Revert the suspect commit and replay queued events",
            "Identify the affected customer cohort and notify them personally",
            "Open a postmortem ticket; root-cause within 48 hours",
        ],
        "stale_spec": [
            "Refresh the spec doc with current scope and decisions",
            "Notify any open-PR author that the spec was updated",
            "Archive specs that no longer represent the live product",
        ],
    }.get(rule, ["Triage manually with the team", "Document and revisit in 7 days"])


def _fallback_watch(rule: str) -> list[str]:
    return {
        "eng_capacity_gap": ["Open Linear ticket count weekly", "Average PR cycle time"],
        "spec_drift":       ["Percent of PRs with linked tickets", "Weekly count of untracked PRs"],
        "quiet_customer":   ["Median customer-channel response time", "Weekly count of unanswered threads >12h"],
        "feature_decay":    ["Churn rate on affected customer cohort", "Bug ticket count for the affected feature"],
        "stale_spec":       ["Specs over 21 days old", "PRs referencing stale specs"],
    }.get(rule, ["Re-scan weekly"])


def _fallback_one_liner(s: ClosedLoopSignal) -> str:
    return {
        "eng_capacity_gap": "Engineering is falling behind product demand; cap WIP and triage the backlog before the gap compounds.",
        "spec_drift":       "Untracked PRs are quietly drifting the product away from the roadmap; require a Linear ticket on every merge.",
        "quiet_customer":   "Customers are pinging without replies; treat silence as churn risk and respond today.",
        "feature_decay":    "A bug correlates with revenue churn; treat it as P0 even if the team is calling it minor.",
        "stale_spec":       "Specs older than three weeks are being shipped against; resync before more code drifts off-spec.",
    }.get(s.rule, s.headline)


_UPSTREAM_ERROR_PREFIXES = (
    "[claude unavailable","[gpt-4 unavailable","[gemini unavailable",
    "[nia.ai unavailable","[cerebras unavailable","[nvidia unavailable",
    "[summary unavailable",
)
_FREE_GIVEAWAYS = ("proceed in staged milestones","position (","key adjustment:")


def _is_upstream_error(t: str) -> bool:
    if not t: return False
    return any(t.strip().lower()[:64].startswith(p) for p in _UPSTREAM_ERROR_PREFIXES)


def _looks_like_template(t: str) -> bool:
    if not t: return True
    return any(g in (t.strip().lower()[:90]) for g in _FREE_GIVEAWAYS)


def synthesize_signal_verdict(signal: ClosedLoopSignal) -> SignalVerdict:
    from backend.debate_engine import run_debate, ask_claude

    art_rows = []
    if signal.involved_artifact_ids:
        with _connect() as conn:
            qmarks = ",".join("?" * len(signal.involved_artifact_ids))
            art_rows = conn.execute(
                f"SELECT * FROM artifacts WHERE id IN ({qmarks})",
                tuple(signal.involved_artifact_ids),
            ).fetchall()
    cited_text = "\n".join(
        f"- [{r['source']}] {r['title']}: {(r['body'] or '')[:200]}" for r in art_rows[:6]
    )

    question = (
        f"A cross-source closed-loop signal just fired in our company brain. "
        f"Should the founder treat this as urgent? What is the single best next action? "
        f"What should they watch next week?\n\n"
        f"SIGNAL RULE: {signal.rule}\n"
        f"PRIORITY (heuristic): {signal.priority}\n"
        f"HEADLINE: {signal.headline}\n"
        f"EVIDENCE: {json.dumps(signal.evidence, default=str)[:1200]}\n\n"
        f"CITED ARTIFACTS:\n{cited_text[:1800]}"
    )
    context = "Channel: company-brain (cross-source). Be crisp, no generic frameworks."

    try:
        debate = run_debate(question=question, context=context)
    except Exception as exc:
        log.warning("brain debate failed for %s: %s", signal.rule, exc)
        debate = {"chairman": {}, "round2": {}, "round1": {}}

    chairman = debate.get("chairman", {}) if isinstance(debate.get("chairman"), dict) else {}
    round2   = debate.get("round2", {})   if isinstance(debate.get("round2"), dict)   else {}

    transcript = json.dumps({
        "strategy":   round2.get("claude", ""),
        "finance":    round2.get("gpt4", ""),
        "tech":       round2.get("gemini", ""),
        "contrarian": round2.get("contrarian", ""),
        "chairman":   chairman,
    }, ensure_ascii=False)

    raw = ""
    try:
        raw = ask_claude(
            prompt=(
                f"SIGNAL: {signal.rule} priority {signal.priority}\n"
                f"Headline: {signal.headline}\n"
                f"Evidence: {json.dumps(signal.evidence, default=str)[:1200]}\n\n"
                f"DEBATE TRANSCRIPT:\n{transcript}\n\nProduce the verdict JSON now."
            ),
            system=VERDICT_INSTRUCTIONS,
        ) or ""
    except Exception as exc:
        log.warning("brain verdict synth failed: %s", exc)

    data: dict = {}
    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        if cleaned:
            data = json.loads(cleaned)
    except Exception:
        data = {}

    def _pick(k: str, default: str) -> str:
        v = data.get(k)
        return v if isinstance(v, str) and v.strip() else default

    def _resolve_view(role: str, llm_field: str, debate_field: str) -> str:
        for c in (data.get(llm_field), round2.get(debate_field)):
            t = (c or "").strip()
            if t and not _is_upstream_error(t) and not _looks_like_template(t):
                return t[:280]
        return _FALLBACK_PANELS.get(signal.rule, {}).get(role) or f"[{role} advisor view unavailable]"

    actions_raw = data.get("actions")
    actions = [str(a)[:200] for a in actions_raw if isinstance(a, str) and a.strip()] if isinstance(actions_raw, list) else []
    if not actions: actions = _fallback_actions(signal.rule)
    actions = actions[:5]

    watch_raw = data.get("watch_metrics")
    watch = [str(w)[:160] for w in watch_raw if isinstance(w, str) and w.strip()] if isinstance(watch_raw, list) else []
    if not watch: watch = _fallback_watch(signal.rule)
    watch = watch[:4]

    confidence = _pick("confidence", chairman.get("confidence", "Medium") if isinstance(chairman, dict) else "Medium")
    if confidence not in ("High", "Medium", "Low"):
        confidence = "Medium"

    chairman_verdict = chairman.get("verdict") if isinstance(chairman, dict) else ""
    default_one_liner = (
        chairman_verdict
        if chairman_verdict and not _is_upstream_error(chairman_verdict) and not _looks_like_template(chairman_verdict)
        else _fallback_one_liner(signal)
    )

    return SignalVerdict(
        rule=signal.rule,
        priority=signal.priority,
        one_liner=_pick("one_liner", default_one_liner)[:280],
        evidence=signal.evidence,
        involved_artifact_ids=signal.involved_artifact_ids,
        strategy_view=_resolve_view("Strategy",   "strategy_view",   "claude"),
        finance_view=_resolve_view("Finance",     "finance_view",    "gpt4"),
        tech_view=_resolve_view("Technology",     "tech_view",       "gemini"),
        contrarian_view=_resolve_view("Contrarian","contrarian_view","contrarian"),
        actions=actions,
        watch_metrics=watch,
        confidence=confidence,
        detected_at=signal.detected_at,
    )


def _signal_fingerprint(s: ClosedLoopSignal) -> str:
    day = s.detected_at[:10]
    return hashlib.sha256(f"brain:{s.rule}:{day}".encode()).hexdigest()[:24]


def save_signal_verdict(v: SignalVerdict) -> int:
    init_db()
    s = ClosedLoopSignal(rule=v.rule, priority=v.priority, headline="", evidence=v.evidence,
                         involved_artifact_ids=v.involved_artifact_ids, detected_at=v.detected_at)
    fp = _signal_fingerprint(s)
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO brain_signals (
                fingerprint, rule, priority, one_liner, evidence_json, involved_artifact_ids_json,
                strategy_view, finance_view, tech_view, contrarian_view,
                actions_json, watch_metrics_json, confidence, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                priority                  = excluded.priority,
                one_liner                 = excluded.one_liner,
                evidence_json             = excluded.evidence_json,
                involved_artifact_ids_json= excluded.involved_artifact_ids_json,
                strategy_view             = excluded.strategy_view,
                finance_view              = excluded.finance_view,
                tech_view                 = excluded.tech_view,
                contrarian_view           = excluded.contrarian_view,
                actions_json              = excluded.actions_json,
                watch_metrics_json        = excluded.watch_metrics_json,
                confidence                = excluded.confidence,
                detected_at               = excluded.detected_at
            """,
            (
                fp, v.rule, v.priority, v.one_liner,
                json.dumps(v.evidence, default=str),
                json.dumps(v.involved_artifact_ids),
                v.strategy_view, v.finance_view, v.tech_view, v.contrarian_view,
                json.dumps(v.actions), json.dumps(v.watch_metrics),
                v.confidence, v.detected_at,
            ),
        )
        return int(cur.lastrowid or 0)


# ── "Ask the Brain" natural-language query ───────────────────────────────────

def _fts_match(question: str) -> str:
    """Build a permissive FTS5 MATCH expression from a free-form question."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", question)]
    stop = {"what","why","how","the","and","for","with","this","that","when","over","into","from","our","their","they","does"}
    keep = [w for w in words if w.lower() not in stop]
    if not keep:
        keep = words[:6]
    return " OR ".join(f'"{w}"' for w in keep[:10])


def query_brain(question: str, *, top_k: int = 8) -> dict:
    """FTS5 retrieval + 4-advisor synthesis. Cites artifact ids."""
    init_db()
    question = (question or "").strip()
    if not question:
        return {"answer": "", "citations": [], "matched": 0}
    match = _fts_match(question)
    rows: list[sqlite3.Row] = []
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT a.* FROM artifacts a
                JOIN artifacts_fts f ON a.id = f.rowid
                WHERE artifacts_fts MATCH ?
                ORDER BY rank LIMIT ?
                """,
                (match, top_k),
            ).fetchall()
    except sqlite3.OperationalError:
        # Fallback: substring search across recent artifacts.
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE title LIKE ? OR body LIKE ? ORDER BY occurred_at DESC LIMIT ?",
                (f"%{question[:40]}%", f"%{question[:40]}%", top_k),
            ).fetchall()

    citations = [{
        "id": int(r["id"]),
        "source": r["source"],
        "type": r["artifact_type"],
        "title": r["title"],
        "url": r["url"],
        "author": r["author"],
        "occurred_at": r["occurred_at"],
    } for r in rows]

    if not citations:
        out = {"answer": "I don't have artifacts that match that question yet. Try connecting more sources or running a brain scan.", "citations": [], "matched": 0}
        _persist_query(question, out)
        return out

    blob = "\n".join(
        f"[{i+1}] ({r['source']}/{r['artifact_type']}) {r['title']}\n   {(r['body'] or '')[:380]}"
        for i, r in enumerate(rows)
    )
    sys = (
        "You are the Fourseat Company Brain. Answer the user's question grounded ONLY in the cited "
        "artifacts. Be specific, plain language, max 4 sentences. Cite supporting artifacts inline as [1], "
        "[2] etc. matching the list. If nothing relevant, say so plainly. No em dashes."
    )
    user = f"QUESTION: {question}\n\nARTIFACTS:\n{blob}"

    answer = ""
    try:
        from backend.debate_engine import ask_claude
        raw = ask_claude(user, sys) or ""
        if raw and not _is_upstream_error(raw) and not _looks_like_template(raw):
            answer = raw.strip()[:1800]
    except Exception as exc:
        log.warning("brain LLM query failed: %s", exc)

    if not answer:
        # Deterministic fallback: stitch the strongest snippets into a brief.
        bullets = []
        for i, r in enumerate(rows[:5]):
            snippet = (r["body"] or "").strip().split("\n", 1)[0][:200]
            bullets.append(f"[{i+1}] {r['source']}: {snippet}")
        answer = (
            "Based on the matched artifacts:\n" + "\n".join(bullets) +
            "\n\nThis brain is running without an LLM key, so the synthesis above is a literal stitch. "
            "Configure ANTHROPIC_API_KEY to enable a synthesized answer."
        )

    out = {"answer": answer, "citations": citations, "matched": len(rows)}
    _persist_query(question, out)
    return out


def _persist_query(question: str, payload: dict) -> None:
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO brain_queries (question, answer, cited_artifact_ids_json, asked_at) VALUES (?,?,?,?)",
                (
                    question[:1000],
                    payload.get("answer", "")[:6000],
                    json.dumps([c["id"] for c in payload.get("citations", [])]),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
    except Exception:
        pass


# ── Public read APIs (for the dashboard) ─────────────────────────────────────

def list_artifacts(limit: int = 50, *, source: str = "") -> list[dict]:
    init_db()
    where = ""
    params: tuple = ()
    if source:
        where = "WHERE source = ?"
        params = (source,)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM artifacts {where} ORDER BY occurred_at DESC LIMIT ?",
            params + (max(1, int(limit)),),
        ).fetchall()
    out = []
    for r in rows:
        try: tags = json.loads(r["tags_json"] or "[]")
        except Exception: tags = []
        out.append({
            "id": r["id"],
            "source": r["source"],
            "type": r["artifact_type"],
            "title": r["title"],
            "body": r["body"],
            "author": r["author"],
            "url": r["url"],
            "tags": tags,
            "occurred_at": r["occurred_at"],
        })
    return out


def list_signals(limit: int = 20, include_resolved: bool = False) -> list[dict]:
    init_db()
    where = "" if include_resolved else "WHERE resolved = 0"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM brain_signals {where} ORDER BY "
            "CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END, "
            "detected_at DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    out = []
    for r in rows:
        def _j(s, default):
            try: return json.loads(s or default)
            except Exception: return json.loads(default)
        out.append({
            "id": r["id"],
            "rule": r["rule"],
            "priority": r["priority"],
            "one_liner": r["one_liner"],
            "evidence": _j(r["evidence_json"], "{}"),
            "involved_artifact_ids": _j(r["involved_artifact_ids_json"], "[]"),
            "strategy_view": r["strategy_view"],
            "finance_view": r["finance_view"],
            "tech_view": r["tech_view"],
            "contrarian_view": r["contrarian_view"],
            "actions": _j(r["actions_json"], "[]"),
            "watch_metrics": _j(r["watch_metrics_json"], "[]"),
            "confidence": r["confidence"],
            "detected_at": r["detected_at"],
            "resolved": bool(r["resolved"]),
        })
    return out


def mark_signal_resolved(signal_id: int, resolved: bool = True) -> bool:
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE brain_signals SET resolved=? WHERE id=?",
            (1 if resolved else 0, int(signal_id)),
        )
        return cur.rowcount > 0


def signal_stats() -> dict:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT priority, COUNT(*) AS n FROM brain_signals WHERE resolved=0 GROUP BY priority"
        ).fetchall()
    counts = {r["priority"]: int(r["n"]) for r in rows}
    return {
        "total_open": sum(counts.values()),
        "by_priority": {p: counts.get(p, 0) for p in ("P0","P1","P2","P3")},
    }


def connector_status() -> dict[str, Any]:
    return {
        "slack":      {"configured": slack_configured(),      "channels": len(SLACK_CHANNEL_IDS)},
        "github":     {"configured": github_configured(),     "repos": len(GITHUB_REPOS)},
        "linear":     {"configured": linear_configured()},
        "quickbooks": {"configured": quickbooks_configured(), "realm": bool(QUICKBOOKS_REALM_ID)},
        "notion":     {"configured": notion_configured()},
    }


def artifact_counts() -> dict[str, int]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT source, COUNT(*) AS n FROM artifacts GROUP BY source").fetchall()
    out = {r["source"]: int(r["n"]) for r in rows}
    out["total"] = sum(out.values())
    return out


# ── Orchestrator ─────────────────────────────────────────────────────────────

def run_brain_scan(*, demo: Optional[bool] = None, force_reseed: bool = False) -> dict:
    """End-to-end: ingest live sources (or seed demo), detect closed-loop
    signals, run the 4-advisor debate, persist verdicts."""
    init_db()
    any_live = any([slack_configured(), github_configured(), linear_configured(),
                    quickbooks_configured(), notion_configured()])
    if demo is None:
        demo = not any_live

    if demo or force_reseed:
        seed_demo_artifacts(reset=True)
    else:
        try:
            for fetcher in (fetch_slack, fetch_github, fetch_linear, fetch_quickbooks, fetch_notion):
                try:
                    arts = fetcher()
                    if arts:
                        upsert_artifacts(arts)
                except Exception as exc:
                    log.warning("brain ingest %s failed: %s", fetcher.__name__, exc)
        except Exception as exc:
            log.warning("brain ingest pipeline error: %s", exc)

    signals = detect_closed_loop_signals()
    persisted: list[SignalVerdict] = []
    for s in signals:
        try:
            v = synthesize_signal_verdict(s)
        except Exception as exc:
            log.warning("brain verdict failed for %s: %s", s.rule, exc)
            v = SignalVerdict(
                rule=s.rule, priority=s.priority,
                one_liner=_fallback_one_liner(s),
                evidence=s.evidence, involved_artifact_ids=s.involved_artifact_ids,
                strategy_view=_FALLBACK_PANELS.get(s.rule, {}).get("Strategy", ""),
                finance_view=_FALLBACK_PANELS.get(s.rule, {}).get("Finance", ""),
                tech_view=_FALLBACK_PANELS.get(s.rule, {}).get("Technology", ""),
                contrarian_view=_FALLBACK_PANELS.get(s.rule, {}).get("Contrarian", ""),
                actions=_fallback_actions(s.rule),
                watch_metrics=_fallback_watch(s.rule),
                confidence="Low",
                detected_at=s.detected_at,
            )
        save_signal_verdict(v)
        persisted.append(v)

    return {
        "mode": "demo" if demo else "live",
        "connectors": connector_status(),
        "artifact_counts": artifact_counts(),
        "signals_detected": len(signals),
        "signals_persisted": len(persisted),
        "signals": list_signals(limit=20),
        "stats": signal_stats(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    out = run_brain_scan(demo=True, force_reseed=True)
    print(json.dumps({k: v for k, v in out.items() if k != "signals"}, indent=2, default=str))
    for s in out.get("signals", []):
        print(f"\n[{s['priority']}] {s['rule']}: {s['one_liner']}")
