"""Reusable web fetch and HTML/JSON crawl helpers for downloader scripts.

This module centralizes request retry logic, JSON pagination, and embedded JSON
extraction from HTML pages so downloaders can prefer live fetch/crawl behavior
and avoid manual offline data dependencies.
"""

import json
import re
import time
from typing import Any

import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ContractSweeper/1.0; +https://github.com/jotaele44/Contract-Sweeper)",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9,es-PR;q=0.8",
}
DEFAULT_TIMEOUT = 30
DEFAULT_RETRY_BACKOFF = [2, 5, 15]
DEFAULT_MAX_RETRIES = 3

_JSON_VAR_PATTERNS = [
    r"window\.__DATA__\s*=\s*(\{)",
    r"window\.__INITIAL_STATE__\s*=\s*(\{)",
    r"window\.__PRELOADED_STATE__\s*=\s*(\{)",
    r"var\s+data\s*=\s*(\{)",
    r"dataLayer\s*=\s*(\[)",
]


def session_with_headers(headers: dict[str, str] | None = None) -> requests.Session:
    s = requests.Session()
    headers = headers or {}
    base = DEFAULT_HEADERS.copy()
    base.update(headers)
    s.headers.update(base)
    return s


def http_get(
    session: requests.Session,
    url: str,
    params: dict[str, Any] | None = None,
    logger=None,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff: list[int] | None = None,
    allow_redirects: bool = True,
    accept_html: bool = False,
) -> requests.Response | None:
    backoff = backoff or DEFAULT_RETRY_BACKOFF
    for attempt in range(max_retries):
        try:
            resp = session.get(url, params=params, timeout=timeout, allow_redirects=allow_redirects)
            if 400 <= resp.status_code < 500:
                if logger is not None:
                    logger.warning(f"  HTTP {resp.status_code} for {url}")
                return None
            if resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} server error")
            return resp
        except requests.RequestException as exc:
            if attempt + 1 < max_retries:
                wait = backoff[min(attempt, len(backoff) - 1)]
                if logger is not None:
                    logger.warning(f"  Request failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                if logger is not None:
                    logger.error(f"  Request failed: {exc}")
    return None


def http_post(
    session: requests.Session,
    url: str,
    json_payload: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    logger=None,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff: list[int] | None = None,
) -> requests.Response | None:
    backoff = backoff or DEFAULT_RETRY_BACKOFF
    for attempt in range(max_retries):
        try:
            resp = session.post(url, json=json_payload, data=data, timeout=timeout)
            if 400 <= resp.status_code < 500:
                if logger is not None:
                    logger.warning(f"  HTTP {resp.status_code} for {url}")
                return None
            if resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} server error")
            return resp
        except requests.RequestException as exc:
            if attempt + 1 < max_retries:
                wait = backoff[min(attempt, len(backoff) - 1)]
                if logger is not None:
                    logger.warning(f"  Request failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                if logger is not None:
                    logger.error(f"  Request failed: {exc}")
    return None


def _try_parse_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_embedded_json(text: str, logger=None) -> Any | None:
    """Extract JSON embedded in HTML or script tags from a page."""
    for pattern in _JSON_VAR_PATTERNS:
        match = re.search(pattern, text, flags=re.DOTALL)
        if not match:
            continue
        start_char = match.group(1)
        start = match.start(1)
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            char = text[idx]
            if char == '"' and not escape:
                in_string = not in_string
            if in_string and char == '\\' and not escape:
                escape = True
                continue
            escape = False
            if in_string:
                continue
            if char == '{' or char == '[':
                depth += 1
            elif char == '}' or char == ']':
                depth -= 1
                if depth == 0:
                    candidate = text[start:idx + 1]
                    parsed = _try_parse_json(candidate)
                    if parsed is not None:
                        return parsed
                    break
    if logger is not None:
        logger.debug("  Embedded JSON extraction failed")
    return None


def find_json_list(data: Any, keys: list[str] | None = None) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    if keys is None:
        keys = ["data", "results", "items", "contracts", "projects", "records"]
    for key in keys:
        if key in data and isinstance(data[key], list):
            return data[key]
    return []


def fetch_paginated_json(
    session: requests.Session,
    url: str,
    params: dict[str, Any] | None = None,
    page_param: str = "page",
    page_size_param: str = "per_page",
    page_size: int = 100,
    max_pages: int = 200,
    logger=None,
    items_keys: list[str] | None = None,
) -> list[dict]:
    results: list[dict] = []
    params = params.copy() if params else {}
    params[page_size_param] = page_size
    for page in range(1, max_pages + 1):
        params[page_param] = page
        resp = http_get(session, url, params=params, logger=logger)
        if resp is None or resp.status_code >= 400:
            break
        try:
            data = resp.json()
        except ValueError:
            break
        page_items = find_json_list(data, items_keys)
        if not page_items:
            break
        results.extend(page_items)
        if len(page_items) < page_size:
            break
        if logger is not None and page % 20 == 0:
            logger.info(f"  Page {page}: {len(results):,} records")
    return results


def extract_json_from_html_page(session: requests.Session, url: str, logger=None) -> Any | None:
    resp = http_get(session, url, logger=logger)
    if resp is None or resp.status_code >= 400:
        return None
    return parse_embedded_json(resp.text, logger=logger)
