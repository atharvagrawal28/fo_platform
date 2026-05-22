"""
database/queries.py
-------------------
All SELECT queries used by the Streamlit dashboard.

Rules:
  - Every function returns a pandas DataFrame (empty DF on no data, never None)
  - No heavy computation here — just reads
  - All expensive analytics come from analytics_cache table
  - Handle empty tables gracefully (first-run state)
"""

import json
import logging

import pandas as pd

from database.connection import run_query_df

logger = logging.getLogger(__name__)


# ── Core results query ────────────────────────────────────────────────────────
def get_upcoming_results(conn, days: int = 7) -> pd.DataFrame:
    """
    Fetch all results scheduled between today and today + `days`.

    Returns one row per (date, canonical company). The DB now enforces this
    via UNIQUE (result_date, name_norm); see migration 002.

    `days` defaults to 7 but the dashboard passes settings.LOOKAHEAD_DAYS so
    the window is configurable in one place.
    """
    sql = """
        SELECT
            result_date,
            company_name,
            symbol,
            meeting_type,
            sector,
            is_fo,
            is_nifty50,
            is_nifty_next50,
            is_banknifty,
            market_cap_tier,
            importance_score,
            source,
            updated_at
        FROM earnings_calendar
        WHERE result_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '%s days'
        ORDER BY result_date ASC, importance_score DESC, company_name ASC
    """ % int(days)

    df = run_query_df(conn, sql)

    if df.empty:
        return df

    # Compute days_remaining for display
    df["result_date"] = pd.to_datetime(df["result_date"])
    today = pd.Timestamp("today").normalize()
    df["days_remaining"] = (df["result_date"] - today).dt.days

    return df


# ── KPI numbers ───────────────────────────────────────────────────────────────
def get_kpis(conn, days: int = 7) -> dict:
    """
    Return distinct, meaningful KPI buckets.

    - today_count    : results due today
    - tomorrow_count : results due exactly tomorrow
    - week_count     : results between today and today + 6 days (rolling 7-day)
    - next_week_count: results between today+7 and today+13 (rolling next 7)
    - total          : results across the dashboard's full lookahead window
    - fo_count       : F&O subset of total
    - nifty50_count  : Nifty 50 subset of total
    - fo_pct         : F&O share of total

    The previous implementation made `total` and `week_count` identical (both
    used a 7-day filter), which made the KPI row misleading — e.g. it showed
    "1,983 Total" and "1,983 This Week" simultaneously. Each bucket below uses
    a strict, non-overlapping definition tied to its label.
    """
    sql = """
        WITH window_rows AS (
            SELECT *
            FROM earnings_calendar
            WHERE result_date BETWEEN CURRENT_DATE
                                 AND  CURRENT_DATE + INTERVAL '%s days'
        )
        SELECT
            COUNT(*)                                                          AS total,
            COUNT(*) FILTER (WHERE is_fo)                                     AS fo_count,
            COUNT(*) FILTER (WHERE is_nifty50)                                AS nifty50_count,
            COUNT(*) FILTER (WHERE is_banknifty)                              AS banknifty_count,
            COUNT(*) FILTER (WHERE result_date = CURRENT_DATE)                AS today_count,
            COUNT(*) FILTER (WHERE result_date = CURRENT_DATE + INTERVAL '1 day') AS tomorrow_count,
            COUNT(*) FILTER (
                WHERE result_date BETWEEN CURRENT_DATE
                                     AND  CURRENT_DATE + INTERVAL '6 days'
            )                                                                 AS week_count,
            COUNT(*) FILTER (
                WHERE result_date BETWEEN CURRENT_DATE + INTERVAL '7 days'
                                     AND  CURRENT_DATE + INTERVAL '13 days'
            )                                                                 AS next_week_count,
            COUNT(*) FILTER (
                WHERE is_fo
                  AND result_date BETWEEN CURRENT_DATE
                                     AND  CURRENT_DATE + INTERVAL '6 days'
            )                                                                 AS fo_week_count,
            COUNT(*) FILTER (
                WHERE is_nifty50
                  AND result_date BETWEEN CURRENT_DATE
                                     AND  CURRENT_DATE + INTERVAL '6 days'
            )                                                                 AS nifty50_week_count,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE is_fo)
                / NULLIF(COUNT(*), 0), 1
            )                                                                 AS fo_pct
        FROM window_rows
    """ % days

    df = run_query_df(conn, sql)

    if df.empty:
        return _empty_kpis()

    row = df.iloc[0]
    return {
        "total":            int(row.get("total", 0) or 0),
        "fo_count":         int(row.get("fo_count", 0) or 0),
        "nifty50_count":    int(row.get("nifty50_count", 0) or 0),
        "banknifty_count":  int(row.get("banknifty_count", 0) or 0),
        "today_count":      int(row.get("today_count", 0) or 0),
        "tomorrow_count":   int(row.get("tomorrow_count", 0) or 0),
        "week_count":       int(row.get("week_count", 0) or 0),
        "next_week_count":   int(row.get("next_week_count", 0) or 0),
        "fo_week_count":     int(row.get("fo_week_count", 0) or 0),
        "nifty50_week_count":int(row.get("nifty50_week_count", 0) or 0),
        "fo_pct":            float(row.get("fo_pct", 0) or 0),
        "lookahead_days":    int(days),
    }


# ── Top earnings this week (by importance score) ──────────────────────────────
def get_top_earnings(conn, days: int = 7, limit: int = 10) -> pd.DataFrame:
    """High-impact companies reporting in the next N days."""
    sql = """
        SELECT
            company_name,
            symbol,
            result_date,
            sector,
            importance_score,
            market_cap_tier,
            is_nifty50,
            is_banknifty,
            is_fo
        FROM earnings_calendar
        WHERE result_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '%s days'
          AND importance_score > 0
        ORDER BY importance_score DESC, result_date ASC
        LIMIT %s
    """ % (days, limit)

    df = run_query_df(conn, sql)
    if not df.empty:
        df["result_date"] = pd.to_datetime(df["result_date"])
    return df


# ── Sector concentration ──────────────────────────────────────────────────────
def get_sector_concentration(conn, days: int = 7) -> pd.DataFrame:
    """Count upcoming results per sector for concentration chart."""
    sql = """
        SELECT
            COALESCE(sector, 'Unclassified')         AS sector,
            COUNT(*)                                  AS total_count,
            COUNT(*) FILTER (WHERE is_fo = TRUE)      AS fo_count,
            MAX(importance_score)                     AS max_importance
        FROM earnings_calendar
        WHERE result_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '%s days'
          AND sector IS NOT NULL
        GROUP BY sector
        ORDER BY total_count DESC
    """ % days

    return run_query_df(conn, sql)


def get_sector_options(conn) -> pd.DataFrame:
    """All known sectors for dashboard filtering, independent of current results."""
    sql = """
        SELECT DISTINCT sector
        FROM (
            SELECT sector FROM sector_map WHERE sector IS NOT NULL
            UNION
            SELECT sector FROM fo_universe WHERE sector IS NOT NULL
            UNION
            SELECT sector FROM earnings_calendar WHERE sector IS NOT NULL
        ) s
        WHERE TRIM(sector) <> ''
        ORDER BY sector
    """
    return run_query_df(conn, sql)


# ── Daily distribution ────────────────────────────────────────────────────────
def get_daily_distribution(conn, days: int = 7) -> pd.DataFrame:
    """Results count per day — for bar/timeline charts."""
    sql = """
        SELECT
            result_date,
            COUNT(*)                              AS total_count,
            COUNT(*) FILTER (WHERE is_fo = TRUE)  AS fo_count,
            COUNT(*) FILTER (WHERE is_fo = FALSE) AS non_fo_count
        FROM earnings_calendar
        WHERE result_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '%s days'
        GROUP BY result_date
        ORDER BY result_date ASC
    """ % days

    df = run_query_df(conn, sql)
    if not df.empty:
        df["result_date"] = pd.to_datetime(df["result_date"])
        df["day_label"]   = df["result_date"].dt.strftime("%d %b (%a)")
    return df


# ── Pipeline health ───────────────────────────────────────────────────────────
def get_pipeline_health(conn, limit: int = 10) -> pd.DataFrame:
    """Last N pipeline execution logs for the health panel."""
    sql = """
        SELECT
            run_id,
            started_at,
            completed_at,
            source_used,
            rows_fetched,
            rows_valid,
            rows_stored,
            validation_passed,
            fallback_used,
            status,
            duration_seconds,
            error_message
        FROM pipeline_logs
        ORDER BY started_at DESC
        LIMIT %s
    """ % limit

    df = run_query_df(conn, sql)
    if not df.empty:
        df["started_at"] = pd.to_datetime(df["started_at"])
    return df


def get_last_pipeline_run(conn) -> dict:
    """Return the most recent pipeline run summary."""
    sql = """
        SELECT *
        FROM pipeline_logs
        WHERE status IN ('success', 'partial')
        ORDER BY started_at DESC
        LIMIT 1
    """
    df = run_query_df(conn, sql)
    if df.empty:
        return {}
    return dict(df.iloc[0])


# ── Analytics cache ───────────────────────────────────────────────────────────
def get_cached_analytics(conn, key: str) -> dict:
    """Retrieve a precomputed analytics value by key."""
    sql = "SELECT cache_value, computed_at FROM analytics_cache WHERE cache_key = %s"
    df = run_query_df(conn, sql, (key,))
    if df.empty:
        return {}
    try:
        val = df.iloc[0]["cache_value"]
        return val if isinstance(val, dict) else json.loads(val)
    except Exception:
        return {}


# ── Internal ──────────────────────────────────────────────────────────────────
def _empty_kpis() -> dict:
    return {
        "total": 0, "fo_count": 0, "nifty50_count": 0, "banknifty_count": 0,
        "today_count": 0, "tomorrow_count": 0,
        "week_count": 0, "next_week_count": 0,
        "fo_week_count": 0, "nifty50_week_count": 0,
        "fo_pct": 0.0, "lookahead_days": 7,
    }
