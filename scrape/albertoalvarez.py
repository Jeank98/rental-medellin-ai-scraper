"""AlbertoAlvarez (AAL) — HTML/JSON textarea scraper.

Each article card contains a <textarea class="field-property"> with
complete structured JSON data. No CSS selectors or icon detection needed.
"""

import json
import logging

from bs4 import BeautifulSoup

from scrape.fetcher import fetch_page
from scrape.normalize import normalize_price, normalize_tipo, normalize_estrato, normalize_barrio
from scrape.validator import validate

logger = logging.getLogger(__name__)

_BASE = "https://albertoalvarez.com"
_TIPOS = ["apartamento", "casa", "apartaestudio"]
_PER_PAGE = 9

_TIPO_OVERRIDE = {
    "casa vivienda": "casa",
}


def _extract_card(article, tipo_url: str) -> dict | None:
    """Extract listing fields from an article card's hidden JSON textarea."""
    textarea = article.find("textarea", class_="field-property")
    if not textarea:
        return None

    try:
        data = json.loads(textarea.get_text(strip=True))
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    code = str(data.get("code", "")).strip()
    raw_tipo = str(data.get("propertyType", "")).strip()
    tipo_raw = _TIPO_OVERRIDE.get(raw_tipo.lower(), raw_tipo)
    tipo = normalize_tipo(tipo_raw)
    precio = normalize_price(data.get("rentValue"))
    area = int(data.get("builtArea", 0) or 0)
    habitaciones = int(data.get("numberOfRooms", 0) or 0)
    household = data.get("householdFeatures") or {}
    banos = int(household.get("baths", 0) or 0)
    parqueaderos = int(household.get("AASimpleparking", 0) or 0)
    estrato = normalize_estrato(data.get("stratum"))
    barrio_raw = str(data.get("sectorName", "")).strip()
    barrio = normalize_barrio(barrio_raw)

    # Build URL slug from raw sectorName
    slug = barrio_raw.lower().replace(" ", "-")
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    url = f"{_BASE}/inmuebles/detalle/arrendamientos/{tipo_url}/{code}/{slug}-medellin/"

    listing = {
        "id": f"AAL-{code}" if code else "",
        "portal": "albertoalvarez",
        "tipo": tipo,
        "precio": precio,
        "area": area,
        "habitaciones": habitaciones,
        "banos": banos,
        "parqueaderos": parqueaderos,
        "estrato": estrato,
        "barrio": barrio,
        "url": url,
    }
    validate(listing)
    return listing


def scrape(ciudad="medellin", sample_only=False, max_pages=None, verbose=False) -> list[dict]:
    """Scrape AlbertoAlvarez rental listings.

    Iterates over 3 tipos (apartamento, casa, apartaestudio), paginating
    until no article cards are found or max_pages/sample_only limits hit.

    Args:
        ciudad: City URL segment (default: medellin).
        sample_only: If True, limit to 3 pages per tipo.
        max_pages: Explicit page limit per tipo.
        verbose: Print per-page progress.

    Returns:
        List of standardized 11-column listing dicts.
    """
    all_listings: list[dict] = []

    for tipo in _TIPOS:
        page = 1
        pages_fetched = 0

        if verbose:
            logger.info("AAL: fetching tipo=%s", tipo)

        while True:
            url = f"{_BASE}/inmuebles/arrendamientos/{tipo}/{ciudad}/?limit={_PER_PAGE}&pag={page}"

            if verbose:
                logger.info("AAL: %s page=%d", tipo, page)

            html = fetch_page(url)
            if not html:
                break

            soup = BeautifulSoup(html, "html.parser")
            articles = soup.find_all("article")
            if not articles:
                break

            cards_found = 0
            for article in articles:
                listing = _extract_card(article, tipo)
                if listing:
                    all_listings.append(listing)
                    cards_found += 1

            if cards_found == 0:
                break

            page += 1
            pages_fetched += 1

            if max_pages is not None and pages_fetched >= max_pages:
                break

            if sample_only and pages_fetched >= 3:
                break

    return all_listings
