"""Arrendamientos del Norte (ADN) — WordPress REST API scraper.

ADN exposes a public JSON API at /wp-json/anorte/v1/buscador.
No browser, selectors, or HTML parsing needed — just paginate
over three tipo params and extract fields from structured JSON.
"""

import re
import logging

from scrape.fetcher import fetch_json
from scrape.normalize import normalize_price, normalize_tipo
from scrape.validator import validate

logger = logging.getLogger(__name__)

_API_BASE = "https://arrendamientosdelnorte.com/wp-json/anorte/v1/buscador"
_TIPOS = ["apartamento", "casa", "apartaestudio"]
_PER_PAGE = 30

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clean_area(raw) -> int:
    """Strip HTML tags and extract the integer before 'm' in area strings.

    Handles values like '60 m<sup>2</sup> aprox.' → 60.
    """
    if raw is None:
        return 0
    s = str(raw).strip()
    s = _HTML_TAG_RE.sub("", s)
    return int(s.split("m")[0].strip())


def _normalize_tipo_adn(raw: str) -> str:
    """Normalize tipo from ADN API response.

    ADN returns capitalized Spanish names like 'Apartamento', 'Casa'.
    """
    return normalize_tipo(str(raw).strip())


def _build_item(portal: str, item: dict) -> dict:
    """Build a normalized listing dict from an ADN API item."""
    precio = normalize_price(item.get("valor", ""))
    area = _clean_area(item.get("area", ""))
    tipo = _normalize_tipo_adn(item.get("tipo", ""))
    habitaciones = int(item.get("cuartos", 0) or 0)
    barrio = str(item.get("barrio", "")).strip()
    url = str(item.get("link", "")).strip()
    codigo = str(item.get("codigo", "")).strip()

    listing = {
        "id": f"ADN-{codigo}" if codigo else "",
        "portal": portal,
        "tipo": tipo,
        "precio": precio,
        "area": area,
        "habitaciones": habitaciones,
        "banos": 0,
        "parqueaderos": 0,
        "estrato": 0,
        "barrio": barrio,
        "url": url,
    }
    return listing


def scrape(ciudad="medellin", sample_only=False, max_pages=None, verbose=False) -> list[dict]:
    """Scrape ADN listings via the public REST API.

    Iterates over 3 tipos (apartamento, casa, apartaestudio), paginating
    until the API returns empty results. Post-filters casa results to
    exclude mixed tipos (Casa-Finca, Casa-local).
    """
    all_listings: list[dict] = []
    max_pages_tipo = max_pages

    for tipo in _TIPOS:
        page = 1
        pages_fetched = 0

        if verbose:
            logger.info("ADN: fetching tipo=%s", tipo)

        while True:
            url = (
                f"{_API_BASE}?concepto=Arriendo"
                f"&tipo={tipo}"
                f"&page={page}"
                f"&per_page={_PER_PAGE}"
            )

            if verbose:
                logger.info("ADN: %s page=%d", tipo, page)

            data = fetch_json(url)
            if not data or (isinstance(data, list) and len(data) == 0):
                break

            items = data if isinstance(data, list) else data.get("data", [])
            if not items:
                break

            listings = [_build_item("arrendamientosdelnorte", item) for item in items]

            # Post-filter: when tipo=casa, API returns mixed tipos — keep only casa
            if tipo == "casa":
                listings = [l for l in listings if l["tipo"] == "casa"]

            # Run each listing through validator
            for listing in listings:
                validate(listing)

            all_listings.extend(listings)

            page += 1
            pages_fetched += 1

            if max_pages_tipo is not None and pages_fetched >= max_pages_tipo:
                break

            if sample_only and pages_fetched >= 3:
                break

    return all_listings
