"""
pipeline/run_oi.py
------------------
OI / Derivatives Positioning Intelligence pipeline.

Runs independently from the earnings pipeline (run.py).
Fetches NSE F&O Bhavcopy → classifies buildup → writes CSV files.

Called by GitHub Actions after earnings pipeline, once per trading day.
Falls back gracefully if bhavcopy isn't published yet (before ~6PM IST).
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.classify_buildup import classify_and_enrich
from pipeline.fetch_oi import fetch_oi_data
from pipeline.store_oi import store_oi_results

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pipeline.run_oi")


def run_oi_pipeline() -> int:
    started = datetime.now(timezone.utc)
    logger.info("=" * 60)
    logger.info("OI Pipeline starting")
    logger.info("=" * 60)

    try:
        # Step 1: Fetch
        logger.info("Step 1/3: Fetching NSE F&O Bhavcopy...")
        df, meta = fetch_oi_data()

        if df.empty:
            logger.warning(
                "OI fetch returned no data — bhavcopy may not be published yet. "
                "Previous snapshot retained."
            )
            return 0   # not a hard failure — just skip quietly

        logger.info(
            "Fetch done | date=%s rows=%d source=%s",
            meta["snapshot_date"], meta["rows_processed"], meta["source"],
        )

        # Step 2: Classify buildup + enrich
        logger.info("Step 2/3: Classifying buildup & enriching...")
        df_enriched = classify_and_enrich(df)
        logger.info("Classification done | total=%d", len(df_enriched))

        # Step 3: Store
        logger.info("Step 3/3: Writing OI CSVs...")
        result = store_oi_results(df_enriched)
        logger.info(
            "OI store done | snapshot=%d history=%d",
            result["snapshot_rows"], result["history_rows"],
        )

    except Exception as e:
        logger.error("OI pipeline error: %s", e, exc_info=True)
        return 1

    finally:
        duration = (datetime.now(timezone.utc) - started).total_seconds()
        logger.info("=" * 60)
        logger.info("OI Pipeline done | duration=%.1fs", duration)
        logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(run_oi_pipeline())
