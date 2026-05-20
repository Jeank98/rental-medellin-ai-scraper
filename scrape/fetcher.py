"""Fetcher wrappers — Scrapling Python API with retry logic.

Provides fetch_page(), fetch_json(), and bulk_fetch() with exponential
backoff retries for all 12 Colombian real estate portal scrapers.

Uses scrapling.Fetcher for server-rendered pages and REST APIs,
and scrapling.StealthyFetcher for Load More portals (Coninsa, VillaCruz).
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, List, Optional, Tuple, Union

import scrapling

logger = logging.getLogger(__name__)

# Retry configuration
_MAX_RETRIES = 3  # number of retry attempts (4 total with initial)
_RETRY_DELAYS = [1, 2, 4]  # seconds between retries
_TIMEOUT = 30  # seconds per request attempt
_BULK_CHUNK_SIZE = 200
_MAX_BULK_WORKERS = 20


def fetch_page(url: str, method: str = "get") -> Optional[str]:
    """Fetch a server-rendered page using Scrapling Fetcher.

    Args:
        url: The URL to fetch.
        method: HTTP method — 'get' (default) uses Fetcher.get().

    Returns:
        Page HTML content as string, or None if all retries are exhausted.
    """
    fetcher = scrapling.Fetcher()

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = fetcher.get(url, timeout=_TIMEOUT, retries=1)


            if resp.status >= 400:
                if resp.status < 500:
                    logger.warning("HTTP %s for %s — not retrying (client error)", resp.status, url)
                    return None
                logger.warning(
                    "HTTP %s for %s (attempt %d/%d)",
                    resp.status,
                    url,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                )
            else:
                return resp.html_content or ""

        except Exception as e:
            logger.warning(
                "Fetch error for %s: %s (attempt %d/%d)",
                url,
                e,
                attempt + 1,
                _MAX_RETRIES + 1,
            )

        if attempt < _MAX_RETRIES:
            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
            logger.debug("Retrying %s in %ds...", url, delay)
            time.sleep(delay)

    logger.error("All %d attempts exhausted for %s", _MAX_RETRIES + 1, url)
    return None


def fetch_json(
    url: str, headers: Optional[dict[str, str]] = None
) -> Union[dict, list, None]:
    """Fetch a JSON REST API endpoint using Scrapling Fetcher.

    Args:
        url: The API URL to fetch.
        headers: Optional HTTP headers dict.

    Returns:
        Parsed dict or list from JSON response, or None on failure.
    """
    fetcher = scrapling.Fetcher()
    extras: dict[str, Any] = {}
    if headers:
        extras["headers"] = headers

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = fetcher.get(url, timeout=_TIMEOUT, retries=1, **extras)

            if resp.status >= 400:
                if resp.status < 500:
                    logger.warning("HTTP %s for %s — not retrying (client error)", resp.status, url)
                    return None
                logger.warning(
                    "HTTP %s for %s (attempt %d/%d)",
                    resp.status,
                    url,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                )
            else:
                data = resp.json()
                if isinstance(data, (dict, list)):
                    return data
                logger.error("Unexpected JSON type for %s: %s — NOT retrying", url, type(data).__name__)
                return None

        except Exception as e:
            logger.warning(
                "JSON fetch error for %s: %s (attempt %d/%d)",
                url,
                e,
                attempt + 1,
                _MAX_RETRIES + 1,
            )

        if attempt < _MAX_RETRIES:
            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
            logger.debug("Retrying %s in %ds...", url, delay)
            time.sleep(delay)

    logger.error("All %d attempts exhausted for %s", _MAX_RETRIES + 1, url)
    return None


def _fetch_single(url: str) -> Tuple[str, str]:
    """Fetch a single URL and return a (url, text) tuple.

    Used as a worker by bulk_fetch. Returns empty string on failure.
    """
    result = fetch_page(url)
    return (url, result if result is not None else "")


def bulk_fetch(urls: List[str]) -> List[Tuple[str, str]]:
    """Fetch multiple URLs concurrently using a thread pool.

    Args:
        urls: List of URLs to fetch.

    Returns:
        List of (url, html_content) tuples — same length as input.
        Failed URLs have empty string as content. Returns empty list
        for empty input.
    """
    if not urls:
        return []

    total = len(urls)
    results: List[Tuple[str, str]] = []

    # Process in chunks of _BULK_CHUNK_SIZE for memory efficiency
    for chunk_start in range(0, total, _BULK_CHUNK_SIZE):
        chunk = urls[chunk_start : chunk_start + _BULK_CHUNK_SIZE]
        workers = min(_MAX_BULK_WORKERS, len(chunk))
        logger.info(
            "Bulk fetching %d URLs (chunk %d-%d/%d) with %d workers",
            len(chunk),
            chunk_start + 1,
            min(chunk_start + _BULK_CHUNK_SIZE, total),
            total,
            workers,
        )

        chunk_results: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_url = {
                executor.submit(_fetch_single, url): url for url in chunk
            }
            for future in as_completed(future_to_url):
                url, content = future.result()
                chunk_results[url] = content

        # Preserve input order
        for url in chunk:
            results.append((url, chunk_results.get(url, "")))

    return results


def stealthy_fetch_with_action(
    url: str, page_action_fn: Callable
) -> Optional[str]:
    """Fetch a page with Playwright interactions (Load More portals).

    Uses scrapling.StealthyFetcher to load the page, then executes the
    provided callback for Playwright page actions (clicks, scrolls).
    Returns the full page content after all interactions complete.

    Args:
        url: The URL to load.
        page_action_fn: A callable that receives a Playwright Page
            object and performs interactions (e.g. clicking Load More).

    Returns:
        Full HTML content after interactions, or None on failure.
    """
    fetcher = scrapling.StealthyFetcher()

    try:
        resp = fetcher.fetch(
            url,
            page_action=page_action_fn,
            timeout=_TIMEOUT * 1000,
            retries=1,
        )
        return resp.html_content or ""

    except Exception as e:
        logger.error("Stealthy fetch error for %s: %s", url, e)
        return None
