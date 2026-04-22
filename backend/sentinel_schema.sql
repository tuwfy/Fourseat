-- Fourseat Sentinel - Triage schema
-- Portable across SQLite and PostgreSQL. For Postgres, replace:
--   INTEGER PRIMARY KEY AUTOINCREMENT -> BIGSERIAL PRIMARY KEY
--   TEXT                              -> TEXT (same)
--   INTEGER NOT NULL DEFAULT 0        -> BOOLEAN NOT NULL DEFAULT FALSE
--
-- The `memory_doc_ids` column stores a JSON array of ChromaDB ids, which
-- links each triage row back to Fourseat_Memory (the boardmind collection).

CREATE TABLE IF NOT EXISTS triage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint         TEXT    UNIQUE NOT NULL,   -- sha256(source:external_id)[:16]
    source              TEXT    NOT NULL,          -- "gmail" | "slack"
    external_id         TEXT    NOT NULL,          -- provider message id
    sender              TEXT    NOT NULL,
    subject             TEXT    NOT NULL,
    body_preview        TEXT    NOT NULL,          -- first 400 chars
    memory_doc_ids      TEXT    NOT NULL DEFAULT '[]',  -- JSON array -> Chroma ids
    priority            TEXT    NOT NULL,          -- P0 | P1 | P2 | P3
    category            TEXT    NOT NULL,          -- Strategy | Finance | Tech | Ops | Noise
    action              TEXT    NOT NULL,          -- Reply Now | Delegate | Schedule | Archive
    one_liner           TEXT    NOT NULL,
    verdict_json        TEXT    NOT NULL,          -- full Verdict dataclass
    blind_spots_json    TEXT    NOT NULL DEFAULT '[]',
    confidence          TEXT    NOT NULL,          -- High | Medium | Low
    received_at         TEXT    NOT NULL,          -- ISO-8601
    processed_at        TEXT    NOT NULL,          -- ISO-8601
    resolved            INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_triage_priority ON triage(priority);
CREATE INDEX IF NOT EXISTS idx_triage_received ON triage(received_at);
CREATE INDEX IF NOT EXISTS idx_triage_resolved ON triage(resolved);
CREATE INDEX IF NOT EXISTS idx_triage_source   ON triage(source);

-- Optional join table for richer Memory links (one triage row -> many Memory chunks).
CREATE TABLE IF NOT EXISTS triage_memory_link (
    triage_id       INTEGER NOT NULL,
    memory_doc_id   TEXT    NOT NULL,             -- matches boardmind collection id
    link_type       TEXT    NOT NULL,             -- "ingested" | "blind_spot"
    PRIMARY KEY (triage_id, memory_doc_id, link_type),
    FOREIGN KEY (triage_id) REFERENCES triage(id) ON DELETE CASCADE
);
