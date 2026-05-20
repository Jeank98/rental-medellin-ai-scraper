"""Habitamos (HBM) — server-rendered Drupal 9 HTML scraper.

Parses listing cards from .cell.medium-6.large-3.margin-bottom-1 using
BeautifulSoup. Handles mixed EN/ES labels and dual-price fields.
"""

import logging
from urllib.parse import quote

from bs4 import BeautifulSoup

from scrape.fetcher import fetch_page
from scrape.normalize import normalize_price, normalize_tipo, normalize_barrio
from scrape.validator import validate

logger = logging.getLogger(__name__)

BASE_URL = "https://en.habitamos.com.co"
CARD_SELECTOR = ".cell.medium-6.large-3.margin-bottom-1"

_CITY_NORMALIZE = {
    "medellin": "Medell\xedn",
    "medell\xedn": "Medell\xedn",
    "bogota": "Bogot\xe1",
    "bogot\xe1": "Bogot\xe1",
}

_FEATURE_LABELS = {
    "bedrooms": ["Bedrooms:", "Habitaciones:", "habitaciones:", "Alcobas:", "alcobas:"],
    "bathrooms": ["Bathrooms:", "Baños:", "baños:", "Banos:", "banos:"],
    "garage": ["Garage:", "Garaje:", "garaje:", "Parqueadero:", "Parqueaderos:"],
}


def _get_heading_text(card) -> str:
    h6 = card.find("h6")
    if h6:
        return h6.get_text(strip=True)
    return ""


def _card_url(card) -> str:
    link = card.find("a", href=True)
    if link:
        href = link["href"]
        return BASE_URL + href if href.startswith("/") else href
    return ""


def _extract_code(card) -> str:
    text = card.get_text(separator=" ", strip=True)
    for prefix in ("Code:", "Código:", "Codigo:"):
        if prefix.lower() in text.lower():
            idx = text.lower().index(prefix.lower()) + len(prefix)
            parts = text[idx:].strip().split()
            if parts and parts[0].isdigit():
                return parts[0]
    return ""


def _extract_tipo(card) -> str:
    text = _get_heading_text(card)
    if not text:
        return ""
    if " - " in text:
        return normalize_tipo(text.split(" - ")[0].strip())
    return ""


def _extract_barrio(card) -> str:
    text = _get_heading_text(card)
    if not text:
        return ""
    for marker in (" - Medell\xedn - ", " - Medellin - "):
        if marker in text:
            return normalize_barrio(text.split(marker)[-1].strip())
    return ""


def _extract_precio(card) -> int:
    text = card.get_text(separator=" ", strip=True)
    for pattern in ("Rental price:", "rental price:", "Rental Price:"):
        if pattern in text:
            idx = text.index(pattern) + len(pattern)
            chunk = text[idx:].strip()
            for stop in ("Sale price:", "For Sale:", "For sale:"):
                if stop.lower() in chunk.lower():
                    chunk = chunk[: chunk.lower().index(stop.lower())].strip()
            return normalize_price(chunk)
    idx = text.find("$")
    if idx >= 0:
        chunk = text[idx:]
        for stop in ("Sale price:", "For Sale:", "For sale:"):
            if stop.lower() in chunk.lower():
                chunk = chunk[: chunk.lower().index(stop.lower())].strip()
        return normalize_price(chunk)
    return 0


def _extract_feature(text: str, labels: list[str]) -> int:
    for label in labels:
        if label.lower() in text.lower():
            idx = text.lower().index(label.lower()) + len(label)
            chunk = text[idx:].strip()
            word = chunk.split()[0] if chunk.split() else ""
            word = word.strip(",.")
            digits = "".join(c for c in word if c.isdigit())
            if digits:
                return int(digits)
            break
    return 0


def _extract_features(card):
    text = card.get_text(separator=" ", strip=True)
    return (
        _extract_feature(text, _FEATURE_LABELS["bedrooms"]),
        _extract_feature(text, _FEATURE_LABELS["bathrooms"]),
        _extract_feature(text, _FEATURE_LABELS["garage"]),
    )


def _extract_listing(card) -> dict:
    code = _extract_code(card)
    habitaciones, banos, parqueaderos = _extract_features(card)
    return {
        "id": f"HBM-{code}" if code else "",
        "portal": "habitamos",
        "tipo": _extract_tipo(card),
        "precio": _extract_precio(card),
        "area": 0,
        "habitaciones": habitaciones,
        "banos": banos,
        "parqueaderos": parqueaderos,
        "estrato": 0,
        "barrio": _extract_barrio(card),
        "url": _card_url(card),
    }


def scrape(
    ciudad="Medellín", sample_only=False, max_pages=None, verbose=False
) -> list[dict]:
    """Scrape Habitamos rental listings by paginating HTML pages.

    Stop condition: page contains "There are no properties" or no cards found.

    Args:
        ciudad: City filter (default: medellin).
        sample_only: Limit to 3 pages if True.
        max_pages: Explicit page limit.
        verbose: Detailed extraction logging.

    Returns:
        List of standardized 11-column listing dicts.
    """
    page = 1
    pages_fetched = 0
    listings: list[dict] = []

    ciudad_normalized = _CITY_NORMALIZE.get(ciudad.lower().strip(), ciudad)
    encoded_ciudad = quote(ciudad_normalized)

    url_template = (
        "https://en.habitamos.com.co/resultados/{}/asc"
        "/fecha_consignacion/arriendo/tipo_propiedad_defecto"
        f"/{encoded_ciudad}"
        "/barrio_defecto/banios_defecto/alcobas_defecto"
        "/precio_desde_defecto/precio_hasta_defecto"
        "/codigo_defecto/area_desde_defecto/area_hasta_defecto"
    )

    while True:
        if max_pages is not None and pages_fetched >= max_pages:
            break
        if sample_only and pages_fetched >= 3:
            break

        url = url_template.format(page)

        if verbose:
            logger.info("HBM: page %d — %s", page, url)

        html = fetch_page(url)
        if html is None:
            logger.warning("HBM: failed to fetch page %d", page)
            break

        if "There are no properties" in html:
            if verbose:
                logger.info("HBM: no more properties at page %d", page)
            break

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(CARD_SELECTOR)
        if not cards:
            if verbose:
                logger.info("HBM: no cards found on page %d", page)
            break

        for card in cards:
            listing = _extract_listing(card)
            validate(listing)
            listings.append(listing)

        page += 1
        pages_fetched += 1

    return listings
