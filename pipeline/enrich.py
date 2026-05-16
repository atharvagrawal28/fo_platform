"""
pipeline/enrich.py
------------------
Adds intelligence to the raw earnings calendar:
  - F&O status
  - Sector mapping
  - Index membership
  - Importance score
"""

import logging
import re

import pandas as pd

from configs.settings import (
    SCORE_BANKNIFTY,
    SCORE_FO,
    SCORE_LARGE_CAP,
    SCORE_MID_CAP,
    SCORE_NIFTY50,
    SCORE_NIFTY_NEXT50,
    SCORE_SMALL_CAP,
)
from database.connection import run_query_df

logger = logging.getLogger(__name__)

_NOISE = re.compile(
    r"\b(LIMITED|LTD|PRIVATE|PVT|INDUSTRIES|INDUSTRY|INDIA|INDIAN|"
    r"CORPORATION|CORP|ENTERPRISES|ENTERPRISE|COMPANY|CO|GROUP|"
    r"HOLDINGS|HOLDING|SERVICES|SOLUTIONS|TECHNOLOGIES|TECHNOLOGY|"
    r"INFRASTRUCTURE|INFRA|FINANCIAL|FINANCE|BANK|BANKING|"
    r"PHARMACEUTICALS|PHARMA|AND|&)\b",
    re.IGNORECASE,
)


def enrich(df: pd.DataFrame, conn) -> pd.DataFrame:
    """
    Add sector, index/F&O flags, market-cap tier, and importance score.

    Exchange-provided symbols are treated as authoritative. This prevents
    false positives such as "Jay Bharat Maruti" being mapped to MARUTI.
    """
    if df.empty:
        return df

    universe = _load_fo_universe(conn)
    sector_ref = _load_sector_map(conn)
    if universe.empty and sector_ref.empty:
        logger.warning("reference tables are empty - enrichment will be minimal. Check database bootstrap logs.")
        return _apply_defaults(df)

    if universe.empty:
        universe = pd.DataFrame(
            columns=[
                "symbol",
                "company_name_hint",
                "sector",
                "sub_sector",
                "market_cap_tier",
                "is_nifty50",
                "is_nifty_next50",
                "is_banknifty",
            ]
        )
    if sector_ref.empty:
        sector_ref = pd.DataFrame(columns=["symbol", "sector", "sub_sector"])

    universe["symbol"] = universe["symbol"].astype(str).str.upper().str.strip()
    sector_ref["symbol"] = sector_ref["symbol"].astype(str).str.upper().str.strip()

    fo_set = set(universe["symbol"].str.upper())
    nifty50_set = set(universe[universe["is_nifty50"]]["symbol"])
    next50_set = set(universe[universe["is_nifty_next50"]]["symbol"])
    banknifty_set = set(universe[universe["is_banknifty"]]["symbol"])

    sector_map = sector_ref.set_index("symbol")[["sector", "sub_sector"]].to_dict("index")
    universe_map = universe.set_index("symbol")[
        ["sector", "sub_sector", "market_cap_tier"]
    ].to_dict("index")
    for symbol, values in universe_map.items():
        sector_map.setdefault(symbol, {}).update(values)

    out = df.copy()
    out["_resolved_symbol"] = out.apply(
        lambda row: _resolve_symbol(row["symbol"], row["company_name"], universe),
        axis=1,
    )

    out["is_fo"] = out["_resolved_symbol"].isin(fo_set)
    out["is_nifty50"] = out["_resolved_symbol"].isin(nifty50_set)
    out["is_nifty_next50"] = out["_resolved_symbol"].isin(next50_set)
    out["is_banknifty"] = out["_resolved_symbol"].isin(banknifty_set)

    out["sector"] = out["_resolved_symbol"].map(
        lambda symbol: sector_map.get(symbol, {}).get("sector", None)
    )
    out["market_cap_tier"] = out["_resolved_symbol"].map(
        lambda symbol: sector_map.get(symbol, {}).get("market_cap_tier", None)
    )

    out["importance_score"] = out.apply(
        lambda row: _score(row, nifty50_set, next50_set, banknifty_set, fo_set),
        axis=1,
    )

    out = out.drop(columns=["_resolved_symbol"])
    logger.info(
        "Enrichment complete | fo=%d nifty50=%d sector_mapped=%d",
        out["is_fo"].sum(),
        out["is_nifty50"].sum(),
        out["sector"].notna().sum(),
    )
    return out


def _resolve_symbol(raw_symbol: str, company_name: str, universe: pd.DataFrame) -> str:
    """
    Prefer the exchange-provided symbol. Only if it is missing, try an exact
    normalized company-name hint match from the seeded universe.
    """
    symbol = str(raw_symbol).strip().upper()
    if symbol and symbol not in {"NAN", "NONE", "NULL"}:
        return symbol

    if universe.empty or "company_name_hint" not in universe.columns:
        return ""

    normalized_name = _normalize_company_name(company_name)
    hints = universe[["symbol", "company_name_hint"]].dropna(subset=["company_name_hint"])
    for _, row in hints.iterrows():
        if _normalize_company_name(row["company_name_hint"]) == normalized_name:
            return str(row["symbol"]).upper().strip()

    return ""


def _normalize_company_name(name: str) -> str:
    name = str(name).upper()
    name = _NOISE.sub(" ", name)
    return re.sub(r"\s+", " ", name).strip()


def _score(row: pd.Series, nifty50: set, next50: set, banknifty: set, fo: set) -> int:
    symbol = str(row.get("_resolved_symbol", "")).upper()
    score = 0

    if symbol in nifty50:
        score += SCORE_NIFTY50
    if symbol in next50:
        score += SCORE_NIFTY_NEXT50
    if symbol in banknifty:
        score += SCORE_BANKNIFTY
    if symbol in fo:
        score += SCORE_FO

    tier = str(row.get("market_cap_tier", "")).lower()
    if tier == "large":
        score += SCORE_LARGE_CAP
    elif tier == "mid":
        score += SCORE_MID_CAP
    elif tier == "small":
        score += SCORE_SMALL_CAP

    return score


def _load_fo_universe(conn) -> pd.DataFrame:
    sql = """
        SELECT symbol, company_name_hint, sector, sub_sector, market_cap_tier,
               is_nifty50, is_nifty_next50, is_banknifty
        FROM fo_universe
    """
    return run_query_df(conn, sql)


def _load_sector_map(conn) -> pd.DataFrame:
    sql = """
        SELECT symbol, sector, sub_sector
        FROM sector_map
    """
    return run_query_df(conn, sql)


def _apply_defaults(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["sector", "market_cap_tier"]:
        df[col] = None
    for col in ["is_fo", "is_nifty50", "is_nifty_next50", "is_banknifty"]:
        df[col] = False
    df["importance_score"] = 0
    return df
