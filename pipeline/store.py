"""
pipeline/store.py
-----------------
Writes enriched data to PostgreSQL.

Fix: datetime.utcnow() replaced with datetime.now(timezone.utc)
     throughout — eliminates DeprecationWarning on Python 3.12+.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import pandas as pd
import psycopg2.extras

from database.connection import pipeline_cursor
from pipeline.validate import canonical_name

logger = logging.getLogger(__name__)


# ── Public entry point ────────────────────────────────────────────────────────
def store_results(
    df: pd.DataFrame,
    run_id: str,
    metadata: dict,
    database_url: str,
) -> dict:
    if df.empty:
        logger.warning("store_results called with empty DataFrame — skipping")
        return {"rows_stored": 0, "snapshot_rows": 0}

    source  = metadata.get("source", "")
    stored  = _upsert_earnings_calendar(df, database_url)
    snapped = _insert_historical_snapshot(df, run_id, database_url)
    pruned  = _prune_stale_rows(database_url, current_source=source)
    _refresh_analytics_cache(database_url)

    logger.info(
        "Store complete | upserted=%d snapshot=%d pruned=%d",
        stored, snapped, pruned,
    )
    return {"rows_stored": stored, "snapshot_rows": snapped, "pruned": pruned}


# ── 1. Upsert earnings_calendar ───────────────────────────────────────────────
def _upsert_earnings_calendar(df: pd.DataFrame, database_url: str) -> int:
    sql = """
        INSERT INTO earnings_calendar (
            result_date, company_name, name_norm, symbol, meeting_type, source,
            sector, is_fo, is_nifty50, is_nifty_next50, is_banknifty,
            market_cap_tier, importance_score, fetched_at, updated_at
        ) VALUES %s
        ON CONFLICT (result_date, name_norm)
        DO UPDATE SET
            company_name     = EXCLUDED.company_name,
            symbol           = EXCLUDED.symbol,
            meeting_type     = EXCLUDED.meeting_type,
            source           = EXCLUDED.source,
            sector           = EXCLUDED.sector,
            is_fo            = EXCLUDED.is_fo,
            is_nifty50       = EXCLUDED.is_nifty50,
            is_nifty_next50  = EXCLUDED.is_nifty_next50,
            is_banknifty     = EXCLUDED.is_banknifty,
            market_cap_tier  = EXCLUDED.market_cap_tier,
            importance_score = EXCLUDED.importance_score,
            updated_at       = NOW()
    """
    now = datetime.now(timezone.utc)              # Fix: was datetime.utcnow()

    rows = []
    for _, row in df.iterrows():
        company_name = str(row.get("company_name", ""))[:500]
        # validate.py adds name_norm; recompute defensively if missing.
        name_norm = (row.get("name_norm") or canonical_name(company_name))[:500]
        if not name_norm:
            continue
        rows.append((
            _to_date(row.get("result_date")),
            company_name,
            name_norm,
            str(row.get("symbol", ""))[:50] or None,
            str(row.get("meeting_type", "Quarterly Results"))[:200],
            str(row.get("source", ""))[:50],
            str(row.get("sector", ""))[:100] if row.get("sector") else None,
            bool(row.get("is_fo", False)),
            bool(row.get("is_nifty50", False)),
            bool(row.get("is_nifty_next50", False)),
            bool(row.get("is_banknifty", False)),
            str(row.get("market_cap_tier", ""))[:20] if row.get("market_cap_tier") else None,
            int(row.get("importance_score", 0)),
            now, now,
        ))

    with pipeline_cursor(database_url) as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=100)
        return len(rows)


# ── 2. Historical snapshots ───────────────────────────────────────────────────
def _insert_historical_snapshot(df: pd.DataFrame, run_id: str, database_url: str) -> int:
    sql = """
        INSERT INTO historical_snapshots (
            pipeline_run_id, result_date, company_name, name_norm, symbol,
            meeting_type, source, sector, is_fo, importance_score
        ) VALUES %s
    """
    rows = []
    for _, row in df.iterrows():
        company_name = str(row.get("company_name", ""))[:500]
        name_norm = (row.get("name_norm") or canonical_name(company_name))[:500]
        rows.append((
            run_id,
            _to_date(row.get("result_date")),
            company_name,
            name_norm,
            str(row.get("symbol", ""))[:50] or None,
            str(row.get("meeting_type", ""))[:200],
            str(row.get("source", ""))[:50],
            str(row.get("sector", ""))[:100] if row.get("sector") else None,
            bool(row.get("is_fo", False)),
            int(row.get("importance_score", 0)),
        ))

    with pipeline_cursor(database_url) as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=100)
        return len(rows)


# ── 3. Analytics cache ────────────────────────────────────────────────────────
def _refresh_analytics_cache(database_url: str) -> None:
    sql_sector = """
        SELECT
            COALESCE(sector, 'Unclassified') AS sector,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE is_fo) AS fo_count
        FROM earnings_calendar
        WHERE result_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
        GROUP BY sector
        ORDER BY total DESC
    """
    sql_busiest = """
        SELECT result_date, COUNT(*) AS count
        FROM earnings_calendar
        WHERE result_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
        GROUP BY result_date
        ORDER BY count DESC
        LIMIT 1
    """

    with pipeline_cursor(database_url) as cur:
        cur.execute(sql_sector)
        sector_rows = [dict(r) for r in cur.fetchall()]

        cur.execute(sql_busiest)
        busiest_rows = cur.fetchall()
        busiest = dict(busiest_rows[0]) if busiest_rows else {}
        if "result_date" in busiest and busiest["result_date"]:
            busiest["result_date"] = str(busiest["result_date"])

        now_str = datetime.now(timezone.utc).isoformat()   # Fix: was utcnow()

        _upsert_cache(cur, "sector_concentration", sector_rows, now_str)
        _upsert_cache(cur, "busiest_day", busiest, now_str)

    logger.info("Analytics cache refreshed")


def _upsert_cache(cur, key: str, value, computed_at: str):
    cur.execute(
        """
        INSERT INTO analytics_cache (cache_key, cache_value, computed_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (cache_key) DO UPDATE
        SET cache_value = EXCLUDED.cache_value,
            computed_at = EXCLUDED.computed_at
        """,
        (key, json.dumps(value), computed_at),
    )


# ── 4. Prune stale rows ───────────────────────────────────────────────────────
def _prune_stale_rows(database_url: str, current_source: str = "") -> int:
    """
    Remove rows that are no longer useful so the dashboard counts stay correct.

    Two classes of stale data are removed:

    1. Past-dated rows (result_date < yesterday) — results that have already
       been announced accumulate indefinitely because the upsert never deletes.
       We keep yesterday to avoid dropping rows from a late-evening run.

    2. BSE-sourced rows when the current run used NSE — the BSE fallback
       stores thousands of SME companies that inflate "All Companies This Week"
       without adding analytical value. When NSE succeeds we don't need them.
       Historical snapshots are kept (append-only by design); only the live
       earnings_calendar table is pruned.
    """
    total_pruned = 0

    with pipeline_cursor(database_url) as cur:
        # ── Rule 1: remove results from the past ──────────────────────────────
        cur.execute(
            """
            DELETE FROM earnings_calendar
            WHERE result_date < CURRENT_DATE - INTERVAL '1 day'
            """,
        )
        past_pruned = cur.rowcount
        total_pruned += past_pruned
        if past_pruned:
            logger.info("Pruned %d past-dated rows from earnings_calendar", past_pruned)

        # ── Rule 2: remove BSE rows when NSE was the authoritative source ─────
        if "nse" in str(current_source).lower():
            cur.execute(
                """
                DELETE FROM earnings_calendar
                WHERE source = 'bse_official_file'
                """,
            )
            bse_pruned = cur.rowcount
            total_pruned += bse_pruned
            if bse_pruned:
                logger.info(
                    "Pruned %d stale BSE rows (NSE is authoritative source this run)",
                    bse_pruned,
                )

    return total_pruned


# ── Pipeline log writers ──────────────────────────────────────────────────────
def log_pipeline_start(run_id: str, database_url: str) -> None:
    with pipeline_cursor(database_url) as cur:
        cur.execute(
            """
            INSERT INTO pipeline_logs (run_id, started_at, status)
            VALUES (%s, NOW(), 'running')
            ON CONFLICT (run_id) DO NOTHING
            """,
            (run_id,),
        )


def log_pipeline_complete(
    run_id: str,
    database_url: str,
    source: str,
    rows_fetched: int,
    rows_valid: int,
    rows_stored: int,
    validation_passed: bool,
    fallback_used: bool,
    duration_s: float,
    status: str,
    error: str = "",
) -> None:
    with pipeline_cursor(database_url) as cur:
        cur.execute(
            """
            UPDATE pipeline_logs SET
                completed_at      = NOW(),
                source_used       = %s,
                rows_fetched      = %s,
                rows_valid        = %s,
                rows_stored       = %s,
                validation_passed = %s,
                fallback_used     = %s,
                duration_seconds  = %s,
                status            = %s,
                error_message     = %s
            WHERE run_id = %s
            """,
            (
                source, rows_fetched, rows_valid, rows_stored,
                validation_passed, fallback_used, duration_s,
                status, error or None, run_id,
            ),
        )


# ── Utilities ─────────────────────────────────────────────────────────────────
def _to_date(val):
    if isinstance(val, pd.Timestamp):
        return val.date()
    if isinstance(val, datetime):
        return val.date()
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None


def generate_run_id() -> str:
    return (
        f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"  # Fix
        f"_{uuid.uuid4().hex[:6]}"
    )
