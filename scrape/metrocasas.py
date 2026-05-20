"""Metrocasas portal scraper — Single-Phase HTML Scraper.

JS-rendered WordPress (RealHomes theme). All 11 fields on listing cards
extracted via BeautifulSoup from data-attributes and text content.
"""

import logging
import re
from bs4 import BeautifulSoup
from scrape.fetcher import fetch_page
from scrape.normalize import (
    normalize_price,
    normalize_tipo,
    normalize_barrio,
    normalize_url,
)
from scrape.validator import validate

logger = logging.getLogger(__name__)

_BASE_URL = "https://metrocasas.co/new/property-search/"
_QUERY = "status=para-alquiler&type[]=apartaestudio&type[]=apartamento&type[]=casa&location[]=medellin"

_COLUMNS = [
    'id', 'portal', 'tipo', 'precio', 'area',
    'habitaciones', 'banos', 'parqueaderos', 'estrato',
    'barrio', 'url',
]


def _page_url(page: int) -> str:
    if page <= 1:
        return f"{_BASE_URL}?{_QUERY}"
    return f"{_BASE_URL}page/{page}/?{_QUERY}"


def _get_total_pages(html: str) -> int:
    soup = BeautifulSoup(html, 'lxml')
    max_page = 1
    for a in soup.select('a.page-numbers, .pagination a'):
        href = a.get('href', '')
        m = re.search(r'/page/(\d+)/', href)
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


def _parse_title(title: str) -> tuple:
    """Parse card title into (tipo, barrio)."""
    if not title:
        return ('', '')
    if ' en ' in title.lower():
        parts = title.split(' en ', 1)
        return (normalize_tipo(parts[0]), normalize_barrio(parts[1]))
    words = title.split()
    if words:
        return (normalize_tipo(words[0]), normalize_barrio(' '.join(words[1:])))
    return ('', '')


def _extract_listing(card) -> dict:
    listing = dict.fromkeys(_COLUMNS, '')
    listing['portal'] = 'metrocasas'

    for key in ('precio', 'area', 'habitaciones', 'banos', 'parqueaderos', 'estrato'):
        listing[key] = 0

    prop_id = card.get('data-property-id', '')
    if prop_id:
        listing['id'] = f"MTC-{prop_id}"

    prop_url = card.get('data-property-url', '')
    if prop_url:
        listing['url'] = normalize_url(prop_url, 'https://metrocasas.co')

    title = card.get('data-property-title', '') or ''
    if title:
        tipo, barrio = _parse_title(title)
        listing['tipo'] = tipo
        listing['barrio'] = barrio
    else:
        h3 = card.select_one('h3')
        if h3:
            title = h3.get_text(strip=True)
            tipo, barrio = _parse_title(title)
            listing['tipo'] = tipo
            listing['barrio'] = barrio

    text = card.get_text(separator=' ')

    price_match = re.search(r'\$\s*([\d.,]+)', text)
    if price_match:
        listing['precio'] = normalize_price(price_match.group(0))

    area_match = re.search(r'Área\s+(\d+)', text)
    if area_match:
        listing['area'] = int(area_match.group(1))

    hab_match = re.search(r'Habitaciones\s+(\d+)', text)
    if hab_match:
        listing['habitaciones'] = int(hab_match.group(1))

    banos_match = re.search(r'Cuartos\s+de\s+baño\s+(\d+)', text)
    if banos_match:
        listing['banos'] = int(banos_match.group(1))

    return listing


def scrape(ciudad='medellin', sample_only=False, max_pages=None, verbose=False) -> list[dict]:
    if sample_only and max_pages is None:
        max_pages = 3

    html = fetch_page(_page_url(1))
    if not html:
        logger.error("Failed to fetch Metrocasas page 1")
        return []

    total_pages = _get_total_pages(html)
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)

    listings = []
    anomalies = []

    def _process(html_content: str) -> int:
        soup = BeautifulSoup(html_content, 'lxml')
        cards = soup.select('article.rh_list_card')
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

    cards_count = _process(html)
    if verbose:
        logger.info("Page 1: %d cards", cards_count)

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
