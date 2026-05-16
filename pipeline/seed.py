"""
pipeline/seed.py
----------------
One-time script to load static CSV reference data into PostgreSQL.

Run ONCE after creating the schema:
    python pipeline/seed.py

What it loads:
  - fo_universe   ← data/fo_universe.csv + index membership CSVs
  - sector_map    ← data/sector_map.csv

Safe to re-run — uses ON CONFLICT DO UPDATE so no duplicates.
"""

import logging
import sys
from pathlib import Path

import pandas as pd
import psycopg2.extras

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from configs.settings import (
    BANKNIFTY_CSV,
    DATABASE_URL,
    FO_UNIVERSE_CSV,
    NIFTY50_CSV,
    NIFTY_NEXT50_CSV,
    SECTOR_MAP_CSV,
)

from database.connection import pipeline_cursor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger(__name__)


def _load_symbol_set(path) -> set:
    """Load CSV symbol column into uppercase set."""
    try:
        df = pd.read_csv(path)

        return set(
            df["symbol"]
            .astype(str)
            .str.upper()
            .str.strip()
            .dropna()
        )

    except FileNotFoundError:
        logger.warning("File not found: %s — treating as empty set", path)
        return set()


def seed_fo_universe():
    """Load fo_universe.csv and membership CSVs into fo_universe table."""

    logger.info("Loading fo_universe.csv...")

    df = pd.read_csv(FO_UNIVERSE_CSV)
    df.columns = df.columns.str.strip().str.lower()

    # Normalize symbols
    df["symbol"] = (
        df["symbol"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # Remove blank symbols
    df = df[df["symbol"] != ""]

    # Remove duplicate symbols
    print("Rows before dedupe:", len(df))

    df = df.drop_duplicates(subset=["symbol"])

    print("Rows after dedupe:", len(df))

    # Load index membership sets
    nifty50 = _load_symbol_set(NIFTY50_CSV)
    nifty_next50 = _load_symbol_set(NIFTY_NEXT50_CSV)
    banknifty = _load_symbol_set(BANKNIFTY_CSV)

    # Add membership flags
    df["is_nifty50"] = df["symbol"].isin(nifty50)
    df["is_nifty_next50"] = df["symbol"].isin(nifty_next50)
    df["is_banknifty"] = df["symbol"].isin(banknifty)

    # Compute base importance score
    def _base_score(row):
        score = 0

        if row["is_nifty50"]:
            score += 40

        if row["is_nifty_next50"]:
            score += 25

        if row["is_banknifty"]:
            score += 20

        market_cap = str(
            row.get("market_cap_tier", "")
        ).lower()

        if market_cap == "large":
            score += 20

        elif market_cap == "mid":
            score += 10

        elif market_cap == "small":
            score += 5

        return score

    df["base_importance"] = df.apply(
        _base_score,
        axis=1
    )

    sql = """
        INSERT INTO fo_universe (
            symbol,
            company_name_hint,
            sector,
            sub_sector,
            is_nifty50,
            is_nifty_next50,
            is_banknifty,
            market_cap_tier,
            base_importance
        )
        VALUES %s

        ON CONFLICT (symbol)
        DO UPDATE SET
            company_name_hint = EXCLUDED.company_name_hint,
            sector            = EXCLUDED.sector,
            sub_sector        = EXCLUDED.sub_sector,
            is_nifty50        = EXCLUDED.is_nifty50,
            is_nifty_next50   = EXCLUDED.is_nifty_next50,
            is_banknifty      = EXCLUDED.is_banknifty,
            market_cap_tier   = EXCLUDED.market_cap_tier,
            base_importance   = EXCLUDED.base_importance,
            updated_at        = NOW()
    """

    rows = [
        (
            str(r["symbol"]).upper().strip(),
            str(r.get("company_name_hint", "")).strip() or None,
            str(r.get("sector", "")).strip() or None,
            str(r.get("sub_sector", "")).strip() or None,
            bool(r["is_nifty50"]),
            bool(r["is_nifty_next50"]),
            bool(r["is_banknifty"]),
            str(r.get("market_cap_tier", "mid")).strip(),
            int(r["base_importance"]),
        )
        for _, r in df.iterrows()
    ]

    with pipeline_cursor(DATABASE_URL) as cur:
        psycopg2.extras.execute_values(
            cur,
            sql,
            rows,
            page_size=200
        )

    logger.info(
        "fo_universe: loaded %d rows",
        len(rows)
    )


def seed_sector_map():
    """Load sector_map.csv into sector_map table."""

    logger.info("Loading sector_map.csv...")

    df = pd.read_csv(SECTOR_MAP_CSV)
    df.columns = df.columns.str.strip().str.lower()

    # Normalize symbols
    df["symbol"] = (
        df["symbol"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # Remove blank symbols
    df = df[df["symbol"] != ""]

    # Remove duplicate symbols
    print("Sector rows before dedupe:", len(df))

    df = df.drop_duplicates(subset=["symbol"])

    print("Sector rows after dedupe:", len(df))

    sql = """
        INSERT INTO sector_map (
            symbol,
            sector,
            sub_sector
        )
        VALUES %s

        ON CONFLICT (symbol)
        DO UPDATE SET
            sector     = EXCLUDED.sector,
            sub_sector = EXCLUDED.sub_sector,
            updated_at = NOW()
    """

    rows = [
        (
            str(r["symbol"]).upper().strip(),
            str(r["sector"]).strip(),
            str(r.get("sub_sector", "")).strip() or None,
        )
        for _, r in df.iterrows()
    ]

    with pipeline_cursor(DATABASE_URL) as cur:
        psycopg2.extras.execute_values(
            cur,
            sql,
            rows,
            page_size=200
        )

    logger.info(
        "sector_map: loaded %d rows",
        len(rows)
    )


if __name__ == "__main__":

    if not DATABASE_URL:
        print(
            "ERROR: DATABASE_URL is not set. "
            "Add it to your .env file."
        )
        sys.exit(1)

    logger.info("Starting database seed...")

    seed_fo_universe()
    seed_sector_map()

    logger.info("✅ Seed complete.")
    