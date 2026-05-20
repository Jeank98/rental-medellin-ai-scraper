"""Merino Hermanos (MHR) — single-phase HTML scraper.

Server-rendered PHP site with text-labeled card layout.
All fields extracted via text pattern matching from Scrapling output.
Uses fetch_page from scrape.fetcher for HTTP requests.
"""

import html as _html_module
import re

from scrape.fetcher import fetch_page
from scrape.normalize import normalize_price, normalize_tipo, normalize_barrio
from scrape.validator import validate

_BASE_URL = "https://merinohermanos.com/inmuebles"

_HTML_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r' {2,}')

_BLOCK_TAGS = [
    '</div>', '</p>', '</section>', '</article>',
    '<br', '</li>', '</tr>', '</td>',
    '</h1>', '</h2>', '</h3>', '</h4>', '</h5>', '</h6>',
]


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text preserving visual line structure."""
    for tag in _BLOCK_TAGS:
        html = html.replace(tag, tag + '\n')
    text = _HTML_TAG_RE.sub(' ', html)
    text = _WS_RE.sub(' ', text)
    text = _html_module.unescape(text)
    return text


def _find_listing_cards(text: str) -> list[list[str]]:
    """Split page text into individual listing card blocks.

    Each card starts with a '$' price line and ends before the next '$'.
    Returns list of line lists per card.
    """
    cards: list[list[str]] = []
    current: list[str] = []
    raw_lines = text.split('\n')

    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('$') and any(c.isdigit() for c in line):
            if current:
                cards.append(current)
                current = []
        current.append(line)

    if current:
        cards.append(current)

    return cards


def _extract_card(lines: list[str]) -> dict | None:
    """Extract listing fields from a single card's text lines.

    Actual card layout observed: precio -> tipo -> codigo -> barrio -> banos -> alcobas -> area
    Fields are matched by keyword, not by line position.
    """
    precio = 0
    codigo = ''
    tipo = ''
    area_val = 0
    habitaciones = 0
    banos = 0
    barrio = ''

    for line in lines:
        if line.startswith('$') and any(c.isdigit() for c in line):
            precio = normalize_price(line)
        elif 'alcoba' in line.lower():
            parts = line.split()
            if parts and parts[0].isdigit():
                habitaciones = int(parts[0])
        elif 'baño' in line.lower():
            parts = line.split()
            if parts and parts[0].isdigit():
                banos = int(parts[0])
        elif line.lower().startswith('area '):
            for word in line.split():
                if word.isdigit():
                    area_val = int(word)
                    break
        elif ' - ' in line:
            parts = line.rsplit(' - ', 1)
            if len(parts) == 2:
                barrio = parts[1].strip()
        elif line.isdigit():
            codigo = line
        elif not tipo and line:
            tipo = line

    if not precio:
        return None

    structural = sum(bool(v) for v in [codigo, barrio, banos, habitaciones, area_val, tipo])
    if structural < 2:
        return None

    return {
        'id': f"MHR-{codigo}" if codigo else '',
        'portal': 'merinohermanos',
        'tipo': normalize_tipo(tipo),
        'precio': precio,
        'area': area_val,
        'habitaciones': habitaciones,
        'banos': banos,
        'parqueaderos': 0,
        'estrato': 0,
        'barrio': normalize_barrio(barrio),
        'url': f"{_BASE_URL}?b_type=arriendo",
    }


def _parse_page(html: str) -> list[dict]:
    """Parse all listing cards from one HTML page."""
    text = _html_to_text(html)
    card_texts = _find_listing_cards(text)
    listings: list[dict] = []
    for card_lines in card_texts:
        listing = _extract_card(card_lines)
        if listing:
            listings.append(listing)
    return listings


def scrape(ciudad='medellin', sample_only=False, max_pages=None, verbose=False) -> list[dict]:
    """Scrape Merino Hermanos rental listings via HTML pagination.

    Paginates ``?b_type=arriendo&page=N`` until an empty page is
    returned or the page limit is reached.

    Args:
        ciudad: Ignored (MHR shows all cities in one search). Kept for
            API compatibility.
        sample_only: If True, limit to 3 pages and print sample count.
        max_pages: Explicit page limit (overrides sample_only default).
        verbose: Print extraction details per page.

    Returns:
        List of standardized 11-column listing dicts.
    """
    if sample_only and max_pages is None:
        max_pages = 3

    listings: list[dict] = []
    anomalies: list[str] = []
    page = 1

    while True:
        if max_pages is not None and page > max_pages:
            break

        url = f"{_BASE_URL}?b_type=arriendo&page={page}"

        if verbose:
            print(f"  MHR: fetching page {page}...")

        html = fetch_page(url)
        if not html:
            break

        page_listings = _parse_page(html)
        if not page_listings:
            break

        if verbose:
            print(f"  MHR: page {page} -> {len(page_listings)} listing(s)")

        for listing in page_listings:
            listings.append(listing)
            warnings = validate(listing)
            if warnings:
                anomalies.extend(warnings)
                if verbose:
                    for w in warnings:
                        print(f"  [ANOMALY] {listing['id']} — {w}")

        page += 1

    if sample_only:
        print(f"Sample: {len(listings)} listing(s) extracted")

    if anomalies:
        print(f"\n{len(anomalies)} anomaly(s) detected across {len(listings)} listings.")

    return listings
