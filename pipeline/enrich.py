"""
pipeline/enrich.py
------------------
Adds intelligence to the raw earnings calendar:
  - F&O status        (is this an F&O stock?)
  - Sector mapping    (which sector does it belong to?)
  - Index membership  (Nifty50? BankNifty?)
  - Importance score  (how market-significant is this result?)

All lookups are done via the fo_universe table in PostgreSQL
(seeded from CSV files by pipeline/seed.py).

Importance scoring weights (defined in configs/settings.py):
  Nifty50      → +40
  Nifty Next50 → +25
  BankNifty    → +20
  F&O stock    → +15
  Large cap    → +20
  Mid cap      → +10
  Small cap    → +5
"""

import logging
import re

import pandas as pd

from configs.settings import (
    SCORE_BANKNIFTY, SCORE_FO, SCORE_LARGE_CAP, SCORE_MID_CAP,
    SCORE_NIFTY50, SCORE_NIFTY_NEXT50, SCORE_SMALL_CAP,
)
from database.connection import run_query_df

logger = logging.getLogger(__name__)

# Words stripped from company names before symbol matching
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
    Main enrichment entry point.
    Adds: sector, is_fo, is_nifty50, is_nifty_next50, is_banknifty,
          market_cap_tier, importance_score
    """
    if df.empty:
        return df

    # Load reference data from DB
    universe = _load_fo_universe(conn)
    if universe.empty:
        logger.warning("fo_universe table is empty — enrichment will be minimal. Run seed.py first.")
        return _apply_defaults(df)

    # Build fast lookup dictionaries
    fo_set         = set(universe["symbol"].str.upper())
    nifty50_set    = set(universe[universe["is_nifty50"]]["symbol"])
    next50_set     = set(universe[universe["is_nifty_next50"]]["symbol"])
    banknifty_set  = set(universe[universe["is_banknifty"]]["symbol"])
    sector_map     = universe.set_index("symbol")[["sector", "sub_sector", "market_cap_tier"]].to_dict("index")

    out = df.copy()

    # Resolve symbol: use fetched symbol if trusted, else match from name
    out["_resolved_symbol"] = out.apply(
        lambda row: _resolve_symbol(row["symbol"], row["company_name"], fo_set),
        axis=1,
    )

    # Enrichment columns
    out["is_fo"]           = out["_resolved_symbol"].isin(fo_set)
    out["is_nifty50"]      = out["_resolved_symbol"].isin(nifty50_set)
    out["is_nifty_next50"] = out["_resolved_symbol"].isin(next50_set)
    out["is_banknifty"]    = out["_resolved_symbol"].isin(banknifty_set)

    out["sector"]          = out["_resolved_symbol"].map(
        lambda s: sector_map.get(s, {}).get("sector", None)
    )
    out["market_cap_tier"] = out["_resolved_symbol"].map(
        lambda s: sector_map.get(s, {}).get("market_cap_tier", None)
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


# ── Symbol resolution ─────────────────────────────────────────────────────────
def _resolve_symbol(raw_symbol: str, company_name: str, fo_set: set) -> str:
    """
    Try to identify the NSE symbol for a company.

    Priority:
      1. raw_symbol directly in fo_set (NSE data is best)
      2. Regex word-boundary match on normalized company name
      3. Return raw_symbol as-is (may not match, importance_score = 0)
    """
    sym = str(raw_symbol).strip().upper()
    if sym and sym in fo_set:
        return sym

    # Normalize the company name
    name = str(company_name).upper()
    name = _NOISE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip()

    # Match against F&O symbols using word boundaries (no false positives)
    for candidate in sorted(fo_set, key=len, reverse=True):
        pattern = r"\b" + re.escape(candidate) + r"\b"
        if re.search(pattern, name):
            return candidate

    return sym  # unmatched — will score 0


# ── Importance scoring ────────────────────────────────────────────────────────
def _score(row: pd.Series, nifty50: set, next50: set, banknifty: set, fo: set) -> int:
    sym   = str(row.get("_resolved_symbol", "")).upper()
    score = 0

    if sym in nifty50:    score += SCORE_NIFTY50
    if sym in next50:     score += SCORE_NIFTY_NEXT50
    if sym in banknifty:  score += SCORE_BANKNIFTY
    if sym in fo:         score += SCORE_FO

    tier = str(row.get("market_cap_tier", "")).lower()
    if tier == "large":   score += SCORE_LARGE_CAP
    elif tier == "mid":   score += SCORE_MID_CAP
    elif tier == "small": score += SCORE_SMALL_CAP

    return score


# ── DB loader ─────────────────────────────────────────────────────────────────
def _load_fo_universe(conn) -> pd.DataFrame:
    sql = """
        SELECT symbol, sector, sub_sector, market_cap_tier,
               is_nifty50, is_nifty_next50, is_banknifty
        FROM fo_universe
    """
    return run_query_df(conn, sql)


def _apply_defaults(df: pd.DataFrame) -> pd.DataFrame:
    """Fallback when fo_universe is empty — add columns with null/False defaults."""
    for col in ["sector", "market_cap_tier"]:
        df[col] = None
    for col in ["is_fo", "is_nifty50", "is_nifty_next50", "is_banknifty"]:
        df[col] = False
    df["importance_score"] = 0
    return df
