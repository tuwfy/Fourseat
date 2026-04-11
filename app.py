"""
Fourseat - Flask API Server
Serves the web UI and exposes endpoints for all three modules.
"""

import os
import json
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# Import our modules
from backend.debate_engine import run_debate, BOARD_PERSONAS
from backend.board_mind    import ingest_document, query_memory, get_all_documents
from backend.board_brief   import generate_board_deck

BASE_DIR   = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
OUTPUT_DIR = BASE_DIR / "data" / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder="frontend/static", template_folder="frontend/templates")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "boardroom-dev-key")
CORS(app)


# ── Serve frontend ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


@app.route("/frontend/<path:path>")
def frontend_files(path):
    return send_from_directory("frontend", path)


# ── Health check ───────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "1.0.0"})


# ── Module 1: Boardroom Debate ─────────────────────────────────────────────────

@app.route("/api/debate", methods=["POST"])
def debate():
    body     = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    context  = (body.get("context") or "").strip()

    if not question:
        return jsonify({"error": "question is required"}), 400

    try:
        result = run_debate(question, context)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Module 2: Fourseat Memory ────────────────────────────────────────────────────────

@app.route("/api/memory/upload", methods=["POST"])
def memory_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f        = request.files["file"]
    doc_type = request.form.get("doc_type", "general")
    label    = request.form.get("label", "")

    from werkzeug.utils import secure_filename
    safe_name = secure_filename(f.filename)
    if not safe_name:
        return jsonify({"error": "Invalid filename"}), 400
    save_path = UPLOAD_DIR / safe_name
    f.save(str(save_path))

    result = ingest_document(str(save_path), doc_type=doc_type, label=label or f.filename)
    return jsonify(result)


@app.route("/api/memory/query", methods=["POST"])
def memory_query():
    body     = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()

    if not question:
        return jsonify({"error": "question is required"}), 400

    result = query_memory(question)
    return jsonify(result)


@app.route("/api/memory/documents", methods=["GET"])
def memory_documents():
    docs = get_all_documents()
    return jsonify({"documents": docs})


# ── Module 3: Fourseat Decks ───────────────────────────────────────────────────────

@app.route("/api/brief/generate", methods=["POST"])
def brief_generate():
    body = request.get_json(silent=True) or {}

    required = ["company_name", "period", "metrics"]
    for field in required:
        if not body.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    try:
        result = generate_board_deck(body)
        if result["success"]:
            result["download_url"] = f"/api/brief/download/{result['filename']}"
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/brief/download/<filename>")
def brief_download(filename):
    safe = Path(filename).name  # prevent path traversal
    filepath = OUTPUT_DIR / safe
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(
        str(filepath),
        as_attachment=True,
        download_name=safe,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


if __name__ == "__main__":
    port  = int(os.getenv("PORT", 5001))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    print(f"\n🎯 Fourseat running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
