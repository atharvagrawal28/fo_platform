-- =============================================================================
-- Migration 002 — Canonical name column + stronger uniqueness
--
-- Why:
--   Migration 001 used UNIQUE (result_date, company_name) as the dedup key.
--   In production this lets the same company slip in 2-3 times per date,
--   because NSE returns "Reliance Industries Limited" while BSE returns
--   "Reliance Industries Ltd." — two different strings, no conflict.
--   The dashboard then shows inflated counts (e.g. ~1,983 "results this week"
--   when the real number is closer to 400).
--
-- What this migration does:
--   1. Adds a canonical name_norm TEXT column to earnings_calendar.
--   2. Back-fills name_norm for existing rows.
--   3. Replaces the old UNIQUE constraint with UNIQUE (result_date, name_norm).
--   4. Mirrors the column on historical_snapshots (no unique constraint there —
--      snapshots are append-only).
--   5. Adds helpful indexes for the dashboard hot path.
--
-- Idempotent: uses IF NOT EXISTS / DO blocks so re-running is safe.
-- =============================================================================

-- ── 1. Add name_norm column to earnings_calendar ──────────────────────────────
ALTER TABLE earnings_calendar
    ADD COLUMN IF NOT EXISTS name_norm TEXT;

-- ── 2. Back-fill existing rows ────────────────────────────────────────────────
-- Strip common corporate suffixes and punctuation, collapse whitespace.
UPDATE earnings_calendar
SET name_norm = TRIM(REGEXP_REPLACE(
        REGEXP_REPLACE(
            UPPER(company_name),
            '\.|,|&|/|\(|\)|''|"',
            ' ',
            'g'
        ),
        '\s+(LIMITED|LTD|PRIVATE|PVT|CORPORATION|CORP|COMPANY|CO|INC|PLC|AG|SE|SA|NV|GMBH)\.?\s*$|\s+',
        ' ',
        'g'
    ))
WHERE name_norm IS NULL OR name_norm = '';

-- For any rows that ended up empty after normalization, fall back to upper(company_name).
UPDATE earnings_calendar
SET name_norm = UPPER(company_name)
WHERE name_norm IS NULL OR TRIM(name_norm) = '';

-- Final defensive sweep — anything still empty becomes a synthetic placeholder
-- keyed on id, which guarantees uniqueness for the new constraint.
UPDATE earnings_calendar
SET name_norm = 'UNKNOWN_' || id::text
WHERE name_norm IS NULL OR TRIM(name_norm) = '';

-- ── 3. Collapse duplicates created by the old constraint ──────────────────────
-- Keep the row with the highest importance_score (or lowest id as tiebreak).
WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY result_date, name_norm
               ORDER BY importance_score DESC NULLS LAST, id ASC
           ) AS rn
    FROM earnings_calendar
)
DELETE FROM earnings_calendar
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

-- ── 4. Swap the unique constraint ─────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'earnings_calendar'::regclass
          AND conname  = 'earnings_calendar_result_date_company_name_key'
    ) THEN
        ALTER TABLE earnings_calendar
            DROP CONSTRAINT earnings_calendar_result_date_company_name_key;
    END IF;
END $$;

ALTER TABLE earnings_calendar
    ALTER COLUMN name_norm SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'earnings_calendar'::regclass
          AND conname  = 'earnings_calendar_result_date_name_norm_key'
    ) THEN
        ALTER TABLE earnings_calendar
            ADD CONSTRAINT earnings_calendar_result_date_name_norm_key
            UNIQUE (result_date, name_norm);
    END IF;
END $$;

-- ── 5. Mirror column on historical_snapshots (no unique — append-only) ────────
ALTER TABLE historical_snapshots
    ADD COLUMN IF NOT EXISTS name_norm TEXT;

UPDATE historical_snapshots
SET name_norm = UPPER(company_name)
WHERE name_norm IS NULL;

-- ── 6. Dashboard hot-path indexes ─────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_earnings_calendar_result_date
    ON earnings_calendar (result_date);

CREATE INDEX IF NOT EXISTS idx_earnings_calendar_is_fo
    ON earnings_calendar (is_fo)
    WHERE is_fo = TRUE;

CREATE INDEX IF NOT EXISTS idx_earnings_calendar_importance
    ON earnings_calendar (importance_score DESC);

-- =============================================================================
-- Done. Verify with:
--   \d earnings_calendar
--   SELECT COUNT(*), COUNT(DISTINCT (result_date, name_norm)) FROM earnings_calendar;
-- The two counts should now match.
-- =============================================================================
