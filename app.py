"""
Fourseat - Flask API Server

Serves the web UI and exposes endpoints for all three modules.
Hardened with strict security headers, upload validation, request-size
limits, basic per-IP rate limiting, and a same-origin CORS posture.
"""

import json
import os
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory
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
from backend.sentinel import connector_status
from backend.stripe_oracle import (
    connector_status as oracle_connector_status,
    ingest_stripe_event,
    list_verdicts as oracle_list_verdicts,
    mark_verdict_resolved,
    attach_deck_filename,
    run_oracle_scan,
    snapshot_summary,
    verdict_stats as oracle_verdict_stats,
    verify_stripe_signature,
    build_deck_payload,
    STRIPE_WEBHOOK_SECRET,
)
from backend.company_brain import (
    connector_status as brain_connector_status,
    artifact_counts as brain_artifact_counts,
    list_artifacts as brain_list_artifacts,
    list_signals as brain_list_signals,
    mark_signal_resolved as brain_mark_resolved,
    signal_stats as brain_signal_stats,
    query_brain,
    run_brain_scan,
    fetch_slack as brain_fetch_slack,
    fetch_github as brain_fetch_github,
    fetch_linear as brain_fetch_linear,
    fetch_quickbooks as brain_fetch_quickbooks,
    fetch_notion as brain_fetch_notion,
    upsert_artifacts as brain_upsert,
    verify_slack_signature as brain_verify_slack,
    verify_github_signature as brain_verify_github,
    verify_linear_signature as brain_verify_linear,
    SLACK_SIGNING_SECRET as BRAIN_SLACK_SECRET,
    GITHUB_WEBHOOK_SECRET as BRAIN_GITHUB_SECRET,
    LINEAR_WEBHOOK_SECRET as BRAIN_LINEAR_SECRET,
)


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
    "orb_crop.png",
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
    "oracle.html",
    "oracle.js",
    "help.js",
    "help.html",
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
    return send_from_directory("frontend", "help.html")


@app.route("/privacy")
def privacy_page():
    return send_from_directory("frontend", "help.html")

@app.route("/help.html")
def help_page():
    return send_from_directory("frontend", "help.html")


@app.route("/waitlist")
def waitlist_page():
    return send_from_directory("frontend", "index.html")


@app.route("/how")
def how_page():
    return send_from_directory("frontend", "index.html")


@app.route("/pricing")
def pricing_page():
    return send_from_directory("frontend", "index.html")


@app.route("/about")
def about_page():
    return send_from_directory("frontend", "index.html")


@app.route("/robots.txt")
def robots_txt():
    base = request.url_root.rstrip("/")
    body = (
        "User-agent: *\n"
        "Allow: /\n\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain; charset=utf-8")


@app.route("/sitemap.xml")
def sitemap_xml():
    base = request.url_root.rstrip("/")
    urls = (
        "/",
        "/oracle",
        "/how",
        "/pricing",
        "/about",
        "/waitlist",
        "/terms",
        "/privacy",
    )
    xml_urls = "".join(
        f"<url><loc>{base}{path}</loc></url>"
        for path in urls
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{xml_urls}"
        "</urlset>"
    )
    return Response(xml, mimetype="application/xml; charset=utf-8")


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
    """Sentinel was deprecated in favour of Oracle. Permanent redirect for any
    bookmarks or external links that still point at /sentinel."""
    from flask import redirect
    return redirect("/oracle", code=301)


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


@app.route("/api/sentinel/connectors", methods=["GET"])
@rate_limited("sentinel_connectors", limit=60, window_s=60)
def sentinel_connectors():
    try:
        return jsonify({"connectors": connector_status()})
    except Exception as e:
        return _server_error("sentinel connector status failed", e)


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


# ── Module 5: Oracle (Stripe revenue intelligence) ──────────────────────────

@app.route("/oracle")
def oracle_page():
    return send_from_directory("frontend", "oracle.html")


@app.route("/api/oracle/connectors", methods=["GET"])
@rate_limited("oracle_connectors", limit=60, window_s=60)
def oracle_connectors():
    try:
        return jsonify({"connectors": oracle_connector_status()})
    except Exception as e:
        return _server_error("oracle connector status failed", e)


@app.route("/api/oracle/scan", methods=["POST", "GET"])
@rate_limited("oracle_scan", limit=12, window_s=60)
def oracle_scan():
    """POST is the interactive trigger; GET is the Vercel Cron entrypoint."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
    else:
        body = {k: v for k, v in request.args.items()}
    demo = body.get("demo")
    if isinstance(demo, str):
        demo = demo.lower() in ("1", "true", "yes")
    elif demo is not None:
        demo = bool(demo)
    force_reseed = bool(body.get("force_reseed"))
    try:
        result = run_oracle_scan(demo=demo, force_reseed=force_reseed)
        return jsonify(result)
    except Exception as e:
        return _server_error("oracle scan failed", e)


@app.route("/api/oracle/snapshot", methods=["GET"])
@rate_limited("oracle_snapshot", limit=60, window_s=60)
def oracle_snapshot():
    try:
        limit = max(1, min(int(request.args.get("limit", "60")), 365))
    except ValueError:
        limit = 60
    try:
        return jsonify({"summary": snapshot_summary(limit=limit)})
    except Exception as e:
        return _server_error("oracle snapshot failed", e)


@app.route("/api/oracle/verdicts", methods=["GET"])
@rate_limited("oracle_verdicts", limit=60, window_s=60)
def oracle_verdicts():
    try:
        limit = max(1, min(int(request.args.get("limit", "20")), 100))
    except ValueError:
        limit = 20
    include_resolved = request.args.get("include_resolved", "0").lower() in ("1", "true", "yes")
    try:
        rows = oracle_list_verdicts(limit=limit, include_resolved=include_resolved)
        return jsonify({"verdicts": rows, "stats": oracle_verdict_stats()})
    except Exception as e:
        return _server_error("oracle verdicts failed", e)


@app.route("/api/oracle/resolve", methods=["POST"])
@rate_limited("oracle_resolve", limit=60, window_s=60)
def oracle_resolve():
    body = request.get_json(silent=True) or {}
    try:
        verdict_id = int(body.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id is required"}), 400
    resolved = bool(body.get("resolved", True))
    if not mark_verdict_resolved(verdict_id, resolved=resolved):
        return jsonify({"error": "verdict not found"}), 404
    return jsonify({"success": True, "id": verdict_id, "resolved": resolved})


@app.route("/api/oracle/deck", methods=["POST"])
@rate_limited("oracle_deck", limit=8, window_s=60)
def oracle_deck():
    """Generate a Revenue Health Briefing .pptx for a stored verdict and
    persist the filename back onto the verdict row."""
    from backend.board_brief import generate_board_deck

    body = request.get_json(silent=True) or {}
    try:
        verdict_id = int(body.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id is required"}), 400

    matches = [v for v in oracle_list_verdicts(limit=200, include_resolved=True) if v.get("id") == verdict_id]
    if not matches:
        return jsonify({"error": "verdict not found"}), 404
    verdict = matches[0]

    company_name = (body.get("company_name") or "Fourseat").strip()[:120] or "Fourseat"
    payload = build_deck_payload(verdict, company_name=company_name)

    try:
        result = generate_board_deck(payload)
    except Exception as e:
        return _server_error("oracle deck generation failed", e)

    if result.get("success") and result.get("filename"):
        safe = Path(result["filename"]).name
        result["filename"] = safe
        result["download_url"] = f"/api/brief/download/{safe}"
        attach_deck_filename(verdict_id, safe)
    return jsonify(result)


@app.route("/api/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Receive Stripe events. Verifies signature when STRIPE_WEBHOOK_SECRET is
    configured; otherwise rejects with 401 to prevent unsigned ingestion."""
    raw_body = request.get_data(cache=False, as_text=False) or b""
    sig_header = request.headers.get("Stripe-Signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({"error": "stripe webhook not configured"}), 503

    if not verify_stripe_signature(raw_body, sig_header, STRIPE_WEBHOOK_SECRET):
        return jsonify({"error": "invalid signature"}), 401

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return jsonify({"error": "invalid json"}), 400

    if not isinstance(event, dict) or not event.get("type"):
        return jsonify({"error": "invalid event"}), 400

    ok = ingest_stripe_event(event)
    if not ok:
        return jsonify({"error": "ingest failed"}), 500
    return jsonify({"received": True, "type": event.get("type")})


# ── Module 6: Company Brain (cross-source intelligence) ─────────────────────

@app.route("/api/brain/connectors", methods=["GET"])
@rate_limited("brain_connectors", limit=60, window_s=60)
def brain_connectors():
    try:
        return jsonify({
            "connectors": brain_connector_status(),
            "artifact_counts": brain_artifact_counts(),
        })
    except Exception as e:
        return _server_error("brain connectors failed", e)


@app.route("/api/brain/scan", methods=["POST", "GET"])
@rate_limited("brain_scan", limit=10, window_s=60)
def brain_scan():
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
    else:
        body = {k: v for k, v in request.args.items()}
    demo = body.get("demo")
    if isinstance(demo, str):
        demo = demo.lower() in ("1", "true", "yes")
    elif demo is not None:
        demo = bool(demo)
    force_reseed = bool(body.get("force_reseed"))
    try:
        return jsonify(run_brain_scan(demo=demo, force_reseed=force_reseed))
    except Exception as e:
        return _server_error("brain scan failed", e)


@app.route("/api/brain/ingest", methods=["POST"])
@rate_limited("brain_ingest", limit=10, window_s=60)
def brain_ingest():
    """Manual trigger to pull a single source's recent artifacts. Used by the
    dashboard's per-connector refresh buttons."""
    body = request.get_json(silent=True) or {}
    source = (body.get("source") or "").strip().lower()
    fetchers = {
        "slack":      brain_fetch_slack,
        "github":     brain_fetch_github,
        "linear":     brain_fetch_linear,
        "quickbooks": brain_fetch_quickbooks,
        "notion":     brain_fetch_notion,
    }
    fn = fetchers.get(source)
    if not fn:
        return jsonify({"error": "unknown source"}), 400
    try:
        arts = fn()
        ids = brain_upsert(arts) if arts else []
        return jsonify({"source": source, "ingested": len(ids), "ids": ids})
    except Exception as e:
        return _server_error("brain ingest failed", e)


@app.route("/api/brain/query", methods=["POST"])
@rate_limited("brain_query", limit=20, window_s=60)
def brain_query():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()[:1000]
    if not question:
        return jsonify({"error": "question is required"}), 400
    try:
        return jsonify(query_brain(question))
    except Exception as e:
        return _server_error("brain query failed", e)


@app.route("/api/brain/artifacts", methods=["GET"])
@rate_limited("brain_artifacts", limit=60, window_s=60)
def brain_artifacts():
    try:
        limit = max(1, min(int(request.args.get("limit", "50")), 500))
    except ValueError:
        limit = 50
    source = (request.args.get("source") or "").strip().lower()
    try:
        return jsonify({"artifacts": brain_list_artifacts(limit=limit, source=source)})
    except Exception as e:
        return _server_error("brain artifacts failed", e)


@app.route("/api/brain/signals", methods=["GET"])
@rate_limited("brain_signals", limit=60, window_s=60)
def brain_signals():
    try:
        limit = max(1, min(int(request.args.get("limit", "20")), 100))
    except ValueError:
        limit = 20
    include_resolved = request.args.get("include_resolved", "0").lower() in ("1", "true", "yes")
    try:
        return jsonify({
            "signals": brain_list_signals(limit=limit, include_resolved=include_resolved),
            "stats": brain_signal_stats(),
        })
    except Exception as e:
        return _server_error("brain signals failed", e)


@app.route("/api/brain/signals/resolve", methods=["POST"])
@rate_limited("brain_resolve", limit=60, window_s=60)
def brain_resolve():
    body = request.get_json(silent=True) or {}
    try:
        signal_id = int(body.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id is required"}), 400
    resolved = bool(body.get("resolved", True))
    if not brain_mark_resolved(signal_id, resolved=resolved):
        return jsonify({"error": "signal not found"}), 404
    return jsonify({"success": True, "id": signal_id, "resolved": resolved})


@app.route("/api/slack/webhook", methods=["POST"])
def slack_webhook():
    """Slack Events API: handles the URL verification challenge plus signed
    inbound events. Drops a small subset (`message.channels`) into artifacts."""
    raw = request.get_data(cache=False, as_text=False) or b""
    ts = request.headers.get("X-Slack-Request-Timestamp", "")
    sig = request.headers.get("X-Slack-Signature", "")

    # Always honour Slack's url_verification challenge first (no signature required).
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        body = {}
    if isinstance(body, dict) and body.get("type") == "url_verification":
        return jsonify({"challenge": body.get("challenge", "")})

    if not BRAIN_SLACK_SECRET:
        return jsonify({"error": "slack webhook not configured"}), 503
    if not brain_verify_slack(raw, ts, sig, BRAIN_SLACK_SECRET):
        return jsonify({"error": "invalid signature"}), 401

    event = (body or {}).get("event", {}) if isinstance(body, dict) else {}
    if event.get("type") == "message" and event.get("text") and event.get("subtype") is None:
        from backend.company_brain import Artifact, upsert_artifacts as _upsert
        from datetime import datetime as _dt, timezone as _tz
        ts_str = str(event.get("ts") or "")
        try:
            occurred = _dt.fromtimestamp(float(ts_str), tz=_tz.utc).isoformat()
        except Exception:
            occurred = _dt.now(_tz.utc).isoformat()
        ch = event.get("channel", "")
        _upsert([Artifact(
            source="slack",
            artifact_type="message",
            external_id=f"{ch}:{ts_str}",
            title=(event.get("text") or "").split("\n", 1)[0][:200],
            body=(event.get("text") or "")[:6000],
            author=f"slack:{event.get('user') or event.get('bot_id') or 'unknown'}",
            url=f"https://slack.com/archives/{ch}/p{ts_str.replace('.', '')}",
            tags=[f"channel:{ch}"],
            metadata={"channel_id": ch, "ts": ts_str, "thread_ts": event.get("thread_ts")},
            occurred_at=occurred,
        )])
    return jsonify({"received": True})


@app.route("/api/github/webhook", methods=["POST"])
def github_webhook():
    """GitHub webhooks: pull_request and issues events get ingested directly."""
    raw = request.get_data(cache=False, as_text=False) or b""
    sig = request.headers.get("X-Hub-Signature-256", "")
    event_type = request.headers.get("X-GitHub-Event", "")
    if not BRAIN_GITHUB_SECRET:
        return jsonify({"error": "github webhook not configured"}), 503
    if not brain_verify_github(raw, sig, BRAIN_GITHUB_SECRET):
        return jsonify({"error": "invalid signature"}), 401
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return jsonify({"error": "invalid json"}), 400

    from backend.company_brain import Artifact, upsert_artifacts as _upsert
    repo = (payload.get("repository") or {}).get("full_name", "")
    if event_type == "pull_request" and repo:
        pr = payload.get("pull_request") or {}
        tags = ["pr", "merged" if pr.get("merged_at") else pr.get("state", "open")]
        for lbl in (pr.get("labels") or []):
            n = (lbl.get("name") if isinstance(lbl, dict) else str(lbl)).strip()
            if n: tags.append(f"label:{n}")
        _upsert([Artifact(
            source="github",
            artifact_type="pr",
            external_id=f"{repo}#pr-{pr.get('number')}",
            title=(pr.get("title") or "")[:300],
            body=(pr.get("body") or "")[:5000] or (pr.get("title") or ""),
            author=(pr.get("user") or {}).get("login", "")[:200],
            url=pr.get("html_url", ""),
            tags=tags,
            metadata={"repo": repo, "number": pr.get("number"), "state": pr.get("state"), "merged_at": pr.get("merged_at")},
            occurred_at=pr.get("updated_at") or pr.get("created_at") or "",
        )])
    elif event_type == "issues" and repo:
        it = payload.get("issue") or {}
        tags = ["issue", it.get("state", "open")]
        for lbl in (it.get("labels") or []):
            n = (lbl.get("name") if isinstance(lbl, dict) else str(lbl)).strip()
            if n: tags.append(f"label:{n}")
        _upsert([Artifact(
            source="github",
            artifact_type="issue",
            external_id=f"{repo}#issue-{it.get('number')}",
            title=(it.get("title") or "")[:300],
            body=(it.get("body") or "")[:4000] or (it.get("title") or ""),
            author=(it.get("user") or {}).get("login", "")[:200],
            url=it.get("html_url", ""),
            tags=tags,
            metadata={"repo": repo, "number": it.get("number"), "state": it.get("state")},
            occurred_at=it.get("updated_at") or it.get("created_at") or "",
        )])
    return jsonify({"received": True, "event": event_type})


@app.route("/api/linear/webhook", methods=["POST"])
def linear_webhook():
    """Linear webhook: signed with linear-signature header (raw HMAC-SHA-256 hex)."""
    raw = request.get_data(cache=False, as_text=False) or b""
    sig = request.headers.get("Linear-Signature", "")
    if not BRAIN_LINEAR_SECRET:
        return jsonify({"error": "linear webhook not configured"}), 503
    if not brain_verify_linear(raw, sig, BRAIN_LINEAR_SECRET):
        return jsonify({"error": "invalid signature"}), 401
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return jsonify({"error": "invalid json"}), 400

    if (payload.get("type") or "").lower() != "issue":
        return jsonify({"received": True, "ignored": payload.get("type")})

    from backend.company_brain import Artifact, upsert_artifacts as _upsert
    data = payload.get("data") or {}
    state_name = (data.get("state") or {}).get("name", "")
    state_type = (data.get("state") or {}).get("type", "")
    tags = ["linear-issue", f"state:{state_name.lower()}", f"state-type:{state_type.lower()}"]
    for l in ((data.get("labels") or {}).get("nodes") or []):
        if l.get("name"): tags.append(f"label:{l['name']}")
    _upsert([Artifact(
        source="linear",
        artifact_type="issue",
        external_id=data.get("id") or data.get("identifier") or "",
        title=(data.get("identifier", "") + " " + (data.get("title") or "")).strip()[:300],
        body=(data.get("description") or data.get("title") or "")[:5000],
        author=((data.get("assignee") or {}).get("name") or "")[:200],
        url=data.get("url", ""),
        tags=tags,
        metadata={
            "identifier": data.get("identifier"),
            "priority": data.get("priority"),
            "state_name": state_name,
            "state_type": state_type,
            "completed_at": data.get("completedAt"),
        },
        occurred_at=data.get("updatedAt") or data.get("createdAt") or "",
    )])
    return jsonify({"received": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    print(f"\nFourseat running at http://localhost:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=IS_DEBUG)
