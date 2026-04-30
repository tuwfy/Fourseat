-- Fourseat Company Brain schema.
-- One artifacts table is the unified surface every connector writes into.
-- FTS5 virtual table provides full-text search across the whole brain.

CREATE TABLE IF NOT EXISTS artifacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint     TEXT    UNIQUE NOT NULL,
    source          TEXT    NOT NULL,             -- slack | github | linear | notion | stripe
    artifact_type   TEXT    NOT NULL,             -- message | pr | issue | doc | event
    external_id     TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    body            TEXT    NOT NULL,
    author          TEXT    NOT NULL DEFAULT '',
    url             TEXT    NOT NULL DEFAULT '',
    tags_json       TEXT    NOT NULL DEFAULT '[]',
    metadata_json   TEXT    NOT NULL DEFAULT '{}',
    occurred_at     TEXT    NOT NULL,
    ingested_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_source   ON artifacts(source);
CREATE INDEX IF NOT EXISTS idx_artifacts_type     ON artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifacts_occurred ON artifacts(occurred_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_author   ON artifacts(author);

-- FTS5 mirror so we can do natural-language search across every source.
CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5(
    title, body, author, tags,
    content='', tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS brain_signals (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint                 TEXT    UNIQUE NOT NULL,
    rule                        TEXT    NOT NULL,
    priority                    TEXT    NOT NULL,
    one_liner                   TEXT    NOT NULL,
    evidence_json               TEXT    NOT NULL DEFAULT '{}',
    involved_artifact_ids_json  TEXT    NOT NULL DEFAULT '[]',
    strategy_view               TEXT    NOT NULL DEFAULT '',
    finance_view                TEXT    NOT NULL DEFAULT '',
    tech_view                   TEXT    NOT NULL DEFAULT '',
    contrarian_view             TEXT    NOT NULL DEFAULT '',
    actions_json                TEXT    NOT NULL DEFAULT '[]',
    watch_metrics_json          TEXT    NOT NULL DEFAULT '[]',
    confidence                  TEXT    NOT NULL DEFAULT 'Medium',
    detected_at                 TEXT    NOT NULL,
    resolved                    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_brain_signals_priority ON brain_signals(priority);
CREATE INDEX IF NOT EXISTS idx_brain_signals_resolved ON brain_signals(resolved);

CREATE TABLE IF NOT EXISTS brain_queries (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    question                 TEXT    NOT NULL,
    answer                   TEXT    NOT NULL DEFAULT '',
    cited_artifact_ids_json  TEXT    NOT NULL DEFAULT '[]',
    asked_at                 TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brain_queries_asked ON brain_queries(asked_at);
