"""
pipeline/fetch_oi.py
--------------------
Downloads NSE F&O Bhavcopy and extracts stock futures Open Interest data.

Data source: NSE Archives (official, public, no authentication required)
URL: https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip

Key advantage of this source:
  - PrvsClsgPric column provides previous day's close directly
  - No need to maintain price history for day-over-day change calculation
  - Near-month expiry gives the most liquid, watched contract

Instrument type codes in the new NSE schema:
  STF  → Stock Futures     (what we want)
  STO  → Stock Options
  IDF  → Index Futures
  IDO  → Index Options
"""

import io
import logging
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import requests

from configs.settings import (
    DATA_RAW_DIR,
    FO_UNIVERSE_CSV,
    REQUEST_TIMEOUT,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

_ARCHIVE_URL = (
    "https://nsearchives.nseindia.com/content/fo/"
    "BhavCopy_NSE_FO_0_0_0_{date}_F_0000.csv.zip"
)
_MAX_LOOKBACK = 7   # trading days to look back for latest available file
_MIN_ROWS     = 10  # minimum STF rows to consider a valid fetch


def fetch_oi_data() -> Tuple[pd.DataFrame, dict]:
    """
    Download NSE F&O Bhavcopy and return processed stock-futures OI DataFrame.

    Returns:
        (df, metadata)
        df: one row per F&O stock (near-month futures), columns:
            symbol, company_name, expiry_date, futures_price, prev_price,
            price_chg_pct, open_interest, oi_change, oi_chg_pct,
            volume_contracts, snapshot_date
        metadata: fetch result summary
    """
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

    check = date.today()
    for _ in range(_MAX_LOOKBACK * 2):          # 2× to skip weekends safely
        if check.weekday() >= 5:                # skip Sat/Sun
            check -= timedelta(days=1)
            continue

        raw, path = _download(check)
        if raw is not None:
            df = _process(raw)
            if len(df) >= _MIN_ROWS:
                logger.info(
                    "OI fetch success | date=%s stf_rows=%d",
                    check, len(df),
                )
                return df, {
                    "source":          "nse_fo_bhavcopy",
                    "snapshot_date":   str(check),
                    "rows_fetched":    len(raw),
                    "rows_processed":  len(df),
                    "raw_file":        str(path) if path else "",
                }
        check -= timedelta(days=1)

    logger.error("OI fetch failed — no valid bhavcopy in last %d trading days", _MAX_LOOKBACK)
    return pd.DataFrame(), {
        "source":         "none",
        "snapshot_date":  str(date.today()),
        "rows_fetched":   0,
        "rows_processed": 0,
        "error":          "No bhavcopy found",
    }


# ── Download & parse ──────────────────────────────────────────────────────────
def _download(d: date) -> Tuple[Optional[pd.DataFrame], Optional[Path]]:
    url = _ARCHIVE_URL.format(date=d.strftime("%Y%m%d"))
    headers = {
        "User-Agent": USER_AGENT,
        "Referer":    "https://www.nseindia.com/",
        "Accept":     "*/*",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            logger.debug("Bhavcopy not available | date=%s status=%d", d, resp.status_code)
            return None, None

        raw_path = DATA_RAW_DIR / f"fo_bhavcopy_{d.strftime('%Y%m%d')}.csv.zip"
        raw_path.write_bytes(resp.content)

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_files = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_files:
                logger.warning("No CSV inside bhavcopy ZIP for %s", d)
                return None, None
            with zf.open(csv_files[0]) as f:
                df = pd.read_csv(f, dtype=str)

        df.columns = [c.strip() for c in df.columns]
        logger.info("Bhavcopy loaded | date=%s total_rows=%d", d, len(df))
        return df, raw_path

    except requests.RequestException as e:
        logger.debug("Bhavcopy download error | date=%s: %s", d, e)
        return None, None
    except Exception as e:
        logger.warning("Bhavcopy parse error | date=%s: %s", d, e)
        return None, None


# ── Processing ────────────────────────────────────────────────────────────────
def _process(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter to stock futures (STF), select near-month expiry per symbol,
    compute price change % and OI change %.
    """
    if "FinInstrmTp" not in df.columns:
        logger.warning("Unexpected bhavcopy schema — FinInstrmTp column missing")
        return pd.DataFrame()

    # Filter to stock futures only
    stf = df[df["FinInstrmTp"].str.strip() == "STF"].copy()
    if stf.empty:
        logger.warning("No STF rows in bhavcopy")
        return pd.DataFrame()

    # Optional: filter to F&O universe (drops illiquid / newly added symbols)
    fo_syms = _load_fo_symbols()
    if fo_syms:
        stf = stf[stf["TckrSymb"].str.strip().str.upper().isin(fo_syms)]

    # Parse numerics
    num_cols = ["ClsPric", "PrvsClsgPric", "SttlmPric",
                "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol"]
    for col in num_cols:
        if col in stf.columns:
            stf[col] = pd.to_numeric(stf[col].astype(str).str.replace(",", ""),
                                     errors="coerce").fillna(0)

    # Parse expiry and keep near-month per symbol
    stf["XpryDt"] = pd.to_datetime(stf["XpryDt"], errors="coerce")
    stf = stf.dropna(subset=["XpryDt"])
    stf["_min_expiry"] = stf.groupby("TckrSymb")["XpryDt"].transform("min")
    stf = stf[stf["XpryDt"] == stf["_min_expiry"]].copy()

    # Aggregate (handles rare duplicate rows after filter)
    stf = stf.groupby("TckrSymb", as_index=False).agg(
        ClsPric=("ClsPric", "last"),
        PrvsClsgPric=("PrvsClsgPric", "last"),
        SttlmPric=("SttlmPric", "last"),
        OpnIntrst=("OpnIntrst", "sum"),
        ChngInOpnIntrst=("ChngInOpnIntrst", "sum"),
        TtlTradgVol=("TtlTradgVol", "sum"),
        XpryDt=("XpryDt", "first"),
        TradDt=("TradDt", "first"),
    )

    # Derived columns
    out = pd.DataFrame()
    out["symbol"]          = stf["TckrSymb"].str.strip().str.upper()
    out["expiry_date"]     = stf["XpryDt"].dt.strftime("%Y-%m-%d")
    out["snapshot_date"]   = pd.to_datetime(stf["TradDt"], errors="coerce").dt.strftime("%Y-%m-%d")

    # Use settlement price when available, else close
    out["futures_price"]   = stf["SttlmPric"].where(stf["SttlmPric"] > 0, stf["ClsPric"])
    out["prev_price"]      = stf["PrvsClsgPric"]

    # Price change % — PrvsClsgPric is in the file, no external history needed
    out["price_chg_pct"] = (
        (out["futures_price"] - out["prev_price"])
        / out["prev_price"].replace(0, float("nan"))
    ).fillna(0).mul(100).round(2)

    out["open_interest"]   = stf["OpnIntrst"].astype(int)
    out["oi_change"]       = stf["ChngInOpnIntrst"].astype(int)
    out["volume_contracts"] = stf["TtlTradgVol"].astype(int)

    # OI change % = CHG / (OI_now - CHG)  → CHG / prev_OI
    prev_oi = out["open_interest"] - out["oi_change"]
    out["oi_chg_pct"] = (
        out["oi_change"] / prev_oi.replace(0, float("nan"))
    ).fillna(0).mul(100).round(2)

    return out.reset_index(drop=True)


def _load_fo_symbols() -> set:
    if not FO_UNIVERSE_CSV.exists():
        return set()
    try:
        return set(
            pd.read_csv(FO_UNIVERSE_CSV)["symbol"]
            .astype(str).str.upper().str.strip()
        )
    except Exception as e:
        logger.warning("fo_universe.csv load error: %s", e)
        return set()
