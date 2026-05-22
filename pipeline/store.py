"""
pipeline/store.py
-----------------
Writes enriched data to CSV files committed to the repository.
No database required — 100% free, runs indefinitely on GitHub Actions.

Architecture:
  data/earnings_calendar.csv  — live earnings window (rolling, pruned daily)
  data/pipeline_log.json      — last 30 run records for the health panel
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from configs.settings import DATA_DIR
from pipeline.validate import canonical_name

logger = logging.getLogger(__name__)

CALENDAR_CSV = DATA_DIR / "earnings_calendar.csv"
PIPELINE_LOG = DATA_DIR / "pipeline_log.json"
MAX_LOG_RUNS = 30  # keep last N pipeline run records


# ── Public entry point ────────────────────────────────────────────────────────
def store_results(
    df: pd.DataFrame,
    run_id: str,
    metadata: dict,
) -> dict:
    if df.empty:
        logger.warning("store_results called with empty DataFrame — skipping")
        return {"rows_stored": 0}

    source  = metadata.get("source", "")
    stored  = _write_earnings_calendar(df, current_source=source)

    logger.info("Store complete | written=%d", stored)
    return {"rows_stored": stored}


# ── Write earnings_calendar.csv ───────────────────────────────────────────────
def _write_earnings_calendar(df: pd.DataFrame, current_source: str = "") -> int:
    """
    Merge new data with existing CSV using (result_date, name_norm) dedup,
    prune past-dated rows, prune BSE rows when NSE is authoritative.
    Returns number of new rows that were written.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    new_df = _prepare_rows(df)
    if new_df.empty:
        logger.warning("No valid rows after prepare — skipping write")
        return 0

    existing = _load_existing_calendar()

    # Merge: new rows take precedence over existing on (date, name_norm)
    if not existing.empty:
        combined = pd.concat([new_df, existing], ignore_index=True)
        combined = combined.drop_duplicates(subset=["result_date", "name_norm"], keep="first")
    else:
        combined = new_df.copy()

    # Prune: remove rows before yesterday (keep yesterday for late-evening runs)
    today     = pd.Timestamp.now().normalize()
    yesterday = today - pd.Timedelta(days=1)
    combined  = combined[pd.to_datetime(combined["result_date"]) >= yesterday]

    # Prune: remove BSE rows when NSE was authoritative this run
    if "nse" in str(current_source).lower():
        before  = len(combined)
        combined = combined[combined["source"] != "bse_official_file"]
        pruned  = before - len(combined)
        if pruned:
            logger.info("Pruned %d stale BSE rows (NSE is authoritative)", pruned)

    # Sort for stable, readable diffs
    combined = combined.sort_values(
        ["result_date", "importance_score"],
        ascending=[True, False],
    )

    combined.to_csv(CALENDAR_CSV, index=False)
    logger.info("Saved %d rows to %s", len(combined), CALENDAR_CSV)
    return len(new_df)


def _prepare_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise and type-cast every row before writing."""
    now_str = datetime.now(timezone.utc).isoformat()
    rows = []
    for _, row in df.iterrows():
        company_name = str(row.get("company_name", ""))[:500]
        name_norm    = (row.get("name_norm") or canonical_name(company_name))[:500]
        if not name_norm:
            continue
        date_str = _to_date_str(row.get("result_date"))
        if not date_str:
            continue
        rows.append({
            "result_date":     date_str,
            "company_name":    company_name,
            "name_norm":       name_norm,
            "symbol":          str(row.get("symbol", ""))[:50] or "",
            "meeting_type":    str(row.get("meeting_type", "Quarterly Results"))[:200],
            "source":          str(row.get("source", ""))[:50],
            "sector":          str(row.get("sector", "")) if row.get("sector") else "",
            "is_fo":           bool(row.get("is_fo", False)),
            "is_nifty50":      bool(row.get("is_nifty50", False)),
            "is_nifty_next50": bool(row.get("is_nifty_next50", False)),
            "is_banknifty":    bool(row.get("is_banknifty", False)),
            "market_cap_tier": str(row.get("market_cap_tier", "")) if row.get("market_cap_tier") else "",
            "importance_score": int(row.get("importance_score", 0)),
            "updated_at":      now_str,
        })
    return pd.DataFrame(rows)


def _load_existing_calendar() -> pd.DataFrame:
    if not CALENDAR_CSV.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(CALENDAR_CSV, dtype=str)
        # Coerce numeric / boolean columns back to correct types
        df["importance_score"] = pd.to_numeric(
            df.get("importance_score", 0), errors="coerce"
        ).fillna(0).astype(int)
        bool_map = {"True": True, "False": False, "true": True, "false": False}
        for col in ["is_fo", "is_nifty50", "is_nifty_next50", "is_banknifty"]:
            if col in df.columns:
                df[col] = df[col].map(bool_map).fillna(False)
        return df
    except Exception as e:
        logger.warning("Could not load existing calendar: %s", e)
        return pd.DataFrame()


# ── Pipeline log ──────────────────────────────────────────────────────────────
def log_pipeline_start(run_id: str) -> None:
    """No-op at start — everything is written on completion."""
    pass


def log_pipeline_complete(
    run_id: str,
    source: str,
    rows_fetched: int,
    rows_valid: int,
    rows_stored: int,
    validation_passed: bool,
    fallback_used: bool,
    duration_s: float,
    status: str,
    error: str = "",
) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    logs: list = []
    if PIPELINE_LOG.exists():
        try:
            logs = json.loads(PIPELINE_LOG.read_text(encoding="utf-8"))
        except Exception:
            logs = []

    entry = {
        "run_id":            run_id,
        "started_at":        datetime.now(timezone.utc).isoformat(),
        "source_used":       source,
        "rows_fetched":      rows_fetched,
        "rows_valid":        rows_valid,
        "rows_stored":       rows_stored,
        "validation_passed": validation_passed,
        "fallback_used":     fallback_used,
        "duration_seconds":  round(duration_s, 2),
        "status":            status,
        "error_message":     error or "",
    }

    logs.insert(0, entry)
    logs = logs[:MAX_LOG_RUNS]

    PIPELINE_LOG.write_text(json.dumps(logs, indent=2), encoding="utf-8")
    logger.info("Pipeline log updated | status=%s runs_kept=%d", status, len(logs))


def generate_run_id() -> str:
    return (
        f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        f"_{uuid.uuid4().hex[:6]}"
    )


# ── Utilities ─────────────────────────────────────────────────────────────────
def _to_date_str(val) -> str:
    if val is None:
        return ""
    try:
        return pd.to_datetime(val).strftime("%Y-%m-%d")
    except Exception:
        return ""
