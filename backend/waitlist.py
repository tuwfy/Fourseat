"""
Waitlist handling for Fourseat.
Stores entries locally and sends optional email notifications.
"""

import json
import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


BASE_DIR = Path(__file__).resolve().parent.parent
WAITLIST_FILE = BASE_DIR / "data" / "waitlist" / "waitlist.jsonl"
WAITLIST_FILE.parent.mkdir(parents=True, exist_ok=True)


def _build_email(subject: str, to_email: str, body_text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = to_email
    msg["From"] = os.getenv("SMTP_FROM_EMAIL", "no-reply@fourseat.ai")
    msg.set_content(body_text)
    return msg


def _send_email(msg: EmailMessage) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    if not host or not username or not password:
        return False

    port = int(os.getenv("SMTP_PORT", "587"))
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            if use_tls:
                server.starttls()
            server.login(username, password)
            server.send_message(msg)
        return True
    except Exception:
        return False


def add_waitlist_entry(email: str, name: str = "", company: str = "") -> dict:
    clean_email = (email or "").strip().lower()
    clean_name = (name or "").strip()
    clean_company = (company or "").strip()

    if not clean_email:
        return {"success": False, "error": "email is required"}
    if not EMAIL_RE.match(clean_email):
        return {"success": False, "error": "email is invalid"}

    payload = {
        "email": clean_email,
        "name": clean_name,
        "company": clean_company,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with WAITLIST_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")

    owner_email = os.getenv("WAITLIST_OWNER_EMAIL", "").strip()
    customer_sent = False
    owner_sent = False

    customer_subject = "You're on the Fourseat waitlist"
    customer_body = (
        "Thanks for joining the Fourseat waitlist.\n\n"
        "We received your request and will email you when your access is ready.\n\n"
        "Team Fourseat"
    )
    customer_sent = _send_email(_build_email(customer_subject, clean_email, customer_body))

    if owner_email:
        owner_subject = "New Fourseat waitlist signup"
        owner_body = (
            "A new user joined the waitlist.\n\n"
            f"Name: {clean_name or '-'}\n"
            f"Email: {clean_email}\n"
            f"Company: {clean_company or '-'}\n"
        )
        owner_sent = _send_email(_build_email(owner_subject, owner_email, owner_body))

    return {
        "success": True,
        "entry": payload,
        "email_notifications": {
            "customer_confirmation_sent": customer_sent,
            "owner_confirmation_sent": owner_sent,
        },
    }
