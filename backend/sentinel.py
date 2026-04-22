"""
Fourseat - Sentinel Layer
Proactive triage for inbound communications (Gmail, Slack).

Pipeline:
    1. Fetch recent messages from Gmail (and optionally Slack).
    2. Persist raw payloads + embeddings into Fourseat Memory (ChromaDB).
    3. Cross-reference Memory for "Blind Spots" (prior commitments, contradictions).
    4. Route each message through the Boardroom (4 advisor lenses) via run_debate().
    5. Store a structured Verdict in the `triage` table.
    6. Render a Daily Decision Briefing as Markdown.

Plugs into existing modules:
    - backend.board_mind.collection      -> vector memory (ChromaDB)
    - backend.board_mind.query_memory    -> blind-spot retrieval
    - backend.debate_engine.run_debate   -> Boardroom panel
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from dotenv import load_dotenv

from backend.debate_engine import run_debate

load_dotenv()

log = logging.getLogger("fourseat.sentinel")

# ── Paths & config ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = Path("/tmp/fourseat-data") if os.getenv("VERCEL") else (BASE_DIR / "data")
DATA_DIR = Path(os.getenv("FOURSEAT_DATA_DIR", str(DEFAULT_DATA_DIR)))
SENTINEL_DIR = DATA_DIR / "sentinel"
SENTINEL_DIR.mkdir(parents=True, exist_ok=True)

DB_URL = os.getenv("SENTINEL_DB_URL", f"sqlite:///{SENTINEL_DIR / 'sentinel.db'}")
GMAIL_TOKEN_PATH = Path(os.getenv("GMAIL_TOKEN_PATH", str(SENTINEL_DIR / "gmail_token.json")))
GMAIL_CREDS_PATH = Path(os.getenv("GMAIL_CREDS_PATH", str(SENTINEL_DIR / "gmail_credentials.json")))
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Message:
    source: str           # "gmail" | "slack"
    external_id: str      # provider message id (idempotency key)
    sender: str
    subject: str
    body: str
    received_at: str      # ISO-8601

    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.source}:{self.external_id}".encode()).hexdigest()[:16]


@dataclass
class Verdict:
    priority: str         # "P0" | "P1" | "P2" | "P3"
    category: str         # "Strategy" | "Finance" | "Tech" | "Ops" | "Noise"
    action: str           # "Reply Now" | "Delegate" | "Schedule" | "Archive"
    one_liner: str
    strategy_view: str
    finance_view: str
    tech_view: str
    contrarian_view: str
    blind_spots: list[str]
    confidence: str       # "High" | "Medium" | "Low"
    reasoning: str


# ── Storage (SQLite first, Postgres-compatible schema) ────────────────────────

def _connect() -> sqlite3.Connection:
    if not DB_URL.startswith("sqlite:///"):
        raise RuntimeError(
            "SENTINEL_DB_URL currently only supports sqlite:/// in this module. "
            "Swap _connect() for psycopg to target Postgres; the schema is portable."
        )
    path = DB_URL.replace("sqlite:///", "", 1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    """Create the triage table if it does not exist."""
    schema_file = BASE_DIR / "backend" / "sentinel_schema.sql"
    if schema_file.exists():
        ddl = schema_file.read_text()
    else:
        ddl = _INLINE_SCHEMA
    with _connect() as conn:
        conn.executescript(ddl)


_INLINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS triage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint         TEXT    UNIQUE NOT NULL,
    source              TEXT    NOT NULL,
    external_id         TEXT    NOT NULL,
    sender              TEXT    NOT NULL,
    subject             TEXT    NOT NULL,
    body_preview        TEXT    NOT NULL,
    memory_doc_ids      TEXT    NOT NULL DEFAULT '[]',
    priority            TEXT    NOT NULL,
    category            TEXT    NOT NULL,
    action              TEXT    NOT NULL,
    one_liner           TEXT    NOT NULL,
    verdict_json        TEXT    NOT NULL,
    blind_spots_json    TEXT    NOT NULL DEFAULT '[]',
    confidence          TEXT    NOT NULL,
    received_at         TEXT    NOT NULL,
    processed_at        TEXT    NOT NULL,
    resolved            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_triage_priority    ON triage(priority);
CREATE INDEX IF NOT EXISTS idx_triage_received    ON triage(received_at);
CREATE INDEX IF NOT EXISTS idx_triage_resolved    ON triage(resolved);
"""


def _already_processed(fingerprint: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM triage WHERE fingerprint = ? LIMIT 1", (fingerprint,)
        ).fetchone()
        return row is not None


def _insert_triage(msg: Message, verdict: Verdict, memory_ids: list[str]) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO triage (
                fingerprint, source, external_id, sender, subject, body_preview,
                memory_doc_ids, priority, category, action, one_liner,
                verdict_json, blind_spots_json, confidence,
                received_at, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg.fingerprint(),
                msg.source,
                msg.external_id,
                msg.sender,
                msg.subject,
                msg.body[:400],
                json.dumps(memory_ids),
                verdict.priority,
                verdict.category,
                verdict.action,
                verdict.one_liner,
                json.dumps(asdict(verdict)),
                json.dumps(verdict.blind_spots),
                verdict.confidence,
                msg.received_at,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return int(cur.lastrowid or 0)


# ── Gmail ingestion ───────────────────────────────────────────────────────────

def _gmail_service():
    """
    Returns an authorized Gmail API client.
    Requires GMAIL_CREDS_PATH (OAuth client secret) and produces GMAIL_TOKEN_PATH
    on first run.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds: Optional[Credentials] = None
    if GMAIL_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_PATH), GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not GMAIL_CREDS_PATH.exists():
                raise FileNotFoundError(
                    f"Missing Gmail OAuth credentials at {GMAIL_CREDS_PATH}. "
                    "Download from Google Cloud Console > APIs & Services > Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(GMAIL_CREDS_PATH), GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        GMAIL_TOKEN_PATH.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode_part(part: dict) -> str:
    data = part.get("body", {}).get("data")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType", "").startswith("text/"):
        return _decode_part(payload)
    for part in payload.get("parts", []) or []:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            return _decode_part(part)
    for part in payload.get("parts", []) or []:
        if part.get("parts"):
            nested = _extract_body(part)
            if nested:
                return nested
    return ""


def _strip_quoted(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*On .+ wrote:\s*$", line):
            break
        if line.startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def fetch_important_emails(limit: int = 10, query: str = "is:important -category:promotions newer_than:2d") -> list[Message]:
    """Pull recent Important emails from Gmail and normalize them."""
    service = _gmail_service()
    listing = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
    ids = [m["id"] for m in listing.get("messages", [])]
    messages: list[Message] = []

    for mid in ids:
        full = service.users().messages().get(userId="me", id=mid, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in full["payload"].get("headers", [])}
        body = _strip_quoted(_extract_body(full["payload"])) or full.get("snippet", "")
        received_ts = int(full.get("internalDate", "0")) / 1000.0
        messages.append(Message(
            source="gmail",
            external_id=mid,
            sender=headers.get("from", "unknown"),
            subject=headers.get("subject", "(no subject)"),
            body=body[:8000],
            received_at=datetime.fromtimestamp(received_ts, tz=timezone.utc).isoformat(),
        ))
    return messages


# ── Demo / seed messages (works without Gmail OAuth) ──────────────────────────

DEMO_EMAILS: list[dict] = [
    {
        "sender": "sarah.lin@acme-capital.com",
        "subject": "Term sheet v3 - need your sign-off by Friday",
        "body": (
            "Hey Tyler, attached is v3 of the term sheet. We moved the valuation to $18M pre, "
            "added a 1x non-participating liquidation preference, and dropped the ratchet. "
            "Option pool is 12% pre-close. Need your signed reply by Friday 5pm ET or we miss "
            "the IC cycle. Happy to jump on a call Thursday if helpful."
        ),
    },
    {
        "sender": "ops@stripe.com",
        "subject": "Action required: dispute filed on charge ch_3Q...",
        "body": (
            "A dispute has been filed for a $2,400 charge from Fourseat Inc. Reason code: "
            "product not received. You have 7 days to submit evidence. Upload invoice, email "
            "threads, and delivery confirmation to the disputes dashboard."
        ),
    },
    {
        "sender": "marcus@designstudio.io",
        "subject": "Proposal: rebrand for Fourseat, $42k over 6 weeks",
        "body": (
            "Enjoyed our call. Proposal attached. Scope covers wordmark, illustration system, "
            "website v2, and a motion toolkit. $42,000 fixed. Kickoff May 5 if signed by April 28."
        ),
    },
    {
        "sender": "security-alerts@vercel.com",
        "subject": "Suspicious login from new device - fourseat-prod",
        "body": (
            "We detected a login to your Vercel team from a new device in Lagos, Nigeria. "
            "If this was not you, rotate your tokens immediately at vercel.com/account/tokens."
        ),
    },
    {
        "sender": "jenna@techcrunch.com",
        "subject": "Interested in covering Fourseat - 20 min this week?",
        "body": (
            "Hi Tyler, I cover AI tooling for founders at TechCrunch. Saw the boardroom demo on "
            "X. Would love to chat for a piece running next week. Any 20-minute slot Wed or Thu "
            "works on my end."
        ),
    },
    {
        "sender": "andre@prospect-enterprise.com",
        "subject": "Pilot: 50 seats for our portfolio founders",
        "body": (
            "Following up. Our LPs liked the boardroom concept. We want to pilot with 50 of our "
            "portfolio founders. Annual contract, $60k, procurement needs SOC2 Type 1 or a "
            "bridge letter. Can we get on a call next week?"
        ),
    },
    {
        "sender": "no-reply@calendly.com",
        "subject": "New booking: Intro call - Nov 12 at 2pm ET",
        "body": "Someone booked your 'Intro call' link. Attendee: priya@nextwave.vc. No notes provided.",
    },
    {
        "sender": "hello@producthunt.com",
        "subject": "Your launch is scheduled for next Tuesday",
        "body": (
            "Your Fourseat launch is live on the calendar for Tuesday 12:01am PT. Reminder: "
            "prepare your maker comment, 3 assets (1280x720), and a launch thread. Hunters with "
            ">500 followers drive 4x conversion."
        ),
    },
    {
        "sender": "legal@outbound-firm.com",
        "subject": "Cease and desist - alleged trademark infringement",
        "body": (
            "Our client, Fourseat Analytics LLC (Delaware), asserts prior common-law rights in "
            "the mark 'Fourseat' in the decision-intelligence category. Demand letter attached. "
            "Respond within 14 days to avoid escalation."
        ),
    },
    {
        "sender": "deals@newsletter.com",
        "subject": "50% off web hosting this weekend only",
        "body": "Flash sale on Bluehost. Don't miss out. Click here to claim.",
    },
]


def _seed_messages_from_dicts(items: list[dict], source: str = "gmail") -> list[Message]:
    now_iso = datetime.now(timezone.utc).isoformat()
    out: list[Message] = []
    for i, it in enumerate(items):
        ext_id = it.get("external_id") or f"demo-{hashlib.md5((it['sender'] + it['subject']).encode()).hexdigest()[:10]}"
        out.append(Message(
            source=source,
            external_id=ext_id,
            sender=it["sender"],
            subject=it["subject"],
            body=it["body"],
            received_at=it.get("received_at", now_iso),
        ))
    return out


def fetch_demo_messages(limit: int = 10) -> list[Message]:
    """Deterministic demo messages. Used when DEMO_MODE=1 or Gmail is not configured."""
    return _seed_messages_from_dicts(DEMO_EMAILS[:limit])


def _gmail_configured() -> bool:
    return GMAIL_CREDS_PATH.exists() or GMAIL_TOKEN_PATH.exists()


# ── Memory integration ────────────────────────────────────────────────────────

def _memory_collection():
    """Lazy-load the vector memory collection.

    ChromaDB pulls in heavy deps (onnxruntime, sentence-transformers) that can
    blow up cold starts or be missing entirely. We import on demand so the
    Sentinel pipeline still works even when Memory is offline.
    """
    try:
        from backend.board_mind import collection  # type: ignore
        return collection
    except Exception as exc:  # pragma: no cover - depends on env
        log.warning("memory collection unavailable: %s", exc)
        return None


def _ingest_into_memory(msg: Message) -> list[str]:
    """Store the message in Fourseat Memory (ChromaDB) with sentinel metadata.

    Never raises: returns [] if the memory layer is unavailable.
    """
    collection = _memory_collection()
    if collection is None:
        return []
    doc_id = f"sentinel_{msg.fingerprint()}"
    try:
        collection.upsert(
            ids=[doc_id],
            documents=[f"[{msg.source.upper()} from {msg.sender}] {msg.subject}\n\n{msg.body}"],
            metadatas=[{
                "source": f"sentinel:{msg.source}",
                "doc_type": "inbound_comm",
                "sender": msg.sender,
                "subject": msg.subject[:120],
                "received_at": msg.received_at,
            }],
        )
        return [doc_id]
    except Exception as exc:
        log.warning("memory ingest failed: %s", exc)
        return []


_UPSTREAM_ERROR_PREFIXES = (
    "[memory query error",
    "[claude unavailable",
    "[gpt-4 unavailable",
    "[gemini unavailable",
    "[nia.ai unavailable",
    "[cerebras unavailable",
    "[nvidia unavailable",
    "[summary unavailable",
)


def _is_upstream_error(text: str) -> bool:
    if not text:
        return False
    head = text.strip().lower()[:64]
    return any(head.startswith(p) for p in _UPSTREAM_ERROR_PREFIXES)


def _detect_blind_spots(msg: Message) -> list[str]:
    """
    Ask Memory whether this message contradicts, duplicates, or commits to something
    already in Fourseat's history. Returns a terse list of blind-spot strings.
    Returns an empty list when Memory is empty or the upstream LLM errored.
    """
    probe = (
        f"The founder just received this message from {msg.sender}: "
        f"Subject: {msg.subject}. Body: {msg.body[:1200]}. "
        f"List ONLY concrete blind spots: prior commitments, contradictions with past decisions, "
        f"duplicate asks, or relevant context the founder may have forgotten. "
        f"Return a short bullet list. If none, return exactly: NONE."
    )
    try:
        from backend.board_mind import query_memory  # lazy: optional dep
        result = query_memory(probe, top_k=6)
    except Exception as exc:
        log.debug("blind-spot probe skipped: %s", exc)
        return []

    if not result.get("has_memory"):
        return []
    answer = (result.get("answer") or "").strip()
    if _is_upstream_error(answer):
        return []
    if answer.upper().startswith("NONE") or "don't have enough information" in answer.lower():
        return []
    bullets = [re.sub(r"^[\-\*\u2022]\s*", "", ln).strip()
               for ln in answer.splitlines() if ln.strip()]
    bullets = [b for b in bullets if len(b) > 8 and not _is_upstream_error(b)]
    return bullets[:5]


# ── Agentic prompting engine ──────────────────────────────────────────────────

SENTINEL_VERDICT_INSTRUCTIONS = """You are the FOURSEAT SENTINEL verdict engine.

You will receive: (a) one inbound message, (b) a transcript of a 4-advisor Boardroom
debate (Strategy, Finance, Tech, Contrarian) that already analyzed the message, and
(c) a list of Memory blind spots.

Your job is to compress all of that into ONE machine-readable verdict. Be ruthless.
No prose outside the JSON. No em dashes.

Output ONLY valid JSON with this exact shape:
{
  "priority": "P0 | P1 | P2 | P3",
  "category": "Strategy | Finance | Tech | Ops | Noise",
  "action":   "Reply Now | Delegate | Schedule | Archive",
  "one_liner": "max 18 words, the decision the founder must make",
  "strategy_view":   "max 30 words, the Chief Strategy Officer angle",
  "finance_view":    "max 30 words, the CFO angle (numbers if possible)",
  "tech_view":       "max 30 words, the CTO angle",
  "contrarian_view": "max 30 words, the Contrarian stress-test",
  "blind_spots":     ["concrete blind spot 1", "..."],
  "confidence":      "High | Medium | Low",
  "reasoning":       "max 60 words, why this priority and action"
}

Priority rubric:
- P0: time-sensitive and materially affects revenue, fundraising, legal, or product-launch
- P1: important, needs a decision within 48h
- P2: useful, batch this week
- P3: noise, archive or auto-reply

Return ONLY the JSON object.
"""


def _build_debate_question(msg: Message, blind_spots: list[str]) -> tuple[str, str]:
    """Returns (question, context) to feed into run_debate()."""
    question = (
        f"Should the founder prioritize, delegate, schedule, or archive this inbound message, "
        f"and what is the single best next action?\n\n"
        f"FROM: {msg.sender}\nSUBJECT: {msg.subject}\n\nBODY:\n{msg.body[:2500]}"
    )
    context_lines = [f"Received at: {msg.received_at}", f"Channel: {msg.source}"]
    if blind_spots:
        context_lines.append("Memory blind spots:")
        context_lines.extend(f"- {b}" for b in blind_spots)
    return question, "\n".join(context_lines)


def _synthesize_verdict(msg: Message, debate: dict, blind_spots: list[str]) -> Verdict:
    """
    Call the same Claude/Cerebras path the Boardroom uses to compress the debate
    into a structured Verdict. Falls back to a safe Medium/P2 verdict on failure.
    """
    from backend.debate_engine import ask_claude  # local import to avoid cycles at module load

    chairman = debate.get("chairman", {})
    round2 = debate.get("round2", {})

    debate_transcript = json.dumps({
        "strategy":   round2.get("claude", ""),
        "finance":    round2.get("gpt4", ""),
        "tech":       round2.get("gemini", ""),
        "contrarian": round2.get("contrarian", ""),
        "chairman":   chairman,
    }, ensure_ascii=False)

    prompt = (
        f"INBOUND MESSAGE:\nFROM: {msg.sender}\nSUBJECT: {msg.subject}\nBODY: {msg.body[:1500]}\n\n"
        f"BOARDROOM DEBATE TRANSCRIPT (JSON):\n{debate_transcript}\n\n"
        f"MEMORY BLIND SPOTS:\n{json.dumps(blind_spots)}\n\n"
        f"Produce the Sentinel verdict JSON now."
    )
    raw = ask_claude(prompt, SENTINEL_VERDICT_INSTRUCTIONS)

    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = json.loads(cleaned)
    except Exception:
        data = {}

    def _pick(key: str, default: str) -> str:
        val = data.get(key)
        return val if isinstance(val, str) and val.strip() else default

    def _advisor_text(src: str, lens: str) -> str:
        text = (src or "").strip()
        if not text or _is_upstream_error(text):
            return f"[{lens} advisor offline - see raw debate log]"
        return text[:240]

    bs_raw = data.get("blind_spots")
    bs = bs_raw if isinstance(bs_raw, list) else blind_spots
    bs = [str(b)[:200] for b in bs if b and not _is_upstream_error(str(b))]

    chairman_verdict = chairman.get("verdict") if isinstance(chairman, dict) else ""
    default_one_liner = (
        chairman_verdict
        if chairman_verdict and not _is_upstream_error(chairman_verdict)
        else f"Review and route inbound {msg.source} from {msg.sender}."
    )

    priority = _pick("priority", "P2")
    if priority not in ("P0", "P1", "P2", "P3"):
        priority = "P2"
    category = _pick("category", "Ops")
    if category not in ("Strategy", "Finance", "Tech", "Ops", "Noise"):
        category = "Ops"
    action = _pick("action", "Schedule")
    if action not in ("Reply Now", "Delegate", "Schedule", "Archive"):
        action = "Schedule"
    confidence = _pick("confidence", chairman.get("confidence", "Medium") if isinstance(chairman, dict) else "Medium")
    if confidence not in ("High", "Medium", "Low"):
        confidence = "Medium"

    return Verdict(
        priority=priority,
        category=category,
        action=action,
        one_liner=_pick("one_liner", default_one_liner)[:240],
        strategy_view=_advisor_text(data.get("strategy_view") or round2.get("claude", ""), "Strategy"),
        finance_view=_advisor_text(data.get("finance_view") or round2.get("gpt4", ""), "Finance"),
        tech_view=_advisor_text(data.get("tech_view") or round2.get("gemini", ""), "Technology"),
        contrarian_view=_advisor_text(data.get("contrarian_view") or round2.get("contrarian", ""), "Contrarian"),
        blind_spots=bs[:5],
        confidence=confidence,
        reasoning=_pick("reasoning", "Heuristic fallback: Boardroom JSON unparsed, using round-2 signals."),
    )


# ── Orchestrator ──────────────────────────────────────────────────────────────

def triage_message(msg: Message, *, skip_if_seen: bool = True) -> Optional[dict]:
    """Full pipeline for a single message. Returns stored verdict row, or None if skipped."""
    if skip_if_seen and _already_processed(msg.fingerprint()):
        return None

    memory_ids = _ingest_into_memory(msg)

    try:
        blind_spots = _detect_blind_spots(msg)
    except Exception as exc:
        log.warning("blind-spot detection failed for %s: %s", msg.external_id, exc)
        blind_spots = []

    question, context = _build_debate_question(msg, blind_spots)

    try:
        debate = run_debate(question=question, context=context)
    except Exception as exc:
        log.warning("debate failed for %s: %s", msg.external_id, exc)
        debate = {"chairman": {}, "round2": {}, "round1": {}}

    try:
        verdict = _synthesize_verdict(msg, debate, blind_spots)
    except Exception as exc:
        log.warning("verdict synth failed for %s: %s", msg.external_id, exc)
        verdict = _fallback_verdict(msg, blind_spots)

    row_id = _insert_triage(msg, verdict, memory_ids)
    return {"id": row_id, "message": asdict(msg), "verdict": asdict(verdict)}


def triage_batch(messages: Iterable[Message]) -> list[dict]:
    init_db()
    out: list[dict] = []
    for m in messages:
        try:
            result = triage_message(m)
        except Exception as exc:
            log.exception("triage pipeline crashed on %s: %s", m.external_id, exc)
            continue
        if result:
            out.append(result)
    return out


def _fallback_verdict(msg: Message, blind_spots: list[str]) -> Verdict:
    """Safe, deterministic verdict used when AI providers are unavailable."""
    return Verdict(
        priority="P2",
        category="Ops",
        action="Schedule",
        one_liner=f"Review inbound from {msg.sender}: {msg.subject[:120]}",
        strategy_view="Strategy advisor offline. Review message against current quarterly priorities.",
        finance_view="Finance advisor offline. Check whether an amount, invoice, or commitment is involved.",
        tech_view="Technology advisor offline. Check whether a system, integration, or security action is required.",
        contrarian_view="Contrarian advisor offline. Ask what signal you would ignore if this were obvious.",
        blind_spots=blind_spots,
        confidence="Low",
        reasoning="AI providers unavailable; fell back to a safe triage placeholder. Configure NIA_API_KEY / ANTHROPIC_API_KEY / CEREBRAS_API_KEY to enable live verdicts.",
    )


# ── Briefing renderer ─────────────────────────────────────────────────────────

_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _load_recent_triage(limit: int = 25) -> list[sqlite3.Row]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM triage WHERE resolved = 0 ORDER BY received_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return list(rows)


def render_daily_brief(limit: int = 10) -> str:
    """Render a Markdown Daily Decision Briefing from stored triage rows."""
    init_db()
    rows = _load_recent_triage(limit=limit)
    rows.sort(key=lambda r: (_PRIORITY_ORDER.get(r["priority"], 9), r["received_at"]), reverse=False)
    rows = rows[:limit]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p_counts: dict[str, int] = {}
    for r in rows:
        p_counts[r["priority"]] = p_counts.get(r["priority"], 0) + 1

    header = [
        f"# Fourseat Daily Decision Briefing  |  {today}",
        "",
        f"**Queue:** {len(rows)} open items  |  "
        f"P0: {p_counts.get('P0', 0)}  |  "
        f"P1: {p_counts.get('P1', 0)}  |  "
        f"P2: {p_counts.get('P2', 0)}  |  "
        f"P3: {p_counts.get('P3', 0)}",
        "",
        "| # | Priority | Category | Action | From | Subject | One-Liner | Conf | Blind Spots |",
        "|---|----------|----------|--------|------|---------|-----------|------|-------------|",
    ]

    body = []
    for i, r in enumerate(rows, start=1):
        blind = ", ".join(json.loads(r["blind_spots_json"])) or "none"
        body.append(
            f"| {i} "
            f"| {r['priority']} "
            f"| {r['category']} "
            f"| {r['action']} "
            f"| {_md_cell(r['sender'])} "
            f"| {_md_cell(r['subject'])} "
            f"| {_md_cell(r['one_liner'])} "
            f"| {r['confidence']} "
            f"| {_md_cell(blind)} |"
        )

    footer = [
        "",
        "## Advisor Panel Highlights",
    ]
    for i, r in enumerate(rows[:5], start=1):
        v = json.loads(r["verdict_json"])
        footer.extend([
            f"### {i}. {r['priority']} {r['category']}: {r['subject']}",
            f"- Strategy: {v.get('strategy_view', '')}",
            f"- Finance: {v.get('finance_view', '')}",
            f"- Tech: {v.get('tech_view', '')}",
            f"- Contrarian: {v.get('contrarian_view', '')}",
            f"- Reasoning: {v.get('reasoning', '')}",
            "",
        ])

    return "\n".join(header + body + footer)


def _md_cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()[:160]


# ── Public entrypoints ───────────────────────────────────────────────────────

def run_daily_brief(limit: int = 10, *, demo: Optional[bool] = None) -> dict:
    """
    End-to-end: fetch -> triage -> render.

    If `demo` is None, auto-detects: uses demo messages when SENTINEL_DEMO_MODE=1
    or when Gmail OAuth credentials are not present. Returns a dict with the rendered
    Markdown brief, the raw queue rows, and runtime metadata.
    """
    init_db()

    if demo is None:
        demo = os.getenv("SENTINEL_DEMO_MODE", "").strip() == "1" or not _gmail_configured()

    source = "demo" if demo else "gmail"
    fetch_error: Optional[str] = None
    msgs: list[Message] = []
    try:
        if demo:
            msgs = fetch_demo_messages(limit=limit)
        else:
            msgs = fetch_important_emails(limit=limit)
    except Exception as e:
        fetch_error = f"fetch failed: {e}"
        log.warning(fetch_error)
        # Fall through with no messages; the triage batch just returns []

    try:
        triaged = triage_batch(msgs)
    except Exception as e:
        log.exception("triage batch failed: %s", e)
        triaged = []

    try:
        brief = render_daily_brief(limit=limit)
    except Exception as e:
        log.exception("brief render failed: %s", e)
        brief = f"# Fourseat Daily Decision Briefing\n\n_Brief unavailable: {e}_\n"

    payload = {
        "processed": len(triaged),
        "fetched": len(msgs),
        "source": source,
        "brief_markdown": brief,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if fetch_error:
        payload["error"] = fetch_error
    return payload


# ── Read APIs for the dashboard ───────────────────────────────────────────────

def list_queue(limit: int = 50, *, include_resolved: bool = False) -> list[dict]:
    """Return triage rows as dicts, ordered by priority then recency."""
    init_db()
    where = "" if include_resolved else "WHERE resolved = 0"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM triage {where} ORDER BY received_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    out: list[dict] = []
    for r in rows:
        verdict = json.loads(r["verdict_json"]) if r["verdict_json"] else {}
        out.append({
            "id": r["id"],
            "fingerprint": r["fingerprint"],
            "source": r["source"],
            "sender": r["sender"],
            "subject": r["subject"],
            "body_preview": r["body_preview"],
            "priority": r["priority"],
            "category": r["category"],
            "action": r["action"],
            "one_liner": r["one_liner"],
            "confidence": r["confidence"],
            "blind_spots": json.loads(r["blind_spots_json"] or "[]"),
            "strategy_view": verdict.get("strategy_view", ""),
            "finance_view": verdict.get("finance_view", ""),
            "tech_view": verdict.get("tech_view", ""),
            "contrarian_view": verdict.get("contrarian_view", ""),
            "reasoning": verdict.get("reasoning", ""),
            "received_at": r["received_at"],
            "processed_at": r["processed_at"],
            "resolved": bool(r["resolved"]),
        })

    out.sort(key=lambda r: (_PRIORITY_ORDER.get(r["priority"], 9), r["received_at"]))
    return out


def mark_resolved(triage_id: int, resolved: bool = True) -> bool:
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE triage SET resolved = ? WHERE id = ?",
            (1 if resolved else 0, int(triage_id)),
        )
        return cur.rowcount > 0


def queue_stats() -> dict:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT priority, COUNT(*) AS n FROM triage WHERE resolved = 0 GROUP BY priority"
        ).fetchall()
    counts = {r["priority"]: int(r["n"]) for r in rows}
    total = sum(counts.values())
    return {
        "total_open": total,
        "by_priority": {p: counts.get(p, 0) for p in ("P0", "P1", "P2", "P3")},
    }


if __name__ == "__main__":
    out = run_daily_brief(limit=10)
    print(out["brief_markdown"])
