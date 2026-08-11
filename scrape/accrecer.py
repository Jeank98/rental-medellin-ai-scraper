"""Acrecer portal scraper — Single-Phase RSC Scraper.

All 11 fields are in the Next.js RSC payload embedded in the page HTML.
Uses json.JSONDecoder for RSC argument extraction and balanced parsing
for searchResults. No CSS selectors, BeautifulSoup, or regex-based
field extraction.
"""

import json
import logging
import math

from scrape.fetcher import fetch_page
from scrape.normalize import normalize_estrato, normalize_tipo
from scrape.validator import validate

logger = logging.getLogger(__name__)

_COLUMNS = [
    'id', 'portal', 'tipo', 'precio', 'area',
    'habitaciones', 'banos', 'parqueaderos', 'estrato',
    'barrio', 'url',
]


def _clean_mojibake(s: str) -> str:
    """Attempt latin-1 → utf-8 re-encoding; keep original on failure."""
    if not s:
        return ''
    try:
        return s.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _parse_chunks(html: str) -> str:
    """Extract and concatenate all self.__next_f.push( JSON payload strings."""
    decoder = json.JSONDecoder()
    chunks: list[str] = []
    pos = 0
    while True:
        idx = html.find('self.__next_f.push(', pos)
        if idx == -1:
            break
        paren_start = html.index('(', idx)
        depth = 0
        i = paren_start
        while i < len(html):
            if html[i] == '(':
                depth += 1
            elif html[i] == ')':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        arg_str = html[paren_start + 1:i]
        try:
            obj, _ = decoder.raw_decode(arg_str)
            if isinstance(obj, list) and len(obj) >= 2:
                chunk = obj[1]
                if isinstance(chunk, str):
                    chunks.append(chunk)
        except (json.JSONDecodeError, ValueError):
            pass
        pos = i + 1
    return ''.join(chunks)


def _find_value(concat: str, key: str):
    """Extract a JSON value by key from the concatenated RSC stream."""
    decoder = json.JSONDecoder()
    search_key = f'"{key}"'
    idx = concat.find(search_key)
    if idx == -1:
        return None
    colon = concat.index(':', idx)
    start = colon + 1
    while start < len(concat) and concat[start] in ' \t\n\r':
        start += 1
    try:
        obj, _ = decoder.raw_decode(concat, start)
        return obj
    except json.JSONDecodeError:
        return None


def parse_rsc_payload(html: str) -> list[dict]:
    """Extract and normalize Acrecer listings from the RSC payload.

    Scans for self.__next_f.push( tokens, concatenates decoded JSON
    chunks, balanced-parses searchResults, and returns a list of
    normalized 11-column listing dicts.
    """
    concat = _parse_chunks(html)
    if not concat:
        return []

    records = _find_value(concat, 'searchResults')
    if not isinstance(records, list):
        return []

    listings: list[dict] = []
    for rec in records:
        code = rec.get('code')
        rent = rec.get('rentValue')
        if not code or not rent:
            logger.warning("Skipping record: missing %s",
                           "code" if not code else "rentValue")
            continue

        rooms = rec.get('rooms') or {}
        hf = rec.get('householdFeatures') or {}

        sector = rec.get('sectorName', '')
        zone = rec.get('zoneName', '')
        barrio_raw = sector if sector else (zone if zone else '')

        listing = dict.fromkeys(_COLUMNS, '')
        listing['id'] = code
        listing['portal'] = 'accrecer'
        listing['tipo'] = normalize_tipo(rec.get('propertyType', ''))
        listing['precio'] = int(rent)
        listing['area'] = (
            round(float(rec['builtArea'])) if rec.get('builtArea') else 0
        )
        listing['habitaciones'] = (
            int(rec['numberOfRooms']) if rec.get('numberOfRooms') else 0
        )
        listing['banos'] = int(rooms.get('baths', 0)) if rooms.get('baths') else 0
        listing['parqueaderos'] = int(hf.get('garages', 0)) if hf.get('garages') else 0
        listing['estrato'] = normalize_estrato(rec.get('stratum', ''))
        listing['barrio'] = _clean_mojibake(barrio_raw)
        listing['url'] = f'https://www.acrecer.com/inmueble/{code}'

        for key in ('precio', 'area', 'habitaciones', 'banos',
                     'parqueaderos', 'estrato'):
            if not isinstance(listing[key], int):
                listing[key] = 0

        listings.append(listing)

    return listings


def scrape(ciudad='medellin', sample_only=False, max_pages=None,
           verbose=False) -> list[dict]:
    """Scrape Acrecer rental listings for both Apartamento and Casa types."""
    types = ['Apartamento', 'Casa']
    all_listings: list[dict] = []
    anomalies: list[str] = []

    for tipo in types:
        url_t = (
            f'https://www.acrecer.com/inmuebles/arriendo/{tipo}'
            f'/Medell%C3%ADn'
        )
        html = fetch_page(f'{url_t}?page=1')
        if not html:
            logger.warning('Failed to fetch page 1 for %s', tipo)
            continue

        concat = _parse_chunks(html)
        total_records = _find_value(concat, 'totalRecords') or 0
        records_per_page = _find_value(concat, 'recordsPerPage') or 12

        total_pages = (
            math.ceil(total_records / records_per_page)
            if records_per_page else 1
        )
        if max_pages is not None:
            total_pages = min(total_pages, max_pages)
        if sample_only and max_pages is None:
            total_pages = 1

        for page in range(1, total_pages + 1):
            if page > 1:
                html = fetch_page(f'{url_t}?page={page}')
                if not html:
                    logger.warning(
                        'Failed to fetch page %d for %s, stopping', page, tipo,
                    )
                    break

            page_listings = parse_rsc_payload(html)
            for listing in page_listings:
                warnings = validate(listing)
                if warnings:
                    anomalies.extend(warnings)
                    if verbose:
                        for w in warnings:
                            print(f'  [ANOMALY] {listing["id"]} — {w}')
                all_listings.append(listing)

            if not page_listings:
                if verbose:
                    logger.info(
                        'No listings on page %d for %s, stopping', page, tipo,
                    )
                break
            if verbose and page_listings:
                logger.info(
                    'Page %d (%s): %d listings, %d total',
                    page, tipo, len(page_listings), len(all_listings),
                )

    if sample_only:
        print(f'Sample: {len(all_listings)} listing(s) extracted')

    if anomalies:
        print(
            f'\n{len(anomalies)} anomaly(s) detected across '
            f'{len(all_listings)} listings.',
        )

    return all_listings
