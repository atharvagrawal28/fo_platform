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
DATA_RAW_DIR = DATA_DIR / "raw"

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── API endpoints ─────────────────────────────────────────────────────────────
NSE_BOARD_MEETINGS_PAGE_URL = "https://www.nseindia.com/companies-listing/corporate-filings-board-meetings"
NSE_BOARD_MEETINGS_CSV_URL  = "https://www.nseindia.com/api/corporate-board-meetings"

BSE_FORTHCOMING_RESULTS_PAGE_URL = "https://www.bseindia.com/corporates/Forth_Results.html?expandable=3"
BSE_FORTHCOMING_RESULTS_CSV_URL  = "https://api.bseindia.com/BseIndiaAPI/api/DownloadCSV1/w"

# Legacy API constants retained for older local scripts.
NSE_HOME_URL     = "https://www.nseindia.com"
NSE_PREFETCH_URL = "https://www.nseindia.com/market-data/upcoming-board-meetings"
NSE_API_URL      = "https://www.nseindia.com/api/event-calendar"

BSE_API_URL  = "https://api.bseindia.com/BseIndiaAPI/api/ForwardResults/w"
BSE_HTML_URL = "https://www.bseindia.com/corporates/forth_results"

# ── Scraper behaviour ─────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 30     # seconds
MAX_RETRIES       = 2
BACKOFF_BASE      = 2      # capped exponential backoff

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
