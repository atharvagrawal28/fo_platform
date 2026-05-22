"""
pipeline/fetch.py
-----------------
File-based acquisition layer.

Production ingestion now uses official downloadable NSE/BSE CSV files:

  NSE corporate board meetings CSV
  BSE forthcoming results CSV

No headless-browser tooling, DOM scraping, or selector parsing is required for
normal production operation.
"""

from __future__ import annotations

import logging
import random
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

from configs.settings import (
    BACKOFF_BASE,
    BSE_FORTHCOMING_RESULTS_CSV_URL,
    BSE_FORTHCOMING_RESULTS_PAGE_URL,
    DATA_RAW_DIR,
    MAX_FUTURE_DAYS,
    MAX_RETRIES,
    NSE_BOARD_MEETINGS_CSV_URL,
    NSE_BOARD_MEETINGS_PAGE_URL,
    REQUEST_TIMEOUT,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

OUTPUT_COLS = ["result_date", "company_name", "symbol", "meeting_type", "source"]

# Keyword matching uses word boundaries — substring matches like "BUSINESS
# RESULTS" or "BUYBACK RESULT" were generating large amounts of noise.
# Each keyword is wrapped as a whole-word regex below.
RESULT_KEYWORDS = (
    "QUARTERLY RESULTS",
    "FINANCIAL RESULTS",
    "AUDITED RESULTS",
    "UNAUDITED RESULTS",
    "STANDALONE RESULTS",
    "CONSOLIDATED RESULTS",
    "QUARTERLY",
    "HALF YEARLY",
    "HALF-YEARLY",
    "ANNUAL RESULTS",
)

# Purposes that look superficially like results but are not earnings events.
# Anything matching one of these in absence of a clear results phrase is dropped.
NON_EARNINGS_PURPOSES = (
    "BUYBACK",
    "BUY BACK",
    "BUY-BACK",
    "RIGHTS ISSUE",
    "BONUS ISSUE",
    "PREFERENTIAL ISSUE",
    "DEBENTURES",
    "DEBENTURE",
    "FUND RAISING",
    "FUND-RAISING",
    "STOCK SPLIT",
    "SPLIT OF",
    "ALLOTMENT",
    # NOTE: "DIVIDEND" intentionally excluded — most "Results and Dividend"
    # entries are real earnings events. Standalone dividend-only meetings
    # are rare and tolerable noise.
    "POSTAL BALLOT",
    "EGM",
    "EXTRAORDINARY GENERAL MEETING",
    "ANNUAL GENERAL MEETING",
    "AGM",
    "SCHEME OF",
    "AMALGAMATION",
    "MERGER",
    "DEMERGER",
    "OFS",
    "QIP",
)

# Pre-compiled patterns (word-boundary, case-insensitive).
_RESULT_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in RESULT_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
_NON_EARNINGS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in NON_EARNINGS_PURPOSES) + r")\b",
    re.IGNORECASE,
)
# Bare "Results" / "Result" — accepted only when no non-earnings phrase is present.
# Avoids both false negatives ("Results and Dividend") and false positives
# ("Result of buyback tender").
_BARE_RESULTS_PATTERN = re.compile(r"\bRESULTS?\b", re.IGNORECASE)

CSV_ACCEPT = (
    "text/csv, application/csv, application/vnd.ms-excel, "
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, "
    "application/zip, */*"
)

DOWNLOAD_ATTEMPTS = max(1, min(MAX_RETRIES, 2))
MIN_DOWNLOAD_BYTES = 80


@dataclass(frozen=True)
class DownloadSpec:
    name: str
    source: str
    url: str
    referer: str
    params: dict[str, str]
    suffix: str = ".csv"
    origin: str | None = None


def fetch_earnings() -> tuple[pd.DataFrame, dict]:
    """
    Download official exchange files, parse them into the existing normalized
    dataframe contract, and return metadata consumed by pipeline/run.py.
    """
    start = datetime.now()
    raw_dir = _ensure_raw_dir()
    frames: list[pd.DataFrame] = []
    raw_files: list[str] = []
    failures: list[str] = []

    for spec in _download_specs():
        try:
            path = _download_with_retry(spec, raw_dir)
            raw_files.append(str(path))
            frames.append(_parse_file_for_source(path, spec))
        except Exception as exc:
            failures.append(f"{spec.name}: {_short_error(exc)}")
            logger.warning(
                "Official download/parser failed | source=%s error=%s",
                spec.source,
                _short_error(exc),
            )

            cached = _latest_raw_file(raw_dir, spec.name)
            if cached:
                try:
                    logger.info(
                        "Fallback transition | source=%s using latest local raw file=%s",
                        spec.source,
                        cached.name,
                    )
                    raw_files.append(str(cached))
                    frames.append(_parse_file_for_source(cached, spec))
                except Exception as cached_exc:
                    logger.warning(
                        "Cached raw file failed | source=%s file=%s error=%s",
                        spec.source,
                        cached.name,
                        _short_error(cached_exc),
                    )

    if not frames:
        duration = (datetime.now() - start).total_seconds()
        logger.error(
            "All official file sources failed after %.1fs. Last database snapshot is preserved.",
            duration,
        )
        raise RuntimeError(
            "Official file ingestion failed. Last valid data preserved in database. "
            + " | ".join(failures)
        )

    df = _standardize(pd.concat(frames, ignore_index=True))
    if df.empty:
        raise RuntimeError("Official files parsed successfully but produced zero dated result rows.")

    duration = (datetime.now() - start).total_seconds()
    logger.info(
        "Fetch success | source=official_files rows=%d duration_s=%.2f raw_files=%d",
        len(df),
        duration,
        len(raw_files),
    )
    return df, {
        "source": "official_files",
        "fallback_used": bool(failures),
        "rows_fetched": len(df),
        "fetch_duration_s": round(duration, 2),
        "raw_files": raw_files,
        "source_failures": failures,
    }


def _download_specs() -> list[DownloadSpec]:
    today = datetime.today().date()
    to_date = today + timedelta(days=MAX_FUTURE_DAYS)

    return [
        DownloadSpec(
            name="nse_board_meetings",
            source="nse_official_file",
            url=NSE_BOARD_MEETINGS_CSV_URL,
            referer=NSE_BOARD_MEETINGS_PAGE_URL,
            params={
                "index": "equities",
                "from_date": today.strftime("%d-%m-%Y"),
                "to_date": to_date.strftime("%d-%m-%Y"),
                "csv": "true",
            },
        ),
        DownloadSpec(
            name="bse_forthcoming_results",
            source="bse_official_file",
            url=BSE_FORTHCOMING_RESULTS_CSV_URL,
            referer=BSE_FORTHCOMING_RESULTS_PAGE_URL,
            params={"fromdate": "", "scripcode": "", "todate": ""},
            origin="https://www.bseindia.com",
        ),
    ]


def _ensure_raw_dir() -> Path:
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_RAW_DIR


def _download_with_retry(spec: DownloadSpec, raw_dir: Path) -> Path:
    last_exc: Exception | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            logger.info(
                "Official file download starting | source=%s attempt=%d/%d",
                spec.source,
                attempt,
                DOWNLOAD_ATTEMPTS,
            )
            return _download_file(spec, raw_dir)
        except Exception as exc:
            last_exc = exc
            if attempt >= DOWNLOAD_ATTEMPTS:
                break

            wait = min(5.0, (BACKOFF_BASE ** (attempt - 1)) + random.uniform(0.2, 0.8))
            logger.warning(
                "Official file download retry | source=%s attempt=%d/%d error=%s wait_s=%.1f",
                spec.source,
                attempt,
                DOWNLOAD_ATTEMPTS,
                _short_error(exc),
                wait,
            )
            time.sleep(wait)

    assert last_exc is not None
    raise last_exc


def _download_file(spec: DownloadSpec, raw_dir: Path) -> Path:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": CSV_ACCEPT,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": spec.referer,
        "Connection": "keep-alive",
    }
    if spec.origin:
        headers["Origin"] = spec.origin

    session = requests.Session()
    session.headers.update(headers)

    response = session.get(spec.url, params=spec.params, timeout=REQUEST_TIMEOUT)
    content_type = response.headers.get("content-type", "")
    logger.info(
        "Official file response | source=%s status=%s content_type=%s bytes=%d",
        spec.source,
        response.status_code,
        content_type,
        len(response.content),
    )
    response.raise_for_status()

    if len(response.content) < MIN_DOWNLOAD_BYTES:
        raise ValueError(f"{spec.source} returned too few bytes")

    body_start = response.content[:80].lstrip().lower()
    if body_start.startswith(b"<html") or body_start.startswith(b"<!doctype"):
        raise ValueError(f"{spec.source} returned HTML instead of a downloadable file")

    suffix = _suffix_from_response(response, spec.suffix)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = raw_dir / f"{spec.name}_{timestamp}{suffix}"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(response.content)
    tmp_path.replace(path)

    logger.info(
        "Official raw file saved | source=%s file=%s bytes=%d",
        spec.source,
        path,
        path.stat().st_size,
    )
    return path


def _suffix_from_response(response: requests.Response, default: str) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8''|\"?)([^\";]+)", disposition, re.I)
    if match:
        suffix = Path(match.group(1).strip()).suffix.lower()
        if suffix in {".csv", ".xlsx", ".zip"}:
            return suffix

    content_type = response.headers.get("content-type", "").lower()
    if "spreadsheet" in content_type:
        return ".xlsx"
    if "zip" in content_type:
        return ".zip"
    return default


def _latest_raw_file(raw_dir: Path, name: str) -> Path | None:
    candidates = [
        p for p in raw_dir.glob(f"{name}_*")
        if p.suffix.lower() in {".csv", ".xlsx", ".zip"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _parse_file_for_source(path: Path, spec: DownloadSpec) -> pd.DataFrame:
    raw_df = _read_structured_file(path)
    logger.info(
        "Raw file loaded | source=%s file=%s rows=%d cols=%d",
        spec.source,
        path.name,
        len(raw_df),
        len(raw_df.columns),
    )

    if spec.source == "nse_official_file":
        parsed = _parse_nse_board_meetings(raw_df, spec.source)
    elif spec.source == "bse_official_file":
        parsed = _parse_bse_forthcoming_results(raw_df, spec.source)
    else:
        raise ValueError(f"Unsupported official source: {spec.source}")

    logger.info(
        "Rows extracted | source=%s file=%s rows=%d",
        spec.source,
        path.name,
        len(parsed),
    )
    return parsed


def _read_structured_file(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return _read_zip_file(path)
    if suffix == ".xlsx":
        return pd.read_excel(path, engine="openpyxl")
    if suffix == ".csv":
        return _read_csv_file(path)
    raise ValueError(f"Unsupported raw file extension: {path.suffix}")


def _read_zip_file(path: Path) -> pd.DataFrame:
    extract_dir = path.parent / "extracted" / path.stem
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(path) as zf:
        members = [
            m for m in zf.namelist()
            if Path(m).suffix.lower() in {".csv", ".xlsx"}
            and not m.endswith("/")
        ]
        if not members:
            raise ValueError(f"No CSV/XLSX file found inside {path.name}")

        member = members[0]
        target = extract_dir / Path(member).name
        target.write_bytes(zf.read(member))
        logger.info("ZIP member extracted | zip=%s member=%s target=%s", path.name, member, target)
        return _read_structured_file(target)


def _read_csv_file(path: Path) -> pd.DataFrame:
    last_exc: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_exc = exc
        except pd.errors.ParserError:
            try:
                return pd.read_csv(
                    path,
                    encoding=encoding,
                    engine="python",
                    on_bad_lines="skip",
                )
            except Exception as exc:
                last_exc = exc
    assert last_exc is not None
    raise last_exc


def _parse_nse_board_meetings(df: pd.DataFrame, source: str) -> pd.DataFrame:
    d = _clean_dataframe(df)
    _require_any(d, "nse", ["symbol"], ["company_name"], ["meeting_date"])

    purpose = _text_series(d, "purpose")
    details = _text_series(d, "details")
    combined = (purpose + " " + details)

    is_result = combined.str.contains(_RESULT_PATTERN, regex=True, na=False)
    is_non_earnings = combined.str.contains(_NON_EARNINGS_PATTERN, regex=True, na=False)
    is_bare_results = combined.str.contains(_BARE_RESULTS_PATTERN, regex=True, na=False)

    # Keep rows that either (a) match an explicit results phrase, or
    # (b) mention "Results" without any non-earnings phrase. This admits
    # entries like "Results and Dividend" while still dropping "Result of
    # buyback tender" (the buyback keyword excludes it).
    mask = is_result | (is_bare_results & ~is_non_earnings)
    dropped_non_earnings = int((~mask & is_non_earnings).sum())
    if dropped_non_earnings:
        logger.info(
            "NSE filter | dropped %d non-earnings board meetings (buyback/rights/etc.)",
            dropped_non_earnings,
        )

    d = d[mask].copy()

    if d.empty:
        raise ValueError("NSE file contained no financial-results board-meeting rows")

    parsed = pd.DataFrame(
        {
            "result_date": _text_series(d, "meeting_date"),
            "company_name": _text_series(d, "company_name"),
            "symbol": _text_series(d, "symbol"),
            "meeting_type": purpose.reindex(d.index).fillna("Financial Results"),
            "source": source,
        }
    )

    # NSE sometimes lists the same board meeting twice when the purpose has
    # multiple agenda items. Collapse here so the rest of the pipeline never
    # sees the noise.
    before = len(parsed)
    parsed = parsed.drop_duplicates(
        subset=["result_date", "symbol", "company_name"], keep="first"
    )
    if before - len(parsed):
        logger.info("NSE intra-source dedup | dropped %d rows", before - len(parsed))

    return parsed


def _parse_bse_forthcoming_results(df: pd.DataFrame, source: str) -> pd.DataFrame:
    d = _clean_dataframe(df)
    _require_any(d, "bse", ["company_name"], ["result_date"], ["security_name", "symbol"])

    symbol_col = "security_name" if "security_name" in d.columns else "symbol"

    # BSE's forthcoming-results endpoint is mostly clean, but a few non-results
    # board meetings still leak through when the company sets a custom purpose.
    purpose_col = next(
        (c for c in ("purpose", "agenda", "remarks", "details") if c in d.columns),
        None,
    )
    if purpose_col:
        purpose = _text_series(d, purpose_col)
        is_result = purpose.str.contains(_RESULT_PATTERN, regex=True, na=False)
        is_non_earnings = purpose.str.contains(_NON_EARNINGS_PATTERN, regex=True, na=False)
        # If the column exists, prefer rows that mention results OR have an
        # empty purpose (BSE's default). Drop only rows whose purpose is clearly
        # non-earnings.
        mask = (purpose.str.strip() == "") | is_result | ~is_non_earnings
        dropped = int((~mask).sum())
        if dropped:
            logger.info("BSE filter | dropped %d non-earnings rows by purpose", dropped)
        d = d[mask].copy()
    else:
        purpose = pd.Series("Forthcoming Results", index=d.index)

    parsed = pd.DataFrame(
        {
            "result_date": _text_series(d, "result_date"),
            "company_name": _text_series(d, "company_name"),
            "symbol": _text_series(d, symbol_col),
            "meeting_type": purpose.reindex(d.index).fillna("Forthcoming Results"),
            "source": source,
        }
    )

    before = len(parsed)
    parsed = parsed.drop_duplicates(
        subset=["result_date", "symbol", "company_name"], keep="first"
    )
    if before - len(parsed):
        logger.info("BSE intra-source dedup | dropped %d rows", before - len(parsed))

    return parsed


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = _dedupe_columns(_clean_col(col) for col in d.columns)
    return d


def _clean_col(value: object) -> str:
    cleaned = str(value).replace("\ufeff", "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    return cleaned.strip("_")


def _dedupe_columns(columns: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for col in columns:
        base = col or "unnamed"
        count = seen.get(base, 0)
        result.append(base if count == 0 else f"{base}_{count}")
        seen[base] = count + 1
    return result


def _require_any(df: pd.DataFrame, label: str, *groups: list[str]) -> None:
    missing = ["/".join(group) for group in groups if not any(col in df.columns for col in group)]
    if missing:
        raise ValueError(f"{label} raw file missing required columns: {', '.join(missing)}")


def _text_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[column].fillna("").astype(str).str.strip()


def _standardize(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for col in OUTPUT_COLS:
        if col not in d.columns:
            d[col] = ""

    d["result_date"] = _parse_dates(d["result_date"])
    bad_dates = d["result_date"].isna().sum()
    if bad_dates:
        logger.warning("Dropping rows with invalid result_date | rows=%d", bad_dates)
        d = d.dropna(subset=["result_date"])

    d["company_name"] = d["company_name"].fillna("").astype(str).str.strip()
    d = d[d["company_name"].astype(bool)]

    d["symbol"] = (
        d["symbol"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.replace(r"\s+", "", regex=True)
        .str.strip()
    )
    d["meeting_type"] = d["meeting_type"].fillna("").astype(str).str.strip()
    d["meeting_type"] = d["meeting_type"].replace("", "Financial Results")
    d["source"] = d["source"].fillna("official_files").astype(str).str.strip()

    d = d.drop_duplicates(subset=["result_date", "company_name", "symbol"])
    logger.info("Standardized official file rows | rows=%d", len(d))
    return d[OUTPUT_COLS].reset_index(drop=True)


def _short_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:500]


def _parse_dates(values: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(values, dayfirst=True, errors="coerce", format="mixed")
    except TypeError:
        return pd.to_datetime(values, dayfirst=True, errors="coerce")
