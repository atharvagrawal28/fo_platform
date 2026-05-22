"""
pipeline/enrich.py
------------------
Adds intelligence to the raw earnings calendar:
  - F&O status
  - Sector mapping
  - Index membership (Nifty 50, Nifty Next 50, Bank Nifty)
  - Market cap tier
  - Importance score

All reference data is loaded directly from CSV files in data/ — no database.
"""

import logging
import re

import pandas as pd

from configs.settings import (
    BANKNIFTY_CSV,
    FO_UNIVERSE_CSV,
    NIFTY50_CSV,
    NIFTY_NEXT50_CSV,
    SCORE_BANKNIFTY,
    SCORE_FO,
    SCORE_LARGE_CAP,
    SCORE_MID_CAP,
    SCORE_NIFTY50,
    SCORE_NIFTY_NEXT50,
    SCORE_SMALL_CAP,
    SECTOR_MAP_CSV,
)

logger = logging.getLogger(__name__)

_NOISE = re.compile(
    r"\b(LIMITED|LTD|PRIVATE|PVT|INDUSTRIES|INDUSTRY|INDIA|INDIAN|"
    r"CORPORATION|CORP|ENTERPRISES|ENTERPRISE|COMPANY|CO|GROUP|"
    r"HOLDINGS|HOLDING|SERVICES|SOLUTIONS|TECHNOLOGIES|TECHNOLOGY|"
    r"INFRASTRUCTURE|INFRA|FINANCIAL|FINANCE|BANK|BANKING|"
    r"PHARMACEUTICALS|PHARMA|AND|&)\b",
    re.IGNORECASE,
)


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add sector, index/F&O flags, market-cap tier, and importance score.

    Exchange-provided symbols are treated as authoritative. This prevents
    false positives such as 'Jay Bharat Maruti' being mapped to MARUTI.
    """
    if df.empty:
        return df

    universe   = _load_fo_universe()
    sector_ref = _load_sector_map()

    if universe.empty and sector_ref.empty:
        logger.warning(
            "Reference CSV files are empty — enrichment will be minimal. "
            "Check that data/fo_universe.csv and data/sector_map.csv exist."
        )
        return _apply_defaults(df)

    # Normalise symbol columns
    if not universe.empty:
        universe["symbol"] = universe["symbol"].astype(str).str.upper().str.strip()
    if not sector_ref.empty:
        sector_ref["symbol"] = sector_ref["symbol"].astype(str).str.upper().str.strip()

    # Build membership sets from individual index files
    fo_set       = set(universe["symbol"]) if not universe.empty else set()
    nifty50_set  = _load_symbol_set(NIFTY50_CSV)
    next50_set   = _load_symbol_set(NIFTY_NEXT50_CSV)
    banknifty_set = _load_symbol_set(BANKNIFTY_CSV)

    # Build sector + market-cap lookup: sector_map wins over fo_universe for sector
    universe_map: dict = {}
    if not universe.empty:
        for _, row in universe.iterrows():
            sym = str(row["symbol"]).upper().strip()
            universe_map[sym] = {
                "sector":          row.get("sector", None),
                "sub_sector":      row.get("sub_sector", None),
                "market_cap_tier": row.get("market_cap_tier", None),
            }

    sector_map: dict = dict(universe_map)  # start from universe, then override
    if not sector_ref.empty:
        for _, row in sector_ref.iterrows():
            sym = str(row["symbol"]).upper().strip()
            sector_map.setdefault(sym, {}).update({
                "sector":     row.get("sector", None),
                "sub_sector": row.get("sub_sector", None),
            })

    out = df.copy()
    out["_resolved_symbol"] = out.apply(
        lambda row: _resolve_symbol(row["symbol"], row["company_name"], universe),
        axis=1,
    )

    out["is_fo"]          = out["_resolved_symbol"].isin(fo_set)
    out["is_nifty50"]     = out["_resolved_symbol"].isin(nifty50_set)
    out["is_nifty_next50"] = out["_resolved_symbol"].isin(next50_set)
    out["is_banknifty"]   = out["_resolved_symbol"].isin(banknifty_set)

    out["sector"] = out["_resolved_symbol"].map(
        lambda sym: sector_map.get(sym, {}).get("sector", None)
    )
    out["market_cap_tier"] = out["_resolved_symbol"].map(
        lambda sym: sector_map.get(sym, {}).get("market_cap_tier", None)
    )

    out["importance_score"] = out.apply(
        lambda row: _score(row, nifty50_set, next50_set, banknifty_set, fo_set),
        axis=1,
    )

    out = out.drop(columns=["_resolved_symbol"])
    logger.info(
        "Enrichment complete | fo=%d nifty50=%d sector_mapped=%d",
        int(out["is_fo"].sum()),
        int(out["is_nifty50"].sum()),
        int(out["sector"].notna().sum()),
    )
    return out


# ── Reference data loaders ────────────────────────────────────────────────────
def _load_fo_universe() -> pd.DataFrame:
    if not FO_UNIVERSE_CSV.exists():
        logger.warning("fo_universe.csv not found at %s", FO_UNIVERSE_CSV)
        return pd.DataFrame()
    try:
        return pd.read_csv(FO_UNIVERSE_CSV)
    except Exception as e:
        logger.error("Could not read fo_universe.csv: %s", e)
        return pd.DataFrame()


def _load_sector_map() -> pd.DataFrame:
    if not SECTOR_MAP_CSV.exists():
        logger.warning("sector_map.csv not found at %s", SECTOR_MAP_CSV)
        return pd.DataFrame()
    try:
        return pd.read_csv(SECTOR_MAP_CSV)
    except Exception as e:
        logger.error("Could not read sector_map.csv: %s", e)
        return pd.DataFrame()


def _load_symbol_set(path) -> set:
    """Load a single-column CSV (header 'symbol') as an uppercase set."""
    if not path.exists():
        logger.warning("Symbol file not found: %s", path)
        return set()
    try:
        df = pd.read_csv(path)
        return set(df["symbol"].astype(str).str.upper().str.strip())
    except Exception as e:
        logger.error("Could not read %s: %s", path, e)
        return set()


# ── Symbol resolution ─────────────────────────────────────────────────────────
def _resolve_symbol(raw_symbol: str, company_name: str, universe: pd.DataFrame) -> str:
    """
    Prefer the exchange-provided symbol. Only if it is missing / invalid,
    fall back to an exact normalised company-name hint from the universe.
    """
    symbol = str(raw_symbol).strip().upper()
    if symbol and symbol not in {"NAN", "NONE", "NULL", ""}:
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


# ── Scoring ───────────────────────────────────────────────────────────────────
def _score(row: pd.Series, nifty50: set, next50: set, banknifty: set, fo: set) -> int:
    symbol = str(row.get("_resolved_symbol", "")).upper()
    score  = 0

    if symbol in nifty50:   score += SCORE_NIFTY50
    if symbol in next50:    score += SCORE_NIFTY_NEXT50
    if symbol in banknifty: score += SCORE_BANKNIFTY
    if symbol in fo:        score += SCORE_FO

    tier = str(row.get("market_cap_tier", "")).lower()
    if tier == "large":     score += SCORE_LARGE_CAP
    elif tier == "mid":     score += SCORE_MID_CAP
    elif tier == "small":   score += SCORE_SMALL_CAP

    return score


def _apply_defaults(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["sector", "market_cap_tier"]:
        df[col] = None
    for col in ["is_fo", "is_nifty50", "is_nifty_next50", "is_banknifty"]:
        df[col] = False
    df["importance_score"] = 0
    return df
