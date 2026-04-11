"""
Fourseat - Fourseat Memory
Persistent company memory: ingests documents, stores context, answers queries.
Uses ChromaDB for vector storage and Claude for intelligent retrieval.
"""

import os
import json
import hashlib
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.utils import embedding_functions
from pypdf import PdfReader
import anthropic
from dotenv import load_dotenv

load_dotenv()

DATA_DIR   = Path(__file__).parent.parent / "data"
MEMORY_DIR = DATA_DIR / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

# ChromaDB persistent client
chroma_client = chromadb.PersistentClient(path=str(MEMORY_DIR / "chroma"))

# Use sentence-transformers default embeddings (free, no API key needed)
ef = embedding_functions.DefaultEmbeddingFunction()

collection = chroma_client.get_or_create_collection(
    name="boardmind",
    embedding_function=ef,
    metadata={"hnsw:space": "cosine"},
)

# ── Document ingestion ────────────────────────────────────────────────────────

def _extract_text_from_pdf(filepath: str) -> str:
    try:
        reader = PdfReader(filepath)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        return f"[PDF extraction error: {e}]"


def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return [c for c in chunks if len(c.strip()) > 50]


def ingest_document(filepath: str, doc_type: str = "general", label: str = "") -> dict:
    """
    Ingest a document (PDF or text) into Fourseat Memory memory.
    Returns summary of what was stored.
    """
    path = Path(filepath)
    if not path.exists():
        return {"success": False, "error": "File not found"}

    # Extract text
    if path.suffix.lower() == ".pdf":
        text = _extract_text_from_pdf(filepath)
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")

    if not text.strip():
        return {"success": False, "error": "No text extracted"}

    # Chunk
    chunks = _chunk_text(text)
    doc_id  = hashlib.md5(filepath.encode()).hexdigest()[:12]
    name    = label or path.name

    ids, docs, metas = [], [], []
    for idx, chunk in enumerate(chunks):
        ids.append(f"{doc_id}_{idx}")
        docs.append(chunk)
        metas.append({"source": name, "doc_type": doc_type, "chunk": idx})

    # Upsert into ChromaDB
    collection.upsert(ids=ids, documents=docs, metadatas=metas)

    # Generate AI summary of the whole document
    summary_prompt = (
        f"Summarize this business document in 3-5 bullet points. "
        f"Focus on strategic decisions, commitments, key metrics, and important dates.\n\n"
        f"{text[:4000]}"
    )
    try:
        resp = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=512,
            messages=[{"role": "user", "content": summary_prompt}],
        )
        summary = resp.content[0].text
    except Exception as e:
        summary = f"[Summary unavailable: {e}]"

    # Save metadata log
    log_path = MEMORY_DIR / "ingested.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else []
    log.append({"id": doc_id, "name": name, "type": doc_type, "chunks": len(chunks), "summary": summary})
    log_path.write_text(json.dumps(log, indent=2))

    return {"success": True, "name": name, "chunks": len(chunks), "summary": summary}


# ── Memory query ──────────────────────────────────────────────────────────────

def query_memory(question: str, top_k: int = 8) -> dict:
    """
    Query Fourseat Memory with a natural language question.
    Retrieves relevant chunks and synthesizes an answer.
    """
    # Retrieve relevant chunks from vector DB
    try:
        results = collection.query(query_texts=[question], n_results=min(top_k, collection.count()))
        chunks   = results["documents"][0] if results["documents"] else []
        sources  = [m["source"] for m in results["metadatas"][0]] if results["metadatas"] else []
    except Exception:
        chunks, sources = [], []

    if not chunks:
        return {
            "answer": "I don't have enough information in memory to answer this. Please upload relevant documents first.",
            "sources": [],
            "has_memory": False,
        }

    context = "\n\n---\n\n".join(chunks)
    unique_sources = list(dict.fromkeys(sources))

    synthesis_prompt = (
        f"You are Fourseat Memory, an AI with perfect memory of a company's entire history.\n"
        f"Answer the founder's question using ONLY the company documents below.\n"
        f"If the answer isn't in the documents, say so clearly.\n"
        f"Highlight any commitments, contradictions, or important context the founder should know.\n\n"
        f"COMPANY DOCUMENTS:\n{context}\n\n"
        f"FOUNDER'S QUESTION: {question}"
    )

    try:
        resp = anthropic_client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=1024,
            messages=[{"role": "user", "content": synthesis_prompt}],
        )
        answer = resp.content[0].text
    except Exception as e:
        answer = f"[Memory query error: {e}]"

    return {"answer": answer, "sources": unique_sources, "has_memory": True}


def get_all_documents() -> list:
    """Return list of all ingested documents."""
    log_path = MEMORY_DIR / "ingested.json"
    if log_path.exists():
        return json.loads(log_path.read_text())
    return []


def delete_document(doc_id: str) -> bool:
    """Remove a document from memory by ID."""
    try:
        # Get all IDs matching this doc
        results = collection.get(where={"$contains": doc_id} if False else {})
        ids_to_delete = [id_ for id_ in results["ids"] if id_.startswith(doc_id)]
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)

        # Update log
        log_path = MEMORY_DIR / "ingested.json"
        if log_path.exists():
            log = json.loads(log_path.read_text())
            log = [d for d in log if d["id"] != doc_id]
            log_path.write_text(json.dumps(log, indent=2))
        return True
    except Exception:
        return False
