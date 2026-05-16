"""
configs/settings.py
-------------------
Single source of truth for every configuration value.

Priority order for DATABASE_URL:
  1. Environment variable (GitHub Actions / Streamlit Cloud / server)
  2. .env file (local development)
  3. Raises clear error if neither exists
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file for local development — no-op in production
load_dotenv()

# ── Root paths ────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── API endpoints ─────────────────────────────────────────────────────────────
NSE_HOME_URL     = "https://www.nseindia.com"
NSE_PREFETCH_URL = "https://www.nseindia.com/market-data/upcoming-board-meetings"
NSE_API_URL      = "https://www.nseindia.com/api/event-calendar"

BSE_API_URL  = "https://api.bseindia.com/BseIndiaAPI/api/ForwardResults/w"
BSE_HTML_URL = "https://www.bseindia.com/corporates/forth_results"

# ── Scraper behaviour ─────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 20     # seconds
MAX_RETRIES       = 3
BACKOFF_BASE      = 2      # exponential: 2s, 4s, 8s

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── Validation thresholds ─────────────────────────────────────────────────────
MIN_ROWS           = 3     # fewer rows than this = likely corrupted fetch
MAX_DUPLICATE_PCT  = 0.50  # >50% duplicates = suspicious
MAX_FUTURE_DAYS    = 90    # dates beyond 90 days = probably wrong

# ── Dashboard ─────────────────────────────────────────────────────────────────
LOOKAHEAD_DAYS = 7

# ── Importance scoring weights ─────────────────────────────────────────────────
SCORE_NIFTY50      = 40
SCORE_NIFTY_NEXT50 = 25
SCORE_BANKNIFTY    = 20
SCORE_FO           = 15
SCORE_LARGE_CAP    = 20
SCORE_MID_CAP      = 10
SCORE_SMALL_CAP    =  5

# ── Data file paths ───────────────────────────────────────────────────────────
FO_UNIVERSE_CSV      = DATA_DIR / "fo_universe.csv"
SECTOR_MAP_CSV       = DATA_DIR / "sector_map.csv"
NIFTY50_CSV          = DATA_DIR / "nifty50.csv"
NIFTY_NEXT50_CSV     = DATA_DIR / "nifty_next50.csv"
BANKNIFTY_CSV        = DATA_DIR / "banknifty.csv"
MARKET_CAP_TIERS_CSV = DATA_DIR / "market_cap_tiers.csv"
