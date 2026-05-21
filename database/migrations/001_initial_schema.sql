-- =============================================================================
-- Migration 001 — Initial Schema
-- Run once on a fresh Neon PostgreSQL database.
-- Command: psql $DATABASE_URL -f database/migrations/001_initial_schema.sql
-- =============================================================================

-- ── 1. earnings_calendar ──────────────────────────────────────────────────────
-- Live upcoming results. Refreshed every pipeline run.
-- UNIQUE on (result_date, company_name) — upserts never duplicate.
CREATE TABLE IF NOT EXISTS earnings_calendar (
    id               SERIAL PRIMARY KEY,
    result_date      DATE        NOT NULL,
    company_name     TEXT        NOT NULL,
    symbol           TEXT,
    meeting_type     TEXT        DEFAULT 'Quarterly Results',
    source           TEXT,                          -- 'nse_official_file', 'bse_official_file', etc.
    -- Enriched columns (filled by enrich.py)
    sector           TEXT,
    is_fo            BOOLEAN     DEFAULT FALSE,
    is_nifty50       BOOLEAN     DEFAULT FALSE,
    is_nifty_next50  BOOLEAN     DEFAULT FALSE,
    is_banknifty     BOOLEAN     DEFAULT FALSE,
    market_cap_tier  TEXT,                          -- 'large','mid','small'
    importance_score INTEGER     DEFAULT 0,
    -- Metadata
    fetched_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (result_date, company_name)
);

-- ── 2. historical_snapshots ───────────────────────────────────────────────────
-- Every successful pipeline run saves a full snapshot here.
-- Never overwritten — append-only. Enables seasonality / trend analytics.
CREATE TABLE IF NOT EXISTS historical_snapshots (
    id               SERIAL PRIMARY KEY,
    pipeline_run_id  TEXT        NOT NULL,
    result_date      DATE        NOT NULL,
    company_name     TEXT        NOT NULL,
    symbol           TEXT,
    meeting_type     TEXT,
    source           TEXT,
    sector           TEXT,
    is_fo            BOOLEAN,
    importance_score INTEGER,
    snapshot_taken_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for time-range queries on historical data
CREATE INDEX IF NOT EXISTS idx_snapshots_result_date
    ON historical_snapshots (result_date);

CREATE INDEX IF NOT EXISTS idx_snapshots_run_id
    ON historical_snapshots (pipeline_run_id);

-- ── 3. analytics_cache ────────────────────────────────────────────────────────
-- Stores precomputed analytics as JSONB.
-- Key examples: 'sector_concentration', 'top_earnings', 'daily_distribution'
CREATE TABLE IF NOT EXISTS analytics_cache (
    cache_key   TEXT PRIMARY KEY,
    cache_value JSONB        NOT NULL,
    computed_at TIMESTAMPTZ  DEFAULT NOW()
);

-- ── 4. pipeline_logs ──────────────────────────────────────────────────────────
-- One row per pipeline execution. Dashboard reads this for health panel.
CREATE TABLE IF NOT EXISTS pipeline_logs (
    id                SERIAL PRIMARY KEY,
    run_id            TEXT        UNIQUE NOT NULL,
    started_at        TIMESTAMPTZ DEFAULT NOW(),
    completed_at      TIMESTAMPTZ,
    source_used       TEXT,
    rows_fetched      INTEGER     DEFAULT 0,
    rows_valid        INTEGER     DEFAULT 0,
    rows_stored       INTEGER     DEFAULT 0,
    validation_passed BOOLEAN,
    fallback_used     BOOLEAN     DEFAULT FALSE,
    error_message     TEXT,
    duration_seconds  FLOAT,
    status            TEXT        DEFAULT 'running'  -- 'running','success','failed','partial'
);

-- ── 5. fo_universe ────────────────────────────────────────────────────────────
-- Master reference table for all F&O stocks with enrichment metadata.
-- Seeded from data/fo_universe.csv via pipeline/seed.py.
CREATE TABLE IF NOT EXISTS fo_universe (
    symbol            TEXT PRIMARY KEY,
    company_name_hint TEXT,
    sector            TEXT,
    sub_sector        TEXT,
    is_nifty50        BOOLEAN  DEFAULT FALSE,
    is_nifty_next50   BOOLEAN  DEFAULT FALSE,
    is_banknifty      BOOLEAN  DEFAULT FALSE,
    market_cap_tier   TEXT     DEFAULT 'mid',   -- 'large','mid','small'
    base_importance   INTEGER  DEFAULT 0,
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- ── 6. sector_map ─────────────────────────────────────────────────────────────
-- Symbol → sector lookup for enrichment.
-- Seeded from data/sector_map.csv.
CREATE TABLE IF NOT EXISTS sector_map (
    symbol      TEXT PRIMARY KEY,
    sector      TEXT NOT NULL,
    sub_sector  TEXT,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- Done. Verify with: \dt
-- =============================================================================
