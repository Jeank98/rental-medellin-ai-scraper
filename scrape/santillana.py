"""Santillana portal scraper — Two-Phase HTML Scraper.

Phase A: scrape listing cards from paginated search pages (5 fields).
Phase B: fetch detail pages for all listings and extract missing fields.
"""

import logging
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from scrape.fetcher import fetch_page, bulk_fetch
from scrape.normalize import (
    normalize_price,
    normalize_tipo,
    normalize_estrato,
    normalize_garaje,
    normalize_barrio,
    normalize_url,
)
from scrape.validator import validate

logger = logging.getLogger(__name__)

_BASE = "https://santillanasas.com"
_SEARCH_URL = (
    f"{_BASE}/search"
    "?simple=1-2-496"
    "&business_type%5B0%5D=for_rent"
    "&id_country=1"
    "&id_region=2"
    "&id_city=496"
    "&order_by=created_at"
    "&order=desc"
    "&for_sale=0"
    "&for_rent=1"
    "&for_temporary_rent=0"
    "&for_transfer=0"
    "&lax_business_type=1"
)

_COLUMNS = [
    "id", "portal", "tipo", "precio", "area",
    "habitaciones", "banos", "parqueaderos", "estrato",
    "barrio", "url",
]


def _page_url(page: int) -> str:
    if page <= 1:
        return _SEARCH_URL
    return f"{_BASE}/search?&page={page}"


def _code_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return path.split("/")[-1] if path else ""


def _parse_card(card) -> dict:
    listing = dict.fromkeys(_COLUMNS, "")
    listing["portal"] = "santillana"
    for key in ("precio", "area", "habitaciones", "banos", "parqueaderos", "estrato"):
        listing[key] = 0

    link = card.select_one("div.title h2 a[href]")
    if link:
        href = link.get("href", "")
        url = normalize_url(href, _BASE)
        listing["url"] = url
        listing["id"] = f"STL-{_code_from_url(url)}"

    for p in card.select(".body p"):
        text = p.get_text(strip=True)
        if text.startswith("Tipo:"):
            listing["tipo"] = normalize_tipo(text[len("Tipo:"):].strip())
            break

    price_span = card.select_one(".areaPrecio span")
    if price_span:
        listing["precio"] = normalize_price(price_span.get_text(strip=True))

    return listing


def _parse_detail(html: str) -> dict:
    fields: dict = {
        "area": 0,
        "habitaciones": 0,
        "banos": 0,
        "parqueaderos": 0,
        "estrato": 0,
        "barrio": "",
    }
    if not html:
        return fields

    soup = BeautifulSoup(html, "lxml")
    for li in soup.select("ul.list-li li"):
        text = li.get_text(strip=True)
        if text.startswith("Área Construida:"):
            val = text.split(":", 1)[1].strip()
            digits = "".join(c for c in val if c.isdecimal())
            if digits:
                fields["area"] = int(digits)
        elif text.startswith("Alcobas:"):
            val = text.split(":", 1)[1].strip()
            digits = "".join(c for c in val if c.isdecimal())
            if digits:
                fields["habitaciones"] = int(digits)
        elif text.startswith("Baños:") or text.startswith("Baño:"):
            val = text.split(":", 1)[1].strip()
            digits = "".join(c for c in val if c.isdecimal())
            if digits:
                fields["banos"] = int(digits)
        elif text.startswith("Garaje:"):
            val = text.split(":", 1)[1].strip()
            fields["parqueaderos"] = normalize_garaje(val)
        elif text.startswith("Estrato:"):
            val = text.split(":", 1)[1].strip()
            fields["estrato"] = normalize_estrato(val)
        elif text.startswith("Zona / barrio:"):
            val = text.split(":", 1)[1].strip()
            fields["barrio"] = normalize_barrio(val)

    return fields


def _fetch_all_pages(max_pages=None, verbose=False) -> list[dict]:
    listings: list[dict] = []
    page = 1

    while True:
        html = fetch_page(_page_url(page))
        if not html:
            logger.warning("Failed to fetch page %d, stopping", page)
            break

        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("div.item")
        if not cards:
            if verbose:
                logger.info("No cards on page %d, stopping", page)
            break

        for card in cards:
            listings.append(_parse_card(card))

        if verbose:
            logger.info("Page %d: %d cards, %d total", page, len(cards), len(listings))

        page += 1
        if max_pages is not None and page > max_pages:
            break

    return listings


def scrape(ciudad="medellin", sample_only=False, max_pages=None, verbose=False) -> list[dict]:
    if sample_only and max_pages is None:
        max_pages = 3

    anomalies: list[str] = []

    listings = _fetch_all_pages(max_pages=max_pages, verbose=verbose)
    if not listings:
        logger.warning("Phase A returned 0 listings")
        return []

    if verbose:
        logger.info("Phase A complete: %d listings", len(listings))

    if verbose:
        logger.info("Phase B: fetching %d detail pages", len(listings))

    detail_urls = [l["url"] for l in listings if l.get("url")]
    results = bulk_fetch(detail_urls)
    url_to_html = dict(results)

    for listing in listings:
        url = listing.get("url", "")
        if url and url in url_to_html:
            detail_fields = _parse_detail(url_to_html[url])
            listing.update(detail_fields)

        warnings = validate(listing)
        if warnings:
            anomalies.extend(warnings)
            if verbose:
                for w in warnings:
                    print(f"  [ANOMALY] {listing['id']} — {w}")

    if verbose:
        logger.info("Phase B complete: %d detail pages fetched", len(results))

    if anomalies:
        print(f"\n{len(anomalies)} anomaly(s) detected across {len(listings)} listings.")

    if sample_only:
        print(f"Sample: {len(listings)} listing(s) extracted")

    return listings
