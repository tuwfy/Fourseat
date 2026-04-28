"""
Fourseat - Flask API Server

Serves the web UI and exposes endpoints for all three modules.
Hardened with strict security headers, upload validation, request-size
limits, basic per-IP rate limiting, and a same-origin CORS posture.
"""

import os
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.utils import secure_filename

try:
    from flask_cors import CORS
except Exception:  # pragma: no cover - optional dep
    CORS = None  # type: ignore

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dep
    def load_dotenv():
        return None

load_dotenv()

from backend.debate_engine import run_debate
from backend.waitlist import (
    add_waitlist_entry,
    count_waitlist,
    email_configured,
    load_waitlist,
    public_waitlist_count,
)
from backend.billing import create_checkout_session


# ── Configuration ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DEFAULT_DATA_DIR = (
    Path("/tmp/fourseat-data") if os.getenv("VERCEL") else (BASE_DIR / "data")
)
DATA_DIR = Path(os.getenv("FOURSEAT_DATA_DIR", str(DEFAULT_DATA_DIR)))
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_UPLOAD_EXTS = {".pdf", ".txt", ".md"}
MAX_UPLOAD_BYTES = 12 * 1024 * 1024          # 12 MB per file
MAX_REQUEST_BYTES = 16 * 1024 * 1024         # 16 MB request body cap
ALLOWED_FRONTEND_FILES = {
    "styles.css",
    "app.js",
    "manifest.webmanifest",
    "sw.js",
    "orb.png",
    "favicon-32.png",
    "favicon-180.png",
    "icon-192.png",
    "icon-512.png",
    "logo-wordmark.png",
    "logo-circle.png",
    "admin.html",
    "admin.js",
    "sentinel.html",
    "sentinel.js",
}

IS_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
IS_PRODUCTION = os.getenv("VERCEL") or os.getenv("FOURSEAT_ENV", "").lower() == "production"


def _resolve_secret_key() -> str:
    key = os.getenv("FLASK_SECRET_KEY", "").strip()
    if key:
        return key
    # No signed-session auth in this app, so a fresh per-process random key is safe.
    # Log a warning in production so an operator can set FLASK_SECRET_KEY explicitly
    # if/when stable session continuity is needed across cold starts.
    if IS_PRODUCTION and not IS_DEBUG:
        import logging
        logging.getLogger("fourseat").warning(
            "FLASK_SECRET_KEY not set; using a per-process random key. "
            "Set FLASK_SECRET_KEY in your environment for stable sessions."
        )
    return secrets.token_urlsafe(48)


app = Flask(
    __name__,
    static_folder="frontend/static",
    template_folder="frontend/templates",
)
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
app.config["JSON_SORT_KEYS"] = False
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.secret_key = _resolve_secret_key()

# CORS: same-origin only by default. Use FOURSEAT_ALLOWED_ORIGINS to allow more.
_allowed_origins = [
    o.strip() for o in os.getenv("FOURSEAT_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
if CORS is not None:
    if _allowed_origins:
        CORS(
            app,
            resources={r"/api/*": {"origins": _allowed_origins}},
            supports_credentials=False,
            methods=["GET", "POST", "OPTIONS"],
            max_age=600,
        )
    # Otherwise rely on browser's default same-origin policy.


# ── Security headers ─────────────────────────────────────────────────────────

CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "manifest-src 'self'; "
    "object-src 'none'; "
    "worker-src 'self'"
)


@app.after_request
def apply_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    )
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy", CSP)
    if IS_PRODUCTION:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=63072000; includeSubDomains; preload",
        )
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    response.headers.setdefault("X-XSS-Protection", "0")
    response.headers.setdefault("Origin-Agent-Cluster", "?1")
    return response


# ── Rate limiting (best-effort, in-process) ──────────────────────────────────

_rate_lock = threading.Lock()
_rate_buckets: dict = {}


def _client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _check_rate_limit(key: str, limit: int, window_s: int) -> bool:
    """Return True when the request is within the limit."""
    now = time.monotonic()
    bucket_key = f"{key}:{_client_ip()}"
    with _rate_lock:
        bucket = _rate_buckets.get(bucket_key)
        if bucket is None:
            bucket = deque()
            _rate_buckets[bucket_key] = bucket
        cutoff = now - window_s
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        # Periodic cleanup to bound memory.
        if len(_rate_buckets) > 10_000:
            for k in list(_rate_buckets.keys())[:1000]:
                if not _rate_buckets[k]:
                    _rate_buckets.pop(k, None)
        return True


def rate_limited(key: str, limit: int, window_s: int):
    """Decorator factory for per-IP rate limiting."""
    def decorator(fn):
        from functools import wraps

        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not _check_rate_limit(key, limit, window_s):
                return jsonify({"error": "rate limit exceeded. Please slow down."}), 429
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ── Error handlers ───────────────────────────────────────────────────────────

def _server_error(message: str, exc: Exception):
    app.logger.exception("%s: %s", message, exc)
    if IS_DEBUG:
        return jsonify({"error": f"{message}: {exc}"}), 500
    return jsonify({"error": "internal server error"}), 500


@app.errorhandler(RequestEntityTooLarge)
def _too_large(_e):
    return jsonify({"error": "request body too large"}), 413


@app.errorhandler(HTTPException)
def _http_error(e):
    return jsonify({"error": e.description or e.name}), e.code


@app.errorhandler(Exception)
def _unhandled(e):  # pragma: no cover
    return _server_error("unexpected error", e)


# ── Frontend ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


@app.route("/terms")
@app.route("/tos")
def terms_page():
    return send_from_directory("frontend", "index.html")


@app.route("/privacy")
def privacy_page():
    return send_from_directory("frontend", "index.html")


@app.route("/waitlist")
def waitlist_page():
    return send_from_directory("frontend", "index.html")


@app.route("/frontend/<path:path>")
def frontend_files(path):
    # Defense-in-depth: only serve known static assets, never traverse upward.
    safe = Path(path).name
    if safe != path or safe not in ALLOWED_FRONTEND_FILES:
        abort(404)
    return send_from_directory("frontend", safe)


# ── Health check ────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "1.1.0"})


# ── Module 1: Boardroom Debate ──────────────────────────────────────────────

@app.route("/api/debate", methods=["POST"])
@rate_limited("debate", limit=10, window_s=60)
def debate():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()[:4000]
    context = (body.get("context") or "").strip()[:6000]

    if not question:
        return jsonify({"error": "question is required"}), 400

    try:
        result = run_debate(question=question, context=context)
        return jsonify(result)
    except Exception as e:
        return _server_error("debate failed", e)


# ── Waitlist & billing ──────────────────────────────────────────────────────

@app.route("/api/waitlist", methods=["POST"])
@rate_limited("waitlist", limit=5, window_s=60)
def waitlist_join():
    body = request.get_json(silent=True) or {}
    result = add_waitlist_entry(
        email=(body.get("email") or "").strip()[:200],
        name=(body.get("name") or "").strip()[:120],
        company=(body.get("company") or "").strip()[:160],
    )
    if not result.get("success"):
        return jsonify({"error": result.get("error", "unable to add waitlist entry")}), 400
    # Don't leak per-recipient provider success/failure to the browser.
    return jsonify({k: v for k, v in result.items() if k != "email_notifications"})


@app.route("/api/waitlist/count", methods=["GET"])
@rate_limited("waitlist_count", limit=60, window_s=60)
def waitlist_count_endpoint():
    """Public counter so the site can show 'X founders already joined'."""
    return jsonify({"count": public_waitlist_count()})


# ── Admin (waitlist dashboard) ──────────────────────────────────────────────

import hmac
from functools import wraps


def _require_admin_token(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = (os.getenv("FOURSEAT_ADMIN_TOKEN") or "").strip()
        if not expected:
            return jsonify({"error": "admin is not configured"}), 503
        header = (request.headers.get("Authorization") or "").strip()
        provided = ""
        if header.lower().startswith("bearer "):
            provided = header[7:].strip()
        else:
            provided = request.args.get("token", "").strip()
        if not provided or not hmac.compare_digest(provided, expected):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


@app.route("/admin")
def admin_page():
    return send_from_directory("frontend", "admin.html")


@app.route("/api/admin/waitlist", methods=["GET"])
@rate_limited("admin_waitlist", limit=60, window_s=60)
@_require_admin_token
def admin_waitlist():
    try:
        limit = max(0, min(int(request.args.get("limit", "200")), 1000))
    except ValueError:
        limit = 200
    entries = load_waitlist()
    if limit:
        entries = entries[:limit]
    return jsonify(
        {
            "count": count_waitlist(),
            "entries": entries,
            "blob_configured": bool((os.getenv("BLOB_READ_WRITE_TOKEN") or "").strip()),
            "owner_email_configured": bool(
                (os.getenv("WAITLIST_OWNER_EMAIL") or "").strip()
            ),
            "email_configured": email_configured(),
            "resend_configured": bool((os.getenv("RESEND_API_KEY") or "").strip()),
            "smtp_configured": bool((os.getenv("SMTP_HOST") or "").strip())
            and bool((os.getenv("SMTP_USERNAME") or "").strip())
            and bool((os.getenv("SMTP_PASSWORD") or "").strip()),
        }
    )


@app.route("/api/admin/waitlist.csv", methods=["GET"])
@rate_limited("admin_waitlist_csv", limit=20, window_s=60)
@_require_admin_token
def admin_waitlist_csv():
    import csv
    import io

    entries = load_waitlist()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["created_at", "email", "name", "company"])
    for e in entries:
        writer.writerow(
            [
                e.get("created_at", ""),
                e.get("email", ""),
                e.get("name", ""),
                e.get("company", ""),
            ]
        )
    csv_bytes = buf.getvalue().encode("utf-8")
    from flask import Response

    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=fourseat-waitlist.csv"},
    )


@app.route("/api/billing/checkout-session", methods=["POST"])
@rate_limited("checkout", limit=5, window_s=60)
def billing_checkout_session():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip()[:200]
    name = (body.get("name") or "").strip()[:120]
    result = create_checkout_session(email=email, name=name)
    if not result.get("success"):
        return jsonify({"error": result.get("error", "unable to create checkout session")}), 400
    return jsonify(result)


# ── Module 2: Fourseat Memory ───────────────────────────────────────────────

@app.route("/api/memory/upload", methods=["POST"])
@rate_limited("memory_upload", limit=10, window_s=60)
def memory_upload():
    from backend.board_mind import ingest_document  # lazy: optional dep

    if "file" not in request.files:
        return jsonify({"error": "no file provided"}), 400

    f = request.files["file"]
    doc_type = (request.form.get("doc_type") or "general").strip().lower()[:32]
    label = (request.form.get("label") or "").strip()[:200]

    safe_name = secure_filename(f.filename or "")
    if not safe_name:
        return jsonify({"error": "invalid filename"}), 400

    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTS:
        return jsonify({"error": "only PDF, TXT, or Markdown files are accepted"}), 400

    save_path = UPLOAD_DIR / safe_name
    f.save(str(save_path))
    try:
        if save_path.stat().st_size > MAX_UPLOAD_BYTES:
            save_path.unlink(missing_ok=True)
            return jsonify({"error": "file is too large (max 12 MB)"}), 413
    except OSError as e:
        return _server_error("upload failed", e)

    try:
        result = ingest_document(str(save_path), doc_type=doc_type, label=label or safe_name)
    except Exception as e:
        return _server_error("ingestion failed", e)
    return jsonify(result)


@app.route("/api/memory/query", methods=["POST"])
@rate_limited("memory_query", limit=20, window_s=60)
def memory_query():
    from backend.board_mind import query_memory

    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()[:2000]
    if not question:
        return jsonify({"error": "question is required"}), 400

    try:
        result = query_memory(question)
    except Exception as e:
        return _server_error("memory query failed", e)
    return jsonify(result)


@app.route("/api/memory/documents", methods=["GET"])
def memory_documents():
    from backend.board_mind import get_all_documents

    try:
        docs = get_all_documents()
    except Exception as e:
        return _server_error("failed to list documents", e)
    return jsonify({"documents": docs})


# ── Module 3: Fourseat Decks ────────────────────────────────────────────────

@app.route("/api/brief/generate", methods=["POST"])
@rate_limited("brief", limit=10, window_s=60)
def brief_generate():
    from backend.board_brief import generate_board_deck

    body = request.get_json(silent=True) or {}
    for field in ("company_name", "period", "metrics"):
        if not body.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    # Trim free-text inputs defensively.
    for f in ("company_name", "period", "highlights", "challenges", "ask"):
        if isinstance(body.get(f), str):
            body[f] = body[f][:4000]

    try:
        result = generate_board_deck(body)
        if result.get("success") and result.get("filename"):
            safe = Path(result["filename"]).name
            result["filename"] = safe
            result["download_url"] = f"/api/brief/download/{safe}"
        return jsonify(result)
    except Exception as e:
        return _server_error("brief generation failed", e)


@app.route("/api/brief/download/<path:filename>")
def brief_download(filename):
    safe = Path(filename).name
    if not safe or safe != filename:
        abort(404)
    filepath = (OUTPUT_DIR / safe).resolve()
    try:
        filepath.relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        abort(404)
    if not filepath.exists() or not filepath.is_file():
        return jsonify({"error": "file not found"}), 404
    return send_file(
        str(filepath),
        as_attachment=True,
        download_name=safe,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


# ── Module 4: Sentinel (proactive triage) ───────────────────────────────────

@app.route("/sentinel")
def sentinel_page():
    return send_from_directory("frontend", "sentinel.html")


@app.route("/api/sentinel/run", methods=["POST"])
@rate_limited("sentinel_run", limit=6, window_s=60)
def sentinel_run():
    from backend.sentinel import run_daily_brief

    body = request.get_json(silent=True) or {}
    try:
        limit = max(1, min(int(body.get("limit", 10)), 25))
    except (TypeError, ValueError):
        limit = 10
    demo = body.get("demo")
    if isinstance(demo, str):
        demo = demo.lower() in ("1", "true", "yes")
    elif demo is not None:
        demo = bool(demo)

    try:
        result = run_daily_brief(limit=limit, demo=demo)
        return jsonify(result)
    except Exception as e:
        return _server_error("sentinel run failed", e)


@app.route("/api/sentinel/queue", methods=["GET"])
@rate_limited("sentinel_queue", limit=60, window_s=60)
def sentinel_queue():
    from backend.sentinel import list_queue, queue_stats

    try:
        limit = max(1, min(int(request.args.get("limit", "50")), 200))
    except ValueError:
        limit = 50
    include_resolved = request.args.get("include_resolved", "0").lower() in ("1", "true", "yes")
    try:
        rows = list_queue(limit=limit, include_resolved=include_resolved)
        return jsonify({"queue": rows, "stats": queue_stats()})
    except Exception as e:
        return _server_error("sentinel queue failed", e)


@app.route("/api/sentinel/brief", methods=["GET"])
@rate_limited("sentinel_brief", limit=30, window_s=60)
def sentinel_brief():
    from backend.sentinel import render_daily_brief, queue_stats

    try:
        limit = max(1, min(int(request.args.get("limit", "10")), 50))
    except ValueError:
        limit = 10
    try:
        md = render_daily_brief(limit=limit)
        return jsonify({"markdown": md, "stats": queue_stats()})
    except Exception as e:
        return _server_error("sentinel brief failed", e)


@app.route("/api/sentinel/resolve", methods=["POST"])
@rate_limited("sentinel_resolve", limit=60, window_s=60)
def sentinel_resolve():
    from backend.sentinel import mark_resolved

    body = request.get_json(silent=True) or {}
    try:
        triage_id = int(body.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id is required"}), 400
    resolved = bool(body.get("resolved", True))
    ok = mark_resolved(triage_id, resolved=resolved)
    if not ok:
        return jsonify({"error": "triage row not found"}), 404
    return jsonify({"success": True, "id": triage_id, "resolved": resolved})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    print(f"\nFourseat running at http://localhost:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=IS_DEBUG)
