"""Maxibienes portal scraper — Single-Phase HTML Scraper.

All 11 fields are on listing cards. Uses BeautifulSoup for CSS selector-based
extraction from server-rendered PHP pages with standard pagination.
"""

import logging
import re
from bs4 import BeautifulSoup
from scrape.fetcher import fetch_page
from scrape.normalize import (
    normalize_price,
    normalize_tipo,
    normalize_barrio,
    normalize_estrato,
    normalize_url,
)
from scrape.validator import validate

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.maxibienes.com/resultados-de-la-busqueda-de-inmueble/"
_QUERY = "gestion=1&ciudad=5001"

# FontAwesome icon → field key mapping
_ICON_FIELD = {
    'fa-compress': 'area',
    'fa-bed': 'habitaciones',
    'fa-bath': 'banos',
    'fa-warehouse': 'parqueaderos',
}

_COLUMNS = [
    'id', 'portal', 'tipo', 'precio', 'area',
    'habitaciones', 'banos', 'parqueaderos', 'estrato',
    'barrio', 'url',
]


def _page_url(page: int) -> str:
    if page <= 1:
        return f"{_BASE_URL}?{_QUERY}"
    return f"{_BASE_URL}pagina/{page}?{_QUERY}"


def _get_total_pages(html: str) -> int:
    m = re.search(r'var\s+totalpagina\s*=\s*(\d+)', html)
    if m:
        return int(m.group(1))
    logger.warning("var totalpagina not found in HTML, defaulting to 1 page")
    return 1


def _extract_listing(card) -> dict:
    listing = dict.fromkeys(_COLUMNS, '')
    listing['portal'] = 'maxibienes'

    # Default numeric fields to 0
    for key in ('precio', 'area', 'habitaciones', 'banos', 'parqueaderos', 'estrato'):
        listing[key] = 0

    # ID: first <li> in .amenities contains the property code
    amenities = card.select('.amenities li')
    if amenities:
        code = ''.join(c for c in amenities[0].get_text(strip=True) if c.isdigit())
        if code:
            listing['id'] = f"MXB-{code}"

    # Tipo and Estrato from <h3>
    h3 = card.select_one('h3')
    if h3:
        tipo_parts = []
        for node in h3.contents:
            if getattr(node, 'name', None) == 'br':
                break
            tipo_parts.append(str(node).strip())
        tipo_raw = ''.join(tipo_parts).strip()
        listing['tipo'] = normalize_tipo(tipo_raw)

        full_text = h3.get_text(strip=True)
        m = re.search(r'estrato[:\s]*(\d+)', full_text, re.IGNORECASE)
        if m:
            listing['estrato'] = normalize_estrato(int(m.group(1)))

    # Precio
    price_span = card.select_one('.price span')
    if price_span:
        listing['precio'] = normalize_price(price_span.get_text(strip=True))

    # Amenities via FontAwesome icons
    for li in amenities:
        i_tag = li.select_one('i')
        if not i_tag:
            continue
        classes = i_tag.get('class', [])
        field = None
        for cls in classes:
            if cls in _ICON_FIELD:
                field = _ICON_FIELD[cls]
                break
        if field is None:
            continue
        text = li.get_text(strip=True)
        # For area, split on 'm' first to avoid capturing "m2" suffix
        if field == 'area':
            text = text.split('m')[0].strip()
        digits = ''.join(c for c in text if c.isdecimal())
        if digits:
            listing[field] = int(digits)

    # Barrio
    location = card.select_one('.image .location')
    if location:
        listing['barrio'] = normalize_barrio(location.get_text(strip=True))

    # URL
    link = card.select_one('.image a[href]')
    if link:
        href = link.get('href', '')
        listing['url'] = normalize_url(href, 'https://www.maxibienes.com')

    return listing


def scrape(ciudad='medellin', sample_only=False, max_pages=None, verbose=False) -> list[dict]:
    if sample_only and max_pages is None:
        max_pages = 3

    html = fetch_page(_page_url(1))
    if not html:
        logger.error("Failed to fetch page 1 from Maxibienes")
        return []

    total_pages = _get_total_pages(html)
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)

    listings = []
    anomalies = []

    def _process(html_content: str) -> int:
        soup = BeautifulSoup(html_content, 'lxml')
        cards = soup.select('.grid-style1 .item')
        for card in cards:
            listing = _extract_listing(card)
            listings.append(listing)
            warnings = validate(listing)
            if warnings:
                anomalies.extend(warnings)
                if verbose:
                    for w in warnings:
                        print(f"  [ANOMALY] {listing['id']} — {w}")
        return len(cards)

    # Page 1 (already fetched)
    cards_count = _process(html)
    if verbose:
        logger.info("Page 1: %d cards", cards_count)

    # Pages 2+
    for page in range(2, total_pages + 1):
        html = fetch_page(_page_url(page))
        if not html:
            logger.warning("Failed to fetch page %d, stopping", page)
            break
        cards_count = _process(html)
        if cards_count == 0:
            logger.info("No cards on page %d, stopping", page)
            break
        if verbose:
            logger.info("Page %d: %d cards, %d total", page, cards_count, len(listings))

    if sample_only:
        print(f"Sample: {len(listings)} listing(s) extracted")

    if anomalies:
        print(f"\n{len(anomalies)} anomaly(s) detected across {len(listings)} listings.")

    return listings
