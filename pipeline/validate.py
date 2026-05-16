"""
pipeline/validate.py
--------------------
Explicit, concrete validation rules — no vague "anomaly detection."

Philosophy:
  - If current fetch looks corrupted, DO NOT overwrite production data.
  - Return (is_valid, reason, cleaned_df) so run.py can decide.
  - Rules are defined as constants — easy to tune without code changes.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd

from configs.settings import MAX_DUPLICATE_PCT, MAX_FUTURE_DAYS, MIN_ROWS

logger = logging.getLogger(__name__)


def validate(df: pd.DataFrame) -> tuple[bool, str, pd.DataFrame]:
    """
    Run all validation checks on a freshly fetched DataFrame.

    Returns
    -------
    (is_valid, failure_reason, cleaned_df)
        is_valid      : False means pipeline should NOT overwrite production data
        failure_reason: human-readable explanation (empty string if valid)
        cleaned_df    : DataFrame with obvious bad rows removed (even if valid)
    """
    if df is None or df.empty:
        return False, "Fetch returned no data", pd.DataFrame()

    original_count = len(df)
    df = df.copy()

    # ── Rule 1: Minimum rows ──────────────────────────────────────────────────
    if len(df) < MIN_ROWS:
        reason = f"Too few rows: got {len(df)}, minimum is {MIN_ROWS}. Likely a corrupted fetch."
        logger.error("❌ Validation failed: %s", reason)
        return False, reason, df

    # ── Rule 2: result_date must be datetime ──────────────────────────────────
    df["result_date"] = pd.to_datetime(df["result_date"], errors="coerce")
    bad_dates = df["result_date"].isna().sum()
    if bad_dates > 0:
        logger.warning("Dropping %d rows with unparseable dates", bad_dates)
        df = df.dropna(subset=["result_date"])

    if df.empty:
        return False, "All rows had invalid dates after parsing", df

    # ── Rule 3: No results from the distant past ──────────────────────────────
    today      = pd.Timestamp(datetime.today().date())
    past_cutoff = today - timedelta(days=1)
    past_rows   = (df["result_date"] < past_cutoff).sum()
    if past_rows > 0:
        logger.debug("Dropping %d past-dated rows", past_rows)
        df = df[df["result_date"] >= past_cutoff]

    # ── Rule 4: No results unreasonably far in the future ────────────────────
    future_cutoff = today + timedelta(days=MAX_FUTURE_DAYS)
    future_rows   = (df["result_date"] > future_cutoff).sum()
    if future_rows > 0:
        logger.warning("Dropping %d rows with dates beyond %d days", future_rows, MAX_FUTURE_DAYS)
        df = df[df["result_date"] <= future_cutoff]

    # ── Rule 5: Duplicate check ───────────────────────────────────────────────
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["result_date", "company_name"])
    dropped = before_dedup - len(df)
    dup_pct = dropped / original_count if original_count else 0

    if dup_pct > MAX_DUPLICATE_PCT:
        reason = (
            f"Excessive duplicates: {dup_pct:.0%} of rows were duplicates "
            f"(threshold: {MAX_DUPLICATE_PCT:.0%}). Source data may be corrupted."
        )
        logger.error("❌ Validation failed: %s", reason)
        return False, reason, df

    if dropped > 0:
        logger.info("Removed %d duplicate rows (%.0f%%)", dropped, dup_pct * 100)

    # ── Rule 6: company_name must not be empty ────────────────────────────────
    empty_names = df["company_name"].str.strip().eq("").sum()
    if empty_names > 0:
        logger.warning("Dropping %d rows with empty company_name", empty_names)
        df = df[df["company_name"].str.strip().astype(bool)]

    # ── Final check ───────────────────────────────────────────────────────────
    if len(df) < MIN_ROWS:
        reason = f"After cleaning, only {len(df)} rows remain (minimum: {MIN_ROWS})."
        return False, reason, df

    logger.info(
        "✅ Validation passed | original=%d cleaned=%d",
        original_count, len(df),
    )
    return True, "", df.reset_index(drop=True)
