"""
pipeline/run.py
---------------
Full pipeline orchestrator: fetch → validate → enrich → store → log

Fix: datetime.utcnow() replaced with datetime.now(timezone.utc)
     throughout — eliminates DeprecationWarning on Python 3.12+.
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from configs.settings import DATABASE_URL
from database.connection import get_connection
from pipeline.enrich import enrich
from pipeline.fetch import fetch_earnings
from pipeline.store import (
    generate_run_id,
    log_pipeline_complete,
    log_pipeline_start,
    store_results,
)
from pipeline.validate import validate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pipeline.run")


def run_pipeline() -> int:
    if not DATABASE_URL:
        logger.error("DATABASE_URL is not set.")
        return 1

    run_id     = generate_run_id()
    started_at = datetime.now(timezone.utc)          # Fix: was datetime.utcnow()

    logger.info("=" * 60)
    logger.info("Pipeline starting | run_id=%s", run_id)
    logger.info("=" * 60)

    try:
        log_pipeline_start(run_id, DATABASE_URL)
    except Exception as e:
        logger.error("Could not write pipeline start log: %s", e)

    source        = "none"
    rows_fetched  = 0
    rows_valid    = 0
    rows_stored   = 0
    val_passed    = False
    fallback_used = False
    error_msg     = ""
    exit_code     = 1

    try:
        # ── Step 1: Fetch ─────────────────────────────────────────────────────
        logger.info("Step 1/4: Fetching data...")
        df, fetch_meta = fetch_earnings()

        source        = fetch_meta.get("source", "none")
        rows_fetched  = fetch_meta.get("rows_fetched", 0)
        fallback_used = fetch_meta.get("fallback_used", False)

        logger.info(
            "Fetch done | source=%s rows=%d fallback=%s",
            source, rows_fetched, fallback_used,
        )

        if df.empty:
            raise RuntimeError("Fetch returned no data from any source.")

        # ── Step 2: Validate ──────────────────────────────────────────────────
        logger.info("Step 2/4: Validating...")
        val_passed, fail_reason, df_clean = validate(df)

        if not val_passed:
            error_msg = f"Validation failed: {fail_reason}"
            logger.error(error_msg)
            logger.warning("Production data NOT updated — last valid snapshot preserved.")
            raise RuntimeError(error_msg)

        rows_valid = len(df_clean)
        logger.info("Validation passed | clean_rows=%d", rows_valid)

        # ── Step 3: Enrich ────────────────────────────────────────────────────
        logger.info("Step 3/4: Enriching...")
        conn = get_connection(DATABASE_URL)
        try:
            df_enriched = enrich(df_clean, conn)
        finally:
            conn.close()

        logger.info(
            "Enrichment done | fo=%d nifty50=%d sector_mapped=%d",
            int(df_enriched["is_fo"].sum()),
            int(df_enriched["is_nifty50"].sum()),
            int(df_enriched["sector"].notna().sum()),
        )

        # ── Step 4: Store ─────────────────────────────────────────────────────
        logger.info("Step 4/4: Storing to PostgreSQL...")
        store_meta  = store_results(df_enriched, run_id, fetch_meta, DATABASE_URL)
        rows_stored = store_meta.get("rows_stored", 0)
        logger.info("Store done | upserted=%d", rows_stored)

        exit_code = 0

    except Exception as e:
        error_msg = str(e) or type(e).__name__
        logger.error("Pipeline error: %s", error_msg, exc_info=True)
        exit_code = 1

    finally:
        duration = (datetime.now(timezone.utc) - started_at).total_seconds()  # Fix
        status   = "success" if exit_code == 0 else "failed"

        try:
            log_pipeline_complete(
                run_id            = run_id,
                database_url      = DATABASE_URL,
                source            = source,
                rows_fetched      = rows_fetched,
                rows_valid        = rows_valid,
                rows_stored       = rows_stored,
                validation_passed = val_passed,
                fallback_used     = fallback_used,
                duration_s        = round(duration, 2),
                status            = status,
                error             = error_msg,
            )
        except Exception as log_err:
            logger.error("Failed to write completion log: %s", log_err)

        logger.info("=" * 60)
        logger.info(
            "Pipeline %s | duration=%.1fs rows_stored=%d source=%s",
            status.upper(), duration, rows_stored, source,
        )
        logger.info("=" * 60)

    return exit_code


if __name__ == "__main__":
    sys.exit(run_pipeline())
