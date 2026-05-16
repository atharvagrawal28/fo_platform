"""
pipeline/fetch.py
-----------------
Acquisition layer only.

Fetch order:
  1. NSE Playwright browser context + internal JSON API
  2. NSE requests fallback + internal JSON API
  3. BSE Playwright + real Corpforthresults JSON API
  4. BSE requests fallback + real Corpforthresults JSON API
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from typing import Any, Callable

import pandas as pd
import requests

from configs.settings import (
    BACKOFF_BASE,
    MAX_RETRIES,
    NSE_API_URL,
    NSE_HOME_URL,
    NSE_PREFETCH_URL,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

REALISTIC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

CHROMIUM_ARGS = [
    "--disable-http2",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
]

PLAYWRIGHT_TIMEOUT_MS = 60_000
NSE_HOME_TIMEOUT_MS = 15_000
HUMAN_WAIT_MS = 3_000

BSE_PAGE_URL = "https://www.bseindia.com/corporates/Forth_Results.html?expandable=3"
BSE_API_URL = "https://api.bseindia.com/BseIndiaAPI/api/Corpforthresults/w"

RESULT_KEYWORDS = (
    "RESULT",
    "FINANCIAL",
    "QUARTERLY",
    "ANNUAL",
    "AUDITED",
    "UNAUDITED",
)

REQUEST_HEADERS = {
    "User-Agent": REALISTIC_USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

OUTPUT_COLS = ["result_date", "company_name", "symbol", "meeting_type", "source"]

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || { runtime: {} };
"""


def fetch_earnings() -> tuple[pd.DataFrame, dict]:
    start = datetime.now()
    fallback_used = False

    sources: list[tuple[Callable[[], pd.DataFrame], str, int]] = [
        (_fetch_nse_playwright, "nse_playwright", 1),
        (_fetch_nse_requests, "nse_requests", 2),
        (_fetch_bse_playwright, "bse_playwright", 1),
        (_fetch_bse_requests, "bse_requests", 2),
    ]

    for index, (fn, label, attempts) in enumerate(sources):
        if index:
            logger.info("Fallback transition | trying source=%s", label)

        try:
            df = _with_retry(fn, label, attempts)
            if df is None or df.empty:
                raise ValueError(f"{label} returned no rows")

            df = _standardize(df, label)
            if df.empty:
                raise ValueError(f"{label} returned no parseable dated rows")

            duration = (datetime.now() - start).total_seconds()
            logger.info(
                "Fetch success | source=%s rows=%d duration_s=%.2f",
                label,
                len(df),
                duration,
            )
            return df, {
                "source": label,
                "fallback_used": fallback_used,
                "rows_fetched": len(df),
                "fetch_duration_s": round(duration, 2),
            }
        except Exception as exc:
            logger.warning("source=%s failed: %s", label, _short_error(exc))
            fallback_used = True

    duration = (datetime.now() - start).total_seconds()
    logger.error(
        "All fetch sources failed after %.1fs. Last valid database snapshot is preserved.",
        duration,
    )
    raise RuntimeError(
        "All fetch sources failed. Last valid data preserved in database."
    )


def _with_retry(fn: Callable[[], pd.DataFrame], label: str, attempts: int) -> pd.DataFrame:
    attempts = max(1, min(attempts, MAX_RETRIES))
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            logger.info("source=%s attempt=%d/%d starting", label, attempt, attempts)
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts:
                break

            wait = min(5.0, (BACKOFF_BASE ** (attempt - 1)) + random.uniform(0.2, 0.8))
            logger.warning(
                "source=%s attempt=%d/%d failed: %s | retrying in %.1fs",
                label,
                attempt,
                attempts,
                _short_error(exc),
                wait,
            )
            time.sleep(wait)

    assert last_exc is not None
    raise last_exc


def _fetch_nse_playwright() -> pd.DataFrame:
    """
    NSE: create a realistic browser context, try homepage briefly, then fetch
    the internal JSON API from the browser context. Do not navigate to the
    board-meetings page because it often hangs.
    """
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        logger.info("NSE browser launched")

        try:
            context = browser.new_context(
                user_agent=REALISTIC_USER_AGENT,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
            )
            context.set_extra_http_headers(BROWSER_HEADERS)
            context.add_init_script(STEALTH_INIT_SCRIPT)
            logger.info("NSE context created")

            page = context.new_page()
            page.set_default_timeout(PLAYWRIGHT_TIMEOUT_MS)
            page.set_default_navigation_timeout(PLAYWRIGHT_TIMEOUT_MS)

            logger.info("NSE page loading | stage=homepage url=%s", NSE_HOME_URL)
            try:
                page.goto(
                    NSE_HOME_URL,
                    wait_until="domcontentloaded",
                    timeout=NSE_HOME_TIMEOUT_MS,
                )
                logger.info("NSE page loaded | stage=homepage")
                page.wait_for_timeout(HUMAN_WAIT_MS)
                logger.info("NSE human-like wait complete | ms=%d", HUMAN_WAIT_MS)
            except PlaywrightError as exc:
                logger.warning("NSE homepage load issue: %s", _short_error(exc))

            logger.info("NSE browser context JSON GET | url=%s", NSE_API_URL)
            payload = _browser_context_json_get(context, NSE_API_URL, "NSE")
            rows = _parse_nse_rows(_payload_records(payload), "nse_playwright")
            logger.info("NSE rows extracted | rows=%d", len(rows))
            return rows
        finally:
            browser.close()
            logger.info("NSE browser closed")


def _fetch_nse_requests() -> pd.DataFrame:
    payload = _requests_json_get(NSE_API_URL, "NSE", referer=NSE_PREFETCH_URL)
    rows = _parse_nse_rows(_payload_records(payload), "nse_requests")
    logger.info("NSE rows extracted | source_url=%s rows=%d", NSE_API_URL, len(rows))
    return rows


def _fetch_bse_playwright() -> pd.DataFrame:
    """
    BSE live Angular flow:
      page: https://www.bseindia.com/corporates/Forth_Results.html?expandable=3
      API:  https://api.bseindia.com/BseIndiaAPI/api/Corpforthresults/w
    """
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    captured: list[tuple[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        logger.info("BSE browser launched")

        try:
            context = browser.new_context(
                user_agent=REALISTIC_USER_AGENT,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
            )
            context.set_extra_http_headers(
                {
                    **BROWSER_HEADERS,
                    "Origin": "https://www.bseindia.com",
                    "Referer": BSE_PAGE_URL,
                }
            )
            context.add_init_script(STEALTH_INIT_SCRIPT)
            logger.info("BSE context created")

            page = context.new_page()
            page.set_default_timeout(PLAYWRIGHT_TIMEOUT_MS)
            page.set_default_navigation_timeout(PLAYWRIGHT_TIMEOUT_MS)

            def on_response(response):
                if "/Corpforthresults/w" not in response.url or response.status != 200:
                    return
                try:
                    data = response.json()
                    captured.append((response.url, data))
                    logger.info(
                        "BSE XHR captured | url=%s rows=%d",
                        response.url,
                        len(_payload_records(data)),
                    )
                except Exception as exc:
                    logger.debug("BSE XHR JSON parse failed: %s", exc)

            page.on("response", on_response)

            logger.info("BSE page loading | url=%s", BSE_PAGE_URL)
            try:
                page.goto(
                    BSE_PAGE_URL,
                    wait_until="networkidle",
                    timeout=PLAYWRIGHT_TIMEOUT_MS,
                )
                logger.info("BSE page loaded")
                page.wait_for_timeout(HUMAN_WAIT_MS)
                logger.info("BSE human-like wait complete | ms=%d", HUMAN_WAIT_MS)
            except PlaywrightError as exc:
                logger.warning("BSE page load issue: %s", _short_error(exc))

            if captured:
                payload_url, payload = max(
                    captured,
                    key=lambda item: len(_payload_records(item[1])),
                )
                logger.info("BSE selected JSON payload | url=%s", payload_url)
            else:
                logger.info("BSE XHR not captured naturally; using browser context JSON")
                payload = _browser_context_json_get(
                    context,
                    BSE_API_URL,
                    "BSE",
                    extra_headers={
                        "Origin": "https://www.bseindia.com",
                        "Referer": BSE_PAGE_URL,
                    },
                )

            rows = _parse_bse_rows(_payload_records(payload), "bse_playwright")
            logger.info("BSE rows extracted | rows=%d", len(rows))
            return rows
        finally:
            browser.close()
            logger.info("BSE browser closed")


def _fetch_bse_requests() -> pd.DataFrame:
    payload = _requests_json_get(
        BSE_API_URL,
        "BSE",
        referer=BSE_PAGE_URL,
        extra_headers={"Origin": "https://www.bseindia.com"},
    )
    rows = _parse_bse_rows(_payload_records(payload), "bse_requests")
    logger.info("BSE rows extracted | source_url=%s rows=%d", BSE_API_URL, len(rows))
    return rows


def _browser_context_json_get(
    context: Any,
    url: str,
    label: str,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    headers = dict(REQUEST_HEADERS)
    if extra_headers:
        headers.update(extra_headers)

    response = context.request.get(url, headers=headers, timeout=PLAYWRIGHT_TIMEOUT_MS)
    logger.info(
        "%s browser context response | status=%s content_type=%s",
        label,
        response.status,
        response.headers.get("content-type", ""),
    )
    if response.status >= 400:
        raise ValueError(f"{label} browser context JSON GET failed: HTTP {response.status}")
    return response.json()


def _requests_json_get(
    url: str,
    label: str,
    referer: str,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    headers = {**REQUEST_HEADERS, "Referer": referer}
    if extra_headers:
        headers.update(extra_headers)

    session = requests.Session()
    session.headers.update(headers)

    time.sleep(random.uniform(0.4, 1.2))
    logger.info("%s requests JSON GET | url=%s", label, url)
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    logger.info(
        "%s requests response | status=%s content_type=%s bytes=%d",
        label,
        response.status_code,
        response.headers.get("content-type", ""),
        len(response.content),
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    body_start = response.text.lstrip()[:1]
    if "json" not in content_type and body_start not in {"[", "{"}:
        raise ValueError(
            f"{label} requests expected JSON but got content-type={content_type!r}"
        )

    return response.json()


def _payload_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]

    if isinstance(payload, dict):
        for key in ("data", "Table", "results", "Table1"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]

        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value

    return []


def _parse_nse_rows(records: list[dict[str, Any]], source: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for item in records:
        purpose = _first_text(item, "purpose", "bm_desc", "eventName", "event")
        description = _first_text(item, "bm_desc", "description", "details")
        result_text = f"{purpose} {description}".upper()
        if not any(keyword in result_text for keyword in RESULT_KEYWORDS):
            continue

        result_date = _first_text(
            item,
            "date",
            "bm_date",
            "bmDate",
            "meeting_date",
            "meetingDate",
        )
        company_name = _first_text(item, "company", "companyName", "nm", "name")
        symbol = _first_text(item, "symbol", "sym", "scripCode", "scrip_code")

        if not result_date or not company_name:
            continue

        rows.append(
            {
                "result_date": result_date,
                "company_name": company_name,
                "symbol": symbol.upper(),
                "meeting_type": purpose or "Financial Results",
                "source": source,
            }
        )

    logger.info("NSE parser | raw_rows=%d result_rows=%d", len(records), len(rows))
    if not rows:
        raise ValueError("NSE JSON captured but zero results-related rows found")

    return pd.DataFrame(rows)


def _parse_bse_rows(records: list[dict[str, Any]], source: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for item in records:
        result_date = _first_text(
            item,
            "meeting_date",
            "MEETING_DATE",
            "Date",
            "result_date",
        )
        company_name = _first_text(
            item,
            "Long_Name",
            "long_name",
            "COMPANY_NAME",
            "Company",
            "short_name",
        )
        symbol = _first_text(
            item,
            "short_name",
            "Symbol",
            "SCRIP_ID",
            "scrip_id",
            "scrip_Code",
            "SCRIP_CD",
        )

        if not result_date or not company_name:
            continue

        rows.append(
            {
                "result_date": result_date,
                "company_name": company_name,
                "symbol": symbol.upper(),
                "meeting_type": "Forthcoming Results",
                "source": source,
            }
        )

    logger.info("BSE parser | raw_rows=%d result_rows=%d", len(records), len(rows))
    if not rows:
        raise ValueError("BSE JSON captured but zero forthcoming-results rows found")

    return pd.DataFrame(rows)


def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _short_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:500]


def _standardize(df: pd.DataFrame, source: str) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    rename = {
        "board_meeting_date": "result_date",
        "date": "result_date",
        "meeting_date": "result_date",
        "bm_date": "result_date",
        "company": "company_name",
        "name": "company_name",
        "short_name": "company_name",
        "long_name": "company_name",
        "scrip_name": "company_name",
        "purpose": "meeting_type",
        "agenda": "meeting_type",
        "scrip_cd": "symbol",
        "scrip_code": "symbol",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    for col in OUTPUT_COLS:
        if col not in df.columns:
            df[col] = "" if col != "source" else source

    df["result_date"] = pd.to_datetime(
        df["result_date"],
        dayfirst=True,
        errors="coerce",
    )
    df = df.dropna(subset=["result_date"])
    df["company_name"] = df["company_name"].astype(str).str.strip()
    df = df[df["company_name"].astype(bool)]
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    df["meeting_type"] = df["meeting_type"].astype(str).str.strip()
    df["source"] = source

    logger.info("Standardized rows | source=%s rows=%d", source, len(df))
    return df[OUTPUT_COLS].reset_index(drop=True)