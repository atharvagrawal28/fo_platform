"""
database/bootstrap.py
---------------------
Idempotent database bootstrap for cloud pipeline runs.

This is safe to run before every ingestion:
  - SQL migrations use IF NOT EXISTS / ON CONFLICT-safe DDL
  - seed.py uses upserts for reference CSV data
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from configs.settings import DATABASE_URL
from database.connection import pipeline_cursor
from pipeline.seed import seed_fo_universe, seed_sector_map

logger = logging.getLogger(__name__)


def bootstrap_database(database_url: str = DATABASE_URL) -> None:
    """Apply migrations and seed reference tables."""
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set.")

    _apply_migrations(database_url)
    _seed_reference_data()


def _apply_migrations(database_url: str) -> None:
    migrations_dir = Path(__file__).parent / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        raise RuntimeError(f"No migration files found in {migrations_dir}")

    with pipeline_cursor(database_url) as cur:
        for path in migration_files:
            logger.info("Applying migration: %s", path.name)
            cur.execute(path.read_text(encoding="utf-8"))


def _seed_reference_data() -> None:
    logger.info("Seeding reference data from CSV files.")
    seed_fo_universe()
    seed_sector_map()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    bootstrap_database()
    logger.info("Database bootstrap complete.")
