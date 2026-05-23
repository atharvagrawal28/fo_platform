"""
pipeline/store_oi.py
--------------------
Writes OI positioning data to CSV files committed to GitHub.

data/oi_snapshot.csv  — today's enriched OI data (full overwrite each run)
data/oi_history.csv   — rolling OI history (append + prune to OI_HISTORY_DAYS)

History is the long-term moat: accumulated daily snapshots enable
pre-earnings buildup patterns, sector transitions, and anomaly detection.
"""

import logging
from datetime import date

import pandas as pd

from configs.settings import DATA_DIR, OI_HISTORY_CSV, OI_HISTORY_DAYS, OI_SNAPSHOT_CSV

logger = logging.getLogger(__name__)


def store_oi_results(df: pd.DataFrame) -> dict:
    """Write snapshot and update history. Returns storage summary."""
    if df.empty:
        logger.warning("store_oi_results: empty DataFrame — skipping")
        return {"snapshot_rows": 0, "history_rows": 0}

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Snapshot: full overwrite (always latest day)
    df.to_csv(OI_SNAPSHOT_CSV, index=False)
    logger.info("OI snapshot saved | rows=%d", len(df))

    # History: append + prune
    history_rows = _update_history(df)

    return {"snapshot_rows": len(df), "history_rows": history_rows}


def _update_history(new: pd.DataFrame) -> int:
    """Append today's snapshot rows to history, dedup, prune old dates."""
    existing = pd.DataFrame()
    if OI_HISTORY_CSV.exists():
        try:
            existing = pd.read_csv(OI_HISTORY_CSV, dtype=str)
        except Exception as e:
            logger.warning("Could not read OI history: %s", e)

    combined = pd.concat([existing, new.astype(str)], ignore_index=True)

    # Dedup: keep latest row per (snapshot_date, symbol)
    if "snapshot_date" in combined.columns and "symbol" in combined.columns:
        combined = combined.drop_duplicates(
            subset=["snapshot_date", "symbol"], keep="last"
        )

    # Prune: keep only within rolling window
    if "snapshot_date" in combined.columns:
        combined["snapshot_date"] = pd.to_datetime(
            combined["snapshot_date"], errors="coerce"
        )
        # Use calendar days (2× trading days to account for weekends/holidays)
        cutoff = pd.Timestamp(date.today()) - pd.Timedelta(days=OI_HISTORY_DAYS * 2)
        combined = combined[combined["snapshot_date"] >= cutoff]
        combined["snapshot_date"] = combined["snapshot_date"].dt.strftime("%Y-%m-%d")

    # Sort for readable diffs (newest first)
    if "snapshot_date" in combined.columns:
        combined = combined.sort_values("snapshot_date", ascending=False)

    combined.to_csv(OI_HISTORY_CSV, index=False)
    logger.info("OI history updated | total_rows=%d", len(combined))
    return len(combined)
