"""Arrendamientos SantaFe (ASF) — Two-Phase HTML Scraper.

Phase A: Parse listing cards (.property-card) from search result pages.
Phase B: Fetch detail pages via bulk_fetch to extract banos + estrato.

Cards have 9 of 11 fields visible; banos and estrato require detail pages.
Detail pages are server-rendered Django — fast parallel fetch without JS.
"""

import logging
import re

from bs4 import BeautifulSoup

from scrape.fetcher import fetch_page, bulk_fetch
from scrape.normalize import (
    normalize_price,
    normalize_tipo,
    normalize_barrio,
    normalize_estrato,
    normalize_url,
)
from scrape.validator import validate

logger = logging.getLogger(__name__)

_BASE_URL = "https://arrendamientossantafe.com"
_SEARCH_URL = f"{_BASE_URL}/propiedades/"
_PAGE_PARAMS = "bussines_type=Arrendar"
_STALE_CODE = "A9692"
_PER_PAGE = 12

_COLUMNS = [
    "id", "portal", "tipo", "precio", "area",
    "habitaciones", "banos", "parqueaderos", "estrato",
    "barrio", "url",
]


def _page_url(page: int) -> str:
    return f"{_SEARCH_URL}?page={page}&{_PAGE_PARAMS}"


def _extract_card(card) -> dict:
    """Extract 9 available fields from a single .property-card element.

    Returns a dict with all 11 columns; banos and estrato default to 0
    (filled in Phase B from detail pages).
    """
    listing = dict.fromkeys(_COLUMNS, "")
    listing["portal"] = "arrendamientossantafe"
    for key in ("precio", "area", "habitaciones", "banos", "parqueaderos", "estrato"):
        listing[key] = 0

    # ID: span.id → "REF: A11248"
    id_span = card.select_one("span.id")
    if id_span:
        text = id_span.get_text(strip=True)
        if ":" in text:
            code = text.split(":")[-1].strip()
            if code:
                listing["id"] = f"ASF-{code}"

    # Tipo: p.tipo-inmueble → "Tipo: Apartamento"
    tipo_p = card.select_one("p.tipo-inmueble")
    if tipo_p:
        text = tipo_p.get_text(strip=True)
        raw = text.split(":", 1)[-1].strip() if ":" in text else text
        listing["tipo"] = normalize_tipo(raw)

    # Precio: div.precio p → "$1,600,000"
    precio_div = card.select_one("div.precio p")
    if precio_div:
        listing["precio"] = normalize_price(precio_div.get_text(strip=True))

    # Area: span.area → "55m²" or "55m2"
    area_span = card.select_one("span.area")
    if area_span:
        text = area_span.get_text(strip=True)
        # Extract digits before 'm' (handles both "55m²" and "55m2")
        digits = text.split('m')[0].strip()
        digits = ''.join(c for c in digits if c.isdecimal())
        if digits:
            listing["area"] = int(digits)

    # Habitaciones: span.alcobas → "2"
    hab_span = card.select_one("span.alcobas")
    if hab_span:
        text = hab_span.get_text(strip=True)
        digits = "".join(c for c in text if c.isdecimal())
        if digits:
            listing["habitaciones"] = int(digits)

    # Parqueaderos: span.garaje → "0"
    gar_span = card.select_one("span.garaje")
    if gar_span:
        text = gar_span.get_text(strip=True)
        digits = "".join(c for c in text if c.isdecimal())
        if digits:
            listing["parqueaderos"] = int(digits)

    # Barrio: .sector p.d-inline → "Ubicación: Cristo Rey"
    sector_p = card.select_one(".sector p.d-inline")
    if sector_p:
        text = sector_p.get_text(strip=True)
        raw = text.split(":", 1)[-1].strip() if ":" in text else text
        listing["barrio"] = normalize_barrio(raw)

    # URL: .inner-card a[href] → prepend domain
    link = card.select_one(".inner-card a[href]")
    if link:
        href = link.get("href", "")
        listing["url"] = normalize_url(href, _BASE_URL)

    return listing


def _parse_search_page(html: str) -> list[dict]:
    """Parse all valid listing cards from one search result page."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".property-card")
    listings = []
    for card in cards:
        listing = _extract_card(card)
        # Filter stale placeholder cards served beyond the real last page
        if _STALE_CODE in listing.get("id", ""):
            continue
        listings.append(listing)
    return listings


def _extract_detail_banos(html: str) -> int:
    """Extract banos count from a detail page's Caracteristicas section."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ")
    m = re.search(r"Ba[ñn]os?\s*:?\s*(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 0


def _extract_detail_estrato(html: str) -> int:
    """Extract estrato from a detail page's Interior section."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ")
    m = re.search(r"Estrato\s*:?\s*(\d+)", text, re.IGNORECASE)
    if m:
        return normalize_estrato(int(m.group(1)))
    return 0


def _phase_b(listings: list[dict], verbose: bool = False) -> list[dict]:
    """Phase B: bulk-fetch detail pages, extract banos + estrato, merge.

    Uses fetcher.bulk_fetch (ThreadPoolExecutor) for parallel HTTP.
    Failed pages leave card defaults (0) intact.
    """
    urls = [l["url"] for l in listings if l["url"]]
    if not urls:
        return listings

    if verbose or True:  # always show progress
        logger.info("ASF Phase B: fetching %d detail pages...", len(urls))

    # Suppress Scrapling's per-request INFO logs during bulk fetch
    import scrapling
    old_level = logging.getLogger("scrapling").level
    logging.getLogger("scrapling").setLevel(logging.WARNING)
    
    results = bulk_fetch(urls)
    
    logging.getLogger("scrapling").setLevel(old_level)
    detail_map = dict(results)

    banos_set = 0
    estrato_set = 0

    for listing in listings:
        html = detail_map.get(listing["url"], "")
        if not html:
            continue
        banos = _extract_detail_banos(html)
        estrato = _extract_detail_estrato(html)
        if banos:
            listing["banos"] = banos
            banos_set += 1
        if estrato:
            listing["estrato"] = estrato
            estrato_set += 1

    if verbose:
        logger.info(
            "ASF Phase B: banos=%d/%d non-zero, estrato=%d/%d non-zero",
            banos_set, len(listings), estrato_set, len(listings),
        )

    return listings


def scrape(
    ciudad="medellin", sample_only=False, max_pages=None, verbose=False
) -> list[dict]:
    """Scrape Arrendamientos SantaFe rental listings (two-phase).

    Phase A: Binary-search last page, then bulk_fetch all search pages
             in parallel (32 workers). Extracts 9 card-level fields.
    Phase B: bulk-fetch all detail pages for banos + estrato.
    """
    if sample_only and max_pages is None:
        max_pages = 3

    listings: list[dict] = []
    anomalies: list[str] = []

    # --- Phase A: Discover last page + parallel fetch ---
    # Step 1: Request page=9999 to discover the real last page
    # The server redirects to the last valid page; pagination shows the number
    html = fetch_page(_page_url(9999))
    last_page = 1
    if html:
        soup = BeautifulSoup(html, "lxml")
        current_el = soup.select_one(".current, .pager-position.current, li.current")
        if current_el:
            text = current_el.get_text(strip=True)
            if text.isdecimal():
                last_page = int(text)
    if last_page <= 1:
        last_page = 1  # fallback

    if max_pages is not None:
        last_page = min(last_page, max_pages)

    if verbose:
        logger.info("ASF: %d search pages — fetching in parallel...", last_page)

    # Step 2: Generate all page URLs and bulk_fetch in parallel
    page_urls = [_page_url(p) for p in range(1, last_page + 1)]
    page_results = bulk_fetch(page_urls)

    # Step 3: Parse all pages
    for url, html in page_results:
        if not html:
            continue
        page_listings = _parse_search_page(html)
        for listing in page_listings:
            listings.append(listing)
            warnings = validate(listing)
            if warnings:
                anomalies.extend(warnings)
                if verbose:
                    for w in warnings:
                        print(f"  [ANOMALY] {listing['id']} — {w}")

    if verbose:
        logger.info("ASF Phase A: %d listings from %d pages", len(listings), last_page)

    if not listings:
        return []

    # --- Phase B: Detail pages ---
    listings = _phase_b(listings, verbose=verbose)

    if sample_only:
        print(f"Sample: {len(listings)} listing(s) extracted")

    if anomalies:
        print(
            f"\n{len(anomalies)} anomaly(s) detected"
            f" across {len(listings)} listings."
        )

    return listings
