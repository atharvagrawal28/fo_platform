"""
pipeline/classify_buildup.py
-----------------------------
Buildup classification engine — the intelligence core of the OI layer.

Standard derivatives positioning matrix:
  ┌─────────────┬──────────────┬──────────────┐
  │             │   OI ↑       │   OI ↓       │
  ├─────────────┼──────────────┼──────────────┤
  │  Price ↑   │ Long Buildup │Short Covering│
  │  Price ↓   │Short Buildup │Long Unwinding│
  └─────────────┴──────────────┴──────────────┘

Configurable thresholds filter out noise — only moves exceeding
OI_PRICE_THRESHOLD_PCT AND OI_CHANGE_THRESHOLD_PCT are classified.
All others remain "Neutral".
"""

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from configs.settings import (
    BANKNIFTY_CSV,
    DATA_DIR,
    FO_UNIVERSE_CSV,
    NIFTY50_CSV,
    NIFTY_NEXT50_CSV,
    OI_CHANGE_THRESHOLD_PCT,
    OI_PRICE_THRESHOLD_PCT,
    OI_STRONG_OI_PCT,
    OI_STRONG_PRICE_PCT,
    SECTOR_MAP_CSV,
)

logger = logging.getLogger(__name__)

# Visual identity for each buildup type — used across charts and tables
BUILDUP_META = {
    "Long Buildup":   {"color": "#00C896", "icon": "▲", "desc": "Bulls adding positions"},
    "Short Buildup":  {"color": "#FF6B6B", "icon": "▼", "desc": "Bears adding positions"},
    "Short Covering": {"color": "#FFB347", "icon": "↑", "desc": "Shorts exiting"},
    "Long Unwinding": {"color": "#8B8FA8", "icon": "↓", "desc": "Longs exiting"},
    "Neutral":        {"color": "#3A3D56", "icon": "—", "desc": "Below noise threshold"},
}


def classify_and_enrich(df: pd.DataFrame) -> pd.DataFrame:
    """
    Full enrichment pipeline: classify buildup + add sector/index/earnings context.

    Input:  raw OI DataFrame from fetch_oi.fetch_oi_data()
    Output: enriched DataFrame ready for storage and display
    """
    if df.empty:
        return df

    # 1. Classify
    df["buildup_type"]     = df.apply(
        lambda r: _classify(r["price_chg_pct"], r["oi_chg_pct"]), axis=1
    )
    df["buildup_strength"] = df.apply(
        lambda r: _strength(r["price_chg_pct"], r["oi_chg_pct"]), axis=1
    )

    # 2. Enrich with sector, index membership, company name
    df = _enrich_reference(df)

    # 3. Flag earnings this week
    df = _add_earnings_context(df)

    counts = df["buildup_type"].value_counts().to_dict()
    logger.info(
        "Buildup | LongBuild=%d ShortBuild=%d ShortCov=%d LongUnwind=%d Neutral=%d",
        counts.get("Long Buildup",   0),
        counts.get("Short Buildup",  0),
        counts.get("Short Covering", 0),
        counts.get("Long Unwinding", 0),
        counts.get("Neutral",        0),
    )
    return df


# ── Classification ────────────────────────────────────────────────────────────
def _classify(price_chg: float, oi_chg: float) -> str:
    p = float(price_chg) if price_chg is not None else 0.0
    o = float(oi_chg)    if oi_chg    is not None else 0.0

    if abs(p) < OI_PRICE_THRESHOLD_PCT or abs(o) < OI_CHANGE_THRESHOLD_PCT:
        return "Neutral"

    if p > 0 and o > 0: return "Long Buildup"
    if p < 0 and o > 0: return "Short Buildup"
    if p > 0 and o < 0: return "Short Covering"
    if p < 0 and o < 0: return "Long Unwinding"
    return "Neutral"


def _strength(price_chg: float, oi_chg: float) -> str:
    p = abs(float(price_chg) if price_chg is not None else 0.0)
    o = abs(float(oi_chg)    if oi_chg    is not None else 0.0)

    if p >= OI_STRONG_PRICE_PCT and o >= OI_STRONG_OI_PCT:
        return "Strong"
    if abs(float(price_chg or 0)) >= OI_PRICE_THRESHOLD_PCT and \
       abs(float(oi_chg    or 0)) >= OI_CHANGE_THRESHOLD_PCT:
        return "Moderate"
    return "Weak"


# ── Reference enrichment ──────────────────────────────────────────────────────
def _enrich_reference(df: pd.DataFrame) -> pd.DataFrame:
    universe   = _read_csv(FO_UNIVERSE_CSV)
    sector_map = _read_csv(SECTOR_MAP_CSV)
    nifty50    = _symbol_set(NIFTY50_CSV)
    banknifty  = _symbol_set(BANKNIFTY_CSV)
    next50     = _symbol_set(NIFTY_NEXT50_CSV)

    # Build per-symbol lookup dicts
    name_lkp   = {}
    sector_lkp = {}
    tier_lkp   = {}

    if not universe.empty:
        universe["symbol"] = universe["symbol"].astype(str).str.upper().str.strip()
        for _, r in universe.iterrows():
            s = r["symbol"]
            name_lkp[s]   = r.get("company_name_hint", s) or s
            sector_lkp[s] = r.get("sector", "")  or ""
            tier_lkp[s]   = r.get("market_cap_tier", "") or ""

    if not sector_map.empty:
        sector_map["symbol"] = sector_map["symbol"].astype(str).str.upper().str.strip()
        for _, r in sector_map.iterrows():
            s = r["symbol"]
            sector_lkp[s] = r.get("sector", sector_lkp.get(s, "")) or sector_lkp.get(s, "")

    df["company_name"]    = df["symbol"].map(lambda s: name_lkp.get(s, s))
    df["sector"]          = df["symbol"].map(lambda s: sector_lkp.get(s, ""))
    df["market_cap_tier"] = df["symbol"].map(lambda s: tier_lkp.get(s, ""))
    df["is_nifty50"]      = df["symbol"].isin(nifty50)
    df["is_banknifty"]    = df["symbol"].isin(banknifty)
    df["is_nifty_next50"] = df["symbol"].isin(next50)
    return df


def _add_earnings_context(df: pd.DataFrame) -> pd.DataFrame:
    df["has_earnings_this_week"] = False
    df["earnings_date"]          = ""
    df["days_to_earnings"]       = None

    cal_path = DATA_DIR / "earnings_calendar.csv"
    if not cal_path.exists():
        return df

    try:
        cal = pd.read_csv(cal_path, dtype=str)
        cal["result_date"] = pd.to_datetime(cal["result_date"], errors="coerce")
        today    = pd.Timestamp(date.today())
        week_end = today + pd.Timedelta(days=7)
        upcoming = cal[(cal["result_date"] >= today) & (cal["result_date"] <= week_end)]

        if upcoming.empty:
            return df

        sym_to_date: dict = (
            upcoming.groupby("symbol")["result_date"].min().to_dict()
        )

        def _flag(row):
            ed = sym_to_date.get(row["symbol"])
            if ed:
                return True, ed.strftime("%Y-%m-%d"), int((ed - today).days)
            return False, "", None

        res = df.apply(_flag, axis=1, result_type="expand")
        df["has_earnings_this_week"] = res[0]
        df["earnings_date"]          = res[1]
        df["days_to_earnings"]       = res[2]
    except Exception as e:
        logger.warning("Earnings context failed: %s", e)

    return df


# ── Helpers ───────────────────────────────────────────────────────────────────
def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _symbol_set(path: Path) -> set:
    if not path.exists():
        return set()
    try:
        return set(
            pd.read_csv(path)["symbol"].astype(str).str.upper().str.strip()
        )
    except Exception:
        return set()
