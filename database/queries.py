"""
database/queries.py
-------------------
All data-access functions used by the Streamlit dashboard.

Previously backed by PostgreSQL — now backed by CSV files committed to GitHub.
All SQL has been replaced with equivalent pandas operations.

Rules:
  - Every function returns a pandas DataFrame or dict (never None)
  - All functions accept the same signatures as before for zero-change callers
  - `conn` parameter is accepted but ignored (kept for signature compatibility)
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from configs.settings import DATA_DIR

logger = logging.getLogger(__name__)

CALENDAR_CSV = DATA_DIR / "earnings_calendar.csv"
PIPELINE_LOG = DATA_DIR / "pipeline_log.json"


# ── Internal data loader (cached at module level within a request) ─────────────
def _load_calendar() -> pd.DataFrame:
    """Load earnings_calendar.csv. Returns empty DataFrame if missing."""
    if not CALENDAR_CSV.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(CALENDAR_CSV, dtype=str)
        # Type-cast critical columns
        df["result_date"] = pd.to_datetime(df["result_date"], errors="coerce")
        df = df.dropna(subset=["result_date"])
        df["importance_score"] = pd.to_numeric(
            df.get("importance_score", 0), errors="coerce"
        ).fillna(0).astype(int)
        bool_map = {"True": True, "False": False, "true": True, "false": False}
        for col in ["is_fo", "is_nifty50", "is_nifty_next50", "is_banknifty"]:
            if col in df.columns:
                df[col] = df[col].map(bool_map).fillna(False)
            else:
                df[col] = False
        return df
    except Exception as e:
        logger.error("Could not load earnings_calendar.csv: %s", e)
        return pd.DataFrame()


def _load_logs() -> list:
    """Load pipeline_log.json. Returns empty list if missing."""
    if not PIPELINE_LOG.exists():
        return []
    try:
        return json.loads(PIPELINE_LOG.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Could not load pipeline_log.json: %s", e)
        return []


def _window(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Return rows where result_date is between today and today + days."""
    today     = pd.Timestamp(date.today())
    end_date  = today + pd.Timedelta(days=days)
    return df[(df["result_date"] >= today) & (df["result_date"] <= end_date)]


# ── Core results query ────────────────────────────────────────────────────────
def get_upcoming_results(conn=None, days: int = 7) -> pd.DataFrame:
    """Fetch all results scheduled between today and today + days."""
    df = _load_calendar()
    if df.empty:
        return df

    df = _window(df, days)
    df = df.sort_values(
        ["result_date", "importance_score", "company_name"],
        ascending=[True, False, True],
    ).reset_index(drop=True)

    today = pd.Timestamp(date.today())
    df["days_remaining"] = (df["result_date"] - today).dt.days

    return df


# ── KPI numbers ───────────────────────────────────────────────────────────────
def get_kpis(conn=None, days: int = 7) -> dict:
    """Return distinct, meaningful KPI buckets — pure pandas implementation."""
    df = _load_calendar()
    if df.empty:
        return _empty_kpis(days)

    today    = pd.Timestamp(date.today())
    tomorrow = today + pd.Timedelta(days=1)
    week_end = today + pd.Timedelta(days=6)
    next_week_start = today + pd.Timedelta(days=7)
    next_week_end   = today + pd.Timedelta(days=13)

    window    = _window(df, days)
    this_week = df[(df["result_date"] >= today) & (df["result_date"] <= week_end)]
    next_week = df[(df["result_date"] >= next_week_start) & (df["result_date"] <= next_week_end)]

    total          = len(window)
    fo_count       = int(window["is_fo"].sum())
    nifty50_count  = int(window["is_nifty50"].sum())
    banknifty_count = int(window["is_banknifty"].sum())
    today_count    = int((window["result_date"] == today).sum())
    tomorrow_count = int((window["result_date"] == tomorrow).sum())
    week_count     = len(this_week)
    next_week_count = len(next_week)
    fo_week_count  = int(this_week["is_fo"].sum())
    nifty50_week_count = int(this_week["is_nifty50"].sum())
    fo_pct = round(100.0 * fo_count / total, 1) if total else 0.0

    return {
        "total":             total,
        "fo_count":          fo_count,
        "nifty50_count":     nifty50_count,
        "banknifty_count":   banknifty_count,
        "today_count":       today_count,
        "tomorrow_count":    tomorrow_count,
        "week_count":        week_count,
        "next_week_count":   next_week_count,
        "fo_week_count":     fo_week_count,
        "nifty50_week_count": nifty50_week_count,
        "fo_pct":            fo_pct,
        "lookahead_days":    int(days),
    }


# ── Top earnings this week (by importance score) ──────────────────────────────
def get_top_earnings(conn=None, days: int = 7, limit: int = 10) -> pd.DataFrame:
    """High-impact companies reporting in the next N days."""
    df = _load_calendar()
    if df.empty:
        return df

    df = _window(df, days)
    df = df[df["importance_score"] > 0]
    df = df.sort_values(["importance_score", "result_date"], ascending=[False, True])
    return df.head(limit).reset_index(drop=True)


# ── Sector concentration ──────────────────────────────────────────────────────
def get_sector_concentration(conn=None, days: int = 7) -> pd.DataFrame:
    """Count upcoming results per sector."""
    df = _load_calendar()
    if df.empty:
        return pd.DataFrame()

    df = _window(df, days)
    df = df[df["sector"].notna() & (df["sector"].astype(str).str.strip() != "")]

    if df.empty:
        return pd.DataFrame()

    grouped = (
        df.groupby("sector", as_index=False)
        .agg(
            total_count=("sector", "count"),
            fo_count=("is_fo", "sum"),
            max_importance=("importance_score", "max"),
        )
        .sort_values("total_count", ascending=False)
    )
    grouped["fo_count"] = grouped["fo_count"].astype(int)
    grouped["max_importance"] = grouped["max_importance"].astype(int)
    return grouped.reset_index(drop=True)


def get_sector_options(conn=None) -> pd.DataFrame:
    """All known sectors from the calendar CSV."""
    df = _load_calendar()
    if df.empty:
        return pd.DataFrame(columns=["sector"])
    sectors = (
        df["sector"]
        .dropna()
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .unique()
    )
    return pd.DataFrame({"sector": sorted(sectors)})


# ── Daily distribution ────────────────────────────────────────────────────────
def get_daily_distribution(conn=None, days: int = 7) -> pd.DataFrame:
    """Results count per day — for bar/timeline charts."""
    df = _load_calendar()
    if df.empty:
        return pd.DataFrame()

    df = _window(df, days)
    if df.empty:
        return pd.DataFrame()

    grouped = (
        df.groupby("result_date", as_index=False)
        .agg(
            total_count=("result_date", "count"),
            fo_count=("is_fo", "sum"),
        )
    )
    grouped["non_fo_count"] = grouped["total_count"] - grouped["fo_count"].astype(int)
    grouped["fo_count"]     = grouped["fo_count"].astype(int)
    grouped["day_label"]    = grouped["result_date"].dt.strftime("%d %b (%a)")
    return grouped.sort_values("result_date").reset_index(drop=True)


# ── Pipeline health ───────────────────────────────────────────────────────────
def get_pipeline_health(conn=None, limit: int = 10) -> pd.DataFrame:
    """Last N pipeline execution logs for the health panel."""
    logs = _load_logs()
    if not logs:
        return pd.DataFrame()
    df = pd.DataFrame(logs[:limit])
    if "started_at" in df.columns:
        df["started_at"] = pd.to_datetime(df["started_at"], errors="coerce")
    return df


def get_last_pipeline_run(conn=None) -> dict:
    """Return the most recent successful pipeline run summary."""
    logs = _load_logs()
    for entry in logs:
        if entry.get("status") in ("success", "partial"):
            return entry
    # If no success, return the most recent run regardless of status
    return logs[0] if logs else {}


# ── Analytics cache (stub — computed inline from CSV) ─────────────────────────
def get_cached_analytics(conn=None, key: str = "") -> dict:
    """Placeholder — analytics are computed live from CSV, no cache table needed."""
    return {}


# ── Internal ──────────────────────────────────────────────────────────────────
def _empty_kpis(days: int = 7) -> dict:
    return {
        "total": 0, "fo_count": 0, "nifty50_count": 0, "banknifty_count": 0,
        "today_count": 0, "tomorrow_count": 0,
        "week_count": 0, "next_week_count": 0,
        "fo_week_count": 0, "nifty50_week_count": 0,
        "fo_pct": 0.0, "lookahead_days": int(days),
    }
