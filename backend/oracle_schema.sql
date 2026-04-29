-- Fourseat Oracle (Stripe revenue intelligence) schema.
-- Portable to Postgres with minor type tweaks (TEXT -> VARCHAR, INTEGER -> BIGINT).

CREATE TABLE IF NOT EXISTS revenue_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint     TEXT    UNIQUE NOT NULL,
    stripe_event_id TEXT    NOT NULL,
    event_type      TEXT    NOT NULL,
    customer_id     TEXT,
    subscription_id TEXT,
    plan_id         TEXT,
    amount_cents    INTEGER NOT NULL DEFAULT 0,
    currency        TEXT    NOT NULL DEFAULT 'usd',
    metadata_json   TEXT    NOT NULL DEFAULT '{}',
    occurred_at     TEXT    NOT NULL,
    ingested_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_type     ON revenue_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_occurred ON revenue_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_customer ON revenue_events(customer_id);

CREATE TABLE IF NOT EXISTS revenue_snapshots (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date         TEXT    UNIQUE NOT NULL,
    mrr_cents             INTEGER NOT NULL DEFAULT 0,
    new_mrr_cents         INTEGER NOT NULL DEFAULT 0,
    churn_mrr_cents       INTEGER NOT NULL DEFAULT 0,
    expansion_cents       INTEGER NOT NULL DEFAULT 0,
    contraction_cents     INTEGER NOT NULL DEFAULT 0,
    failed_payments_count INTEGER NOT NULL DEFAULT 0,
    failed_payments_cents INTEGER NOT NULL DEFAULT 0,
    nrr_pct               REAL    NOT NULL DEFAULT 100.0,
    active_subs           INTEGER NOT NULL DEFAULT 0,
    top_customer_share    REAL    NOT NULL DEFAULT 0.0,
    tier_breakdown_json   TEXT    NOT NULL DEFAULT '{}',
    computed_at           TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON revenue_snapshots(snapshot_date);

CREATE TABLE IF NOT EXISTS revenue_verdicts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint         TEXT    UNIQUE NOT NULL,
    rule                TEXT    NOT NULL,
    priority            TEXT    NOT NULL,
    one_liner           TEXT    NOT NULL,
    evidence_json       TEXT    NOT NULL DEFAULT '{}',
    strategy_view       TEXT    NOT NULL DEFAULT '',
    finance_view        TEXT    NOT NULL DEFAULT '',
    tech_view           TEXT    NOT NULL DEFAULT '',
    contrarian_view     TEXT    NOT NULL DEFAULT '',
    actions_json        TEXT    NOT NULL DEFAULT '[]',
    watch_metrics_json  TEXT    NOT NULL DEFAULT '[]',
    confidence          TEXT    NOT NULL DEFAULT 'Medium',
    detected_at         TEXT    NOT NULL,
    resolved            INTEGER NOT NULL DEFAULT 0,
    deck_filename       TEXT
);
CREATE INDEX IF NOT EXISTS idx_verdicts_priority ON revenue_verdicts(priority);
CREATE INDEX IF NOT EXISTS idx_verdicts_resolved ON revenue_verdicts(resolved);
CREATE INDEX IF NOT EXISTS idx_verdicts_detected ON revenue_verdicts(detected_at);
