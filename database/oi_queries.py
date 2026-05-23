"""
database/oi_queries.py
-----------------------
Data-access layer for OI / derivatives positioning data.
All backed by CSV files — no database required.

Functions mirror the SQL-style interface used in database/queries.py
so the dashboard layer stays consistent.
"""

import logging
from datetime import date

import pandas as pd

from configs.settings import OI_HISTORY_CSV, OI_SNAPSHOT_CSV

logger = logging.getLogger(__name__)

_BOOL_MAP = {"True": True, "False": False, "true": True, "false": False}
_NUM_COLS = [
    "futures_price", "prev_price", "price_chg_pct",
    "open_interest", "oi_change", "oi_chg_pct",
    "volume_contracts", "days_to_earnings",
]
_BOOL_COLS = ["is_nifty50", "is_banknifty", "is_nifty_next50", "has_earnings_this_week"]


# ── Public API ────────────────────────────────────────────────────────────────
def get_oi_snapshot() -> pd.DataFrame:
    """Latest OI snapshot — one row per F&O stock."""
    return _load(OI_SNAPSHOT_CSV)


def get_oi_history(days: int = 30) -> pd.DataFrame:
    """OI history for the last N calendar days."""
    df = _load(OI_HISTORY_CSV)
    if df.empty:
        return df
    cutoff = pd.Timestamp(date.today()) - pd.Timedelta(days=days)
    return df[df["snapshot_date"] >= cutoff].reset_index(drop=True)


def get_buildup_summary() -> dict:
    """Aggregated buildup counts for the KPI cards row."""
    df = get_oi_snapshot()
    if df.empty:
        return _empty_summary()

    bt = df["buildup_type"].value_counts().to_dict()
    strong = df[df.get("buildup_strength", pd.Series(dtype=str)) == "Strong"] \
             if "buildup_strength" in df.columns else df.iloc[0:0]

    earnings_col = df["has_earnings_this_week"] if "has_earnings_this_week" in df.columns \
                   else pd.Series(False, index=df.index)

    return {
        "long_buildup":         bt.get("Long Buildup",   0),
        "short_buildup":        bt.get("Short Buildup",  0),
        "short_covering":       bt.get("Short Covering", 0),
        "long_unwinding":       bt.get("Long Unwinding", 0),
        "neutral":              bt.get("Neutral",        0),
        "total":                len(df),
        "strong_signals":       len(strong),
        "earnings_week_count":  int(earnings_col.astype(bool).sum()),
        "snapshot_date":        str(df["snapshot_date"].iloc[0]) if "snapshot_date" in df.columns else "",
    }


def get_sector_buildup() -> pd.DataFrame:
    """
    Sector × buildup-type pivot — for the sector heatmap and summary table.
    Returns one row per sector with columns for each buildup type.
    """
    df = get_oi_snapshot()
    if df.empty or "sector" not in df.columns:
        return pd.DataFrame()

    active = df[
        df["sector"].astype(str).str.strip().ne("") &
        df["buildup_type"].ne("Neutral")
    ]
    if active.empty:
        return pd.DataFrame()

    pivot = (
        active
        .groupby(["sector", "buildup_type"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    for col in ["Long Buildup", "Short Buildup", "Short Covering", "Long Unwinding"]:
        if col not in pivot.columns:
            pivot[col] = 0
    pivot["total"] = (
        pivot["Long Buildup"] + pivot["Short Buildup"] +
        pivot["Short Covering"] + pivot["Long Unwinding"]
    )
    return pivot.sort_values("total", ascending=False).reset_index(drop=True)


def get_strongest_signals(n: int = 20) -> pd.DataFrame:
    """Top N positioning shifts ranked by absolute OI change %."""
    df = get_oi_snapshot()
    if df.empty:
        return df
    active = df[df["buildup_type"] != "Neutral"].copy()
    if active.empty:
        return active
    active["_abs_oi"] = active["oi_chg_pct"].abs()
    return (
        active
        .sort_values("_abs_oi", ascending=False)
        .drop(columns=["_abs_oi"])
        .head(n)
        .reset_index(drop=True)
    )


def get_earnings_oi_context() -> pd.DataFrame:
    """
    F&O stocks reporting results in the next 7 days + their current positioning.
    The core EVENT + POSITIONING intelligence view.
    """
    df = get_oi_snapshot()
    if df.empty or "has_earnings_this_week" not in df.columns:
        return pd.DataFrame()
    mask = df["has_earnings_this_week"].astype(bool)
    return (
        df[mask]
        .sort_values("days_to_earnings")
        .reset_index(drop=True)
    )


def get_oi_trend(symbol: str, days: int = 20) -> pd.DataFrame:
    """Historical OI trend for a single symbol — foundation for future analytics."""
    df = get_oi_history(days=days)
    if df.empty or "symbol" not in df.columns:
        return pd.DataFrame()
    return (
        df[df["symbol"].str.upper() == symbol.upper()]
        .sort_values("snapshot_date")
        .reset_index(drop=True)
    )


# ── Internal ──────────────────────────────────────────────────────────────────
def _load(path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, dtype=str)
        for col in _NUM_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        for col in _BOOL_COLS:
            if col in df.columns:
                df[col] = df[col].map(_BOOL_MAP).fillna(False)
        if "snapshot_date" in df.columns:
            df["snapshot_date"] = pd.to_datetime(df["snapshot_date"], errors="coerce")
        return df
    except Exception as e:
        logger.error("Could not load OI CSV %s: %s", path, e)
        return pd.DataFrame()


def _empty_summary() -> dict:
    return {
        "long_buildup": 0, "short_buildup": 0,
        "short_covering": 0, "long_unwinding": 0,
        "neutral": 0, "total": 0, "strong_signals": 0,
        "earnings_week_count": 0, "snapshot_date": "",
    }
