"""
Waitlist handling for Fourseat.

Responsibilities:
- Validate and de-duplicate signups.
- Append entries to a JSONL file on disk (local dir in dev, /tmp on Vercel).
- Mirror the JSONL to Vercel Blob when BLOB_READ_WRITE_TOKEN is set so
  the list survives serverless cold starts.
- Send a branded HTML + plaintext confirmation to the signup, and a
  notification to the configured owner on every new entry.
- Expose load/count helpers used by the admin dashboard.
"""

from __future__ import annotations

import json
import logging
import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("fourseat.waitlist")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = Path("/tmp/fourseat-data") if os.getenv("VERCEL") else (BASE_DIR / "data")
DATA_DIR = Path(os.getenv("FOURSEAT_DATA_DIR", str(DEFAULT_DATA_DIR)))
WAITLIST_FILE = DATA_DIR / "waitlist" / "waitlist.jsonl"
WAITLIST_FILE.parent.mkdir(parents=True, exist_ok=True)

BRAND_NAME = "Fourseat"
BRAND_TAGLINE = "A board of advisors for every decision."

# ─── Disk + Blob persistence ────────────────────────────────────────────────

def _blob_token() -> str:
    return (os.getenv("BLOB_READ_WRITE_TOKEN") or "").strip()


def _blob_pathname() -> str:
    return os.getenv("FOURSEAT_WAITLIST_BLOB", "fourseat/waitlist.jsonl").strip()


def _load_from_blob() -> Optional[List[dict]]:
    """Best-effort pull of the waitlist file from Vercel Blob."""
    token = _blob_token()
    if not token:
        return None
    try:
        import requests  # already in requirements
        # List blobs with prefix to discover current URL (Blob stores can vary).
        list_url = "https://blob.vercel-storage.com"
        params = {"prefix": _blob_pathname(), "limit": "1"}
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(list_url, params=params, headers=headers, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        blobs = data.get("blobs") or []
        if not blobs:
            return []
        url = blobs[0].get("url")
        if not url:
            return []
        rr = requests.get(url, timeout=8)
        if rr.status_code != 200:
            return None
        entries = []
        for line in rr.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries
    except Exception as e:  # pragma: no cover
        log.warning("waitlist blob load failed: %s", e)
        return None


def _save_to_blob(jsonl_text: str) -> bool:
    """Best-effort upload of the waitlist file to Vercel Blob."""
    token = _blob_token()
    if not token:
        return False
    try:
        import requests
        pathname = _blob_pathname()
        url = f"https://blob.vercel-storage.com/{pathname}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/plain; charset=utf-8",
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
        }
        r = requests.put(url, data=jsonl_text.encode("utf-8"), headers=headers, timeout=12)
        return r.status_code in (200, 201)
    except Exception as e:  # pragma: no cover
        log.warning("waitlist blob save failed: %s", e)
        return False


def _read_local() -> List[dict]:
    if not WAITLIST_FILE.exists():
        return []
    out: List[dict] = []
    try:
        for line in WAITLIST_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError as e:
        log.warning("waitlist read failed: %s", e)
    return out


def _write_local(entries: List[dict]) -> None:
    WAITLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
    if text:
        text += "\n"
    WAITLIST_FILE.write_text(text, encoding="utf-8")


def load_waitlist() -> List[dict]:
    """Load entries, merging Blob (when configured) with the local file."""
    remote = _load_from_blob()
    local = _read_local()
    if remote is None:
        return local
    # Merge by email, newest created_at wins for name/company updates.
    merged: Dict[str, dict] = {}
    for e in local + remote:
        key = (e.get("email") or "").strip().lower()
        if not key:
            continue
        existing = merged.get(key)
        if existing is None or (e.get("created_at") or "") > (existing.get("created_at") or ""):
            merged[key] = e
    out = list(merged.values())
    out.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    return out


def count_waitlist() -> int:
    return len(load_waitlist())


# ─── Email plumbing ─────────────────────────────────────────────────────────

def _from_address() -> str:
    addr = os.getenv("SMTP_FROM_EMAIL", "no-reply@fourseat.ai").strip()
    name = os.getenv("SMTP_FROM_NAME", BRAND_NAME).strip()
    return formataddr((name, addr))


def _build_email(subject: str, to_email: str, text: str, html: Optional[str] = None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = to_email
    msg["From"] = _from_address()
    reply_to = os.getenv("WAITLIST_OWNER_EMAIL", "").strip()
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _send_email(msg: EmailMessage) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    if not host or not username or not password:
        log.info("SMTP not configured; skipping email to %s", msg.get("To"))
        return False

    port = int(os.getenv("SMTP_PORT", "587"))
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20) as server:
                server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.ehlo()
                if use_tls:
                    server.starttls()
                    server.ehlo()
                server.login(username, password)
                server.send_message(msg)
        return True
    except Exception as e:
        log.warning("SMTP send to %s failed: %s", msg.get("To"), e)
        return False


# ─── Email templates ────────────────────────────────────────────────────────

def _customer_text(name: str) -> str:
    greet = f"Hi {name}," if name else "Hi,"
    return (
        f"{greet}\n\n"
        f"Thanks for joining the {BRAND_NAME} waitlist.\n\n"
        f"{BRAND_NAME} is a decision workspace for founders and operators. A panel "
        "of strategy, finance, technology, and contrarian advisors pressure-tests "
        "every important call before you commit.\n\n"
        "What happens next:\n"
        "  1. We email you a secure link when your workspace is ready.\n"
        "  2. You sign in and convene your first board.\n"
        "  3. First verdict in under a minute, structured by a Board Chair.\n\n"
        "Reply to this email any time; it reaches us directly.\n\n"
        f"Team {BRAND_NAME}\n"
        f"{BRAND_TAGLINE}\n"
    )


def _customer_html(name: str) -> str:
    greet = f"Hi {name}," if name else "Hi,"
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#110f0d;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Inter,sans-serif;color:#eeeae2;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#110f0d;">
    <tr><td align="center" style="padding:32px 16px;">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:#1a1613;border:1px solid rgba(232,186,131,.15);border-radius:20px;overflow:hidden;">
        <tr><td style="padding:32px 32px 8px 32px;">
          <div style="font-family:Georgia,'Instrument Serif',serif;font-size:22px;color:#fff;letter-spacing:-.01em;">{BRAND_NAME}</div>
          <div style="font-size:12px;color:#e8ba83;letter-spacing:.12em;text-transform:uppercase;margin-top:6px;">You're on the list</div>
        </td></tr>
        <tr><td style="padding:20px 32px 8px 32px;">
          <div style="font-family:Georgia,'Instrument Serif',serif;font-size:30px;line-height:1.15;color:#fff;margin-bottom:16px;">Thanks for joining<br/><em style="color:rgba(255,255,255,.65)">early access.</em></div>
          <p style="font-size:15px;line-height:1.65;color:rgba(255,255,255,.78);margin:0 0 16px 0;">{greet}</p>
          <p style="font-size:15px;line-height:1.65;color:rgba(255,255,255,.78);margin:0 0 16px 0;">
            {BRAND_NAME} is a decision workspace for founders and operators. A panel of
            strategy, finance, technology, and contrarian advisors pressure-tests every
            important call, and a Board Chair returns a structured verdict with risks,
            opportunities, and next steps.
          </p>
          <p style="font-size:15px;line-height:1.65;color:rgba(255,255,255,.78);margin:0 0 16px 0;">
            We'll email you a secure link the moment your workspace is ready. Reply to
            this email any time; it reaches us directly.
          </p>
        </td></tr>
        <tr><td style="padding:8px 32px 28px 32px;">
          <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;background:rgba(232,186,131,.06);border:1px solid rgba(232,186,131,.18);border-radius:14px;">
            <tr><td style="padding:16px 20px;">
              <div style="font-size:12px;color:#e8ba83;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px;">What to expect</div>
              <div style="font-size:14px;color:rgba(255,255,255,.82);line-height:1.55;">
                → Early access link via email<br/>
                → First verdict in under a minute<br/>
                → A four-advisor board + Chair synthesis
              </div>
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:0 32px 28px 32px;border-top:1px solid rgba(255,255,255,.05);">
          <p style="font-size:12px;color:rgba(255,255,255,.4);margin:16px 0 0 0;line-height:1.55;">
            You're receiving this because you signed up at {BRAND_NAME}. Guidance provided is not legal, tax, or investment advice.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>
"""


def _owner_text(entry: dict, total: int) -> str:
    return (
        f"New {BRAND_NAME} waitlist signup. Total so far: {total}\n\n"
        f"Name:    {entry.get('name') or '-'}\n"
        f"Email:   {entry.get('email')}\n"
        f"Company: {entry.get('company') or '-'}\n"
        f"When:    {entry.get('created_at')}\n"
    )


def _owner_html(entry: dict, total: int) -> str:
    def row(label, value):
        return (
            f"<tr>"
            f"<td style='padding:6px 12px 6px 0;font-size:12px;color:#8a8377;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap;'>{label}</td>"
            f"<td style='padding:6px 0;font-size:14px;color:#1a1613;'>{value or '-'}</td>"
            f"</tr>"
        )

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f4efe6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,sans-serif;color:#1a1613;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:32px 16px;">
      <table role="presentation" width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;background:#fff;border:1px solid #e6ddc8;border-radius:16px;">
        <tr><td style="padding:24px 24px 8px 24px;">
          <div style="font-family:Georgia,'Instrument Serif',serif;font-size:20px;color:#1a1613;">{BRAND_NAME} · New signup</div>
          <div style="font-size:13px;color:#8a8377;margin-top:4px;">Total waitlist entries: <strong>{total}</strong></div>
        </td></tr>
        <tr><td style="padding:12px 24px 24px 24px;">
          <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;">
            {row('Name', entry.get('name'))}
            {row('Email', entry.get('email'))}
            {row('Company', entry.get('company'))}
            {row('When', entry.get('created_at'))}
          </table>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>
"""


# ─── Public API ─────────────────────────────────────────────────────────────

def add_waitlist_entry(email: str, name: str = "", company: str = "") -> dict:
    clean_email = (email or "").strip().lower()
    clean_name = (name or "").strip()[:120]
    clean_company = (company or "").strip()[:160]

    if not clean_email:
        return {"success": False, "error": "email is required"}
    if not EMAIL_RE.match(clean_email):
        return {"success": False, "error": "email is invalid"}
    if len(clean_email) > 200:
        return {"success": False, "error": "email is too long"}

    entries = load_waitlist()
    existing = next((e for e in entries if (e.get("email") or "").lower() == clean_email), None)

    now = datetime.now(timezone.utc).isoformat()
    if existing:
        already_existed = True
        existing.setdefault("created_at", now)
        existing["updated_at"] = now
        if clean_name:
            existing["name"] = clean_name
        if clean_company:
            existing["company"] = clean_company
        entry = existing
        # Put the updated entry first.
        entries = [e for e in entries if (e.get("email") or "").lower() != clean_email]
        entries.insert(0, entry)
    else:
        already_existed = False
        entry = {
            "email": clean_email,
            "name": clean_name,
            "company": clean_company,
            "created_at": now,
        }
        entries.insert(0, entry)

    try:
        _write_local(entries)
    except OSError as e:
        log.warning("waitlist local write failed: %s", e)

    # Best-effort mirror to Blob so the list survives cold starts.
    jsonl = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
    _save_to_blob(jsonl)

    total = len(entries)

    # Customer confirmation (idempotent; resend on repeat signup is fine).
    customer_sent = _send_email(
        _build_email(
            subject=f"You're on the {BRAND_NAME} waitlist",
            to_email=clean_email,
            text=_customer_text(clean_name),
            html=_customer_html(clean_name),
        )
    )

    # Owner notification.
    owner_email = os.getenv("WAITLIST_OWNER_EMAIL", "").strip()
    owner_sent = False
    if owner_email and not already_existed:
        owner_sent = _send_email(
            _build_email(
                subject=f"New {BRAND_NAME} signup #{total} · {clean_email}",
                to_email=owner_email,
                text=_owner_text(entry, total),
                html=_owner_html(entry, total),
            )
        )

    return {
        "success": True,
        "entry": entry,
        "already_existed": already_existed,
        "total": total,
        "email_notifications": {
            "customer_confirmation_sent": customer_sent,
            "owner_confirmation_sent": owner_sent,
        },
    }
