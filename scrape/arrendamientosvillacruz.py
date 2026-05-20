"""Arrendamientos Villa Cruz (AVC) — Scroll-based Livewire scraper.

Uses StealthyFetcher + scroll to load all listings, then element-based
DOM parsing (Scrapling API, not BeautifulSoup) for field extraction."""

import logging
import re

from scrapling import StealthyFetcher

from scrape.normalize import (
    normalize_price,
    normalize_tipo,
    normalize_barrio,
)
from scrape.validator import validate

logger = logging.getLogger(__name__)

_URL = "https://www.arrendamientosvillacruz.com.co/resultados?gestion=Arriendo&tipo=Apartamentos-y-Apartaestudios-y-Casas-y-Casas+Locales-y-Casas+Fincas"
_PORTAL = "arrendamientosvillacruz"


def scroll_to_load_all(page):
    """Scroll to bottom repeatedly until listing count stops growing."""
    last = page.locator("text=COD:").count()
    while True:
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(2000)
        current = page.locator("text=COD:").count()
        if current == last:
            break
        last = current


def _parse_listings(resp) -> list[dict]:
    """Parse listing cards from Scrapling Response using element-based extraction.

    Scopes extraction to individual .estate_itm cards so sibling leakage
    and deeply nested blank lines don't break field extraction.
    """
    cards = resp.css('[class*="estate_itm"]:not([class*="estate_itm--"])')

    listings: list[dict] = []
    seen_ids: set[str] = set()

    for card in cards:
        text = card.get_all_text()
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        code = None
        for line in lines:
            m = re.search(r"COD:\s*(\d+)", line)
            if m:
                code = m.group(1)
                break

        if not code:
            continue

        listing_id = f"AVC-{code}"
        if listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)

        listing = {
            "id": listing_id,
            "portal": _PORTAL,
            "tipo": "",
            "precio": 0,
            "area": 0,
            "habitaciones": 0,
            "banos": 0,
            "parqueaderos": 0,
            "estrato": 0,
            "barrio": "",
            "url": _URL,
        }

        for k, line in enumerate(lines):
            if "Arriendo" in line and k + 1 < len(lines):
                listing["tipo"] = normalize_tipo(lines[k + 1])

            if "$" in line and not listing["precio"]:
                listing["precio"] = normalize_price(line)

            m = re.search(r"(\d+)\s*m²", line)
            if m:
                listing["area"] = int(m.group(1))
            elif k + 1 < len(lines) and lines[k + 1] == "m²" and line.isdigit():
                listing["area"] = int(line)

            m = re.search(r"(\d+)\s*Alcobas", line)
            if m:
                listing["habitaciones"] = int(m.group(1))

            m = re.search(r"(\d+)\s*Baños", line)
            if m:
                listing["banos"] = int(m.group(1))

            m = re.search(r"(\d+)\s*parq\.?", line)
            if m:
                listing["parqueaderos"] = int(m.group(1))

            if " - " in line and not listing["barrio"]:
                listing["barrio"] = normalize_barrio(line)

        listings.append(listing)

    return listings


def scrape(
    ciudad="medellin",
    sample_only=False,
    max_pages=None,
    verbose=False,
) -> list[dict]:
    """Scrape Arrendamientos Villa Cruz rental listings.

    Uses StealthyFetcher with scroll automation to load all cards,
    then extracts fields from the rendered HTML.

    Args:
        ciudad: City filter (used for output naming).
        sample_only: If True, log count and return without full validation.
        max_pages: Ignored for scroll-based portals.
        verbose: Detailed extraction logging.

    Returns:
        List of standardized 11-column listing dicts.
    """
    if verbose:
        logger.info("AVC: fetching page with scroll automation...")

    fetcher = StealthyFetcher()
    try:
        resp = fetcher.fetch(
            _URL,
            page_action=scroll_to_load_all,
            timeout=30000,
            retries=1,
        )
    except Exception as e:
        logger.error("AVC: failed to fetch page: %s", e)
        return []

    listings = _parse_listings(resp)

    if verbose:
        logger.info("AVC: %d listing(s) extracted", len(listings))

    for listing in listings:
        validate(listing)

    return listings
