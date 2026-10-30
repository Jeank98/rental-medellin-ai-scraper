"""Habitamos (HBM) — one-phase REST extraction.

The portal was rebuilt on Drupal: ``/propiedades?comercio=arriendo`` now ships an
empty shell and the results are loaded client-side from
``/api/propiedades/buscar``. The legacy ``en.habitamos.com.co`` host answers 403
and its card markup (``.cell.medium-6...``) no longer exists anywhere.

Each search response already carries every contractual field, so no detail
request is needed. ``estrato`` is genuinely absent from this API.
"""

import json
import logging
import re
from typing import Final
from urllib.parse import quote

from scrape.fetcher import fetch_page
from scrape.normalize import normalize_barrio, normalize_price, normalize_tipo
from scrape.validator import validate

logger = logging.getLogger(__name__)

PORTAL: Final = "habitamos"
API_BASE: Final = "https://habitamos.com.co/api/propiedades/buscar"
DETAIL_BASE: Final = "https://www.habitamos.com.co/propiedades/"
PAGE_SIZE: Final = 12  # the API caps por_pagina at 12
MIN_RENT: Final = 200_000
MAX_RENT: Final = 200_000_000

# The API filters on the municipality label it prints, accents included.
CITY_NAMES: Final[dict[str, str]] = {
    "medellin": "Medellín",
    "medellín": "Medellín",
    "envigado": "Envigado",
    "itagui": "Itagüí",
    "itagüí": "Itagüí",
    "sabaneta": "Sabaneta",
    "la estrella": "La Estrella",
    "la estrella ": "La Estrella",
}

RESIDENTIAL_TYPES: Final = {"apartamento", "apartaestudio", "casa"}

_WRAPPER_RE = re.compile(r"^\s*<html><body>|</body></html>\s*$", re.IGNORECASE)


class UnsupportedCityError(KeyError):
    """Raised when the requested city has no verified Habitamos filter."""


def _city_key(ciudad: str) -> str:
    return " ".join(str(ciudad).strip().casefold().replace("-", " ").split())


def resolve_municipio(ciudad: str) -> str:
    """Map a canonical city label to the municipality the API filters on."""
    key = _city_key(ciudad)
    if key in CITY_NAMES:
        return CITY_NAMES[key]
    known = ["medellin", "envigado", "itagui", "sabaneta", "la estrella"]
    raise UnsupportedCityError(
        f"Habitamos has no verified filter for {ciudad!r}; known: {known}"
    )


def build_api_url(page: int, municipio: str) -> str:
    """One search URL. Page numbering is 1-based."""
    return (
        f"{API_BASE}?comercio=arriendo&pagina={page}"
        f"&por_pagina={PAGE_SIZE}&municipio={quote(municipio)}"
    )


def parse_search_payload(raw: str) -> dict:
    """Parse one search response; the endpoint wraps its JSON in ``<html><body>``."""
    body = _WRAPPER_RE.sub("", str(raw).strip())
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError(f"Habitamos returned a non-JSON payload: {error}") from error


def _int(value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return normalize_price(value)
    return 0


def to_listing(item: dict) -> dict | None:
    """Map one API record to the 11-column schema.

    Non-residential inventory (local, bodega, oficina, lote) is dropped: the
    shared sheet and the validator only track dwellings.
    """
    code = str(item.get("codigo") or "").strip()
    if not code:
        return None

    tipo = normalize_tipo(item.get("tipo") or "")
    if tipo not in RESIDENTIAL_TYPES:
        return None

    precio = _int(item.get("precio_arriendo"))
    if not MIN_RENT <= precio <= MAX_RENT:
        return None

    return {
        "id": f"HBM-{code}",
        "portal": PORTAL,
        "tipo": tipo,
        "precio": precio,
        "area": _int(item.get("area_numero")) or _int(item.get("area")),
        "habitaciones": _int(item.get("alcobas")),
        "banos": _int(item.get("banos")),
        "parqueaderos": _int(item.get("parqueaderos")),
        "estrato": 0,
        "barrio": normalize_barrio(item.get("barrio") or ""),
        "url": f"{DETAIL_BASE}{code}",
    }


def scrape(
    ciudad="Medellín", sample_only=False, max_pages=None, verbose=False
) -> list[dict]:
    """Scrape Habitamos rental listings for one municipality.

    Args:
        ciudad: Canonical city (medellin, envigado, itagui, sabaneta,
            la-estrella) or an accented/aliased label.
        sample_only: Limit to 3 pages.
        max_pages: Explicit page limit.
        verbose: Per-page logging.

    Returns:
        List of standardized 11-column listing dicts.
    """
    municipio = resolve_municipio(ciudad)
    page_limit = max_pages if max_pages is not None else (3 if sample_only else None)

    listings: list[dict] = []
    seen: set[str] = set()
    page = 1
    total_pages = 0

    while True:
        if page_limit is not None and page > page_limit:
            break

        url = build_api_url(page, municipio)
        if verbose:
            logger.info("HBM: %s pagina=%d", municipio, page)

        try:
            payload = parse_search_payload(str(fetch_page(url)))
        except Exception as error:  # noqa: BLE001 - reported by the caller
            logger.error("HBM: fallo la página %d: %s", page, error)
            break

        results = payload.get("resultados") or []
        if page == 1:
            total_pages = _int(payload.get("total_paginas"))
            if verbose:
                logger.info(
                    "HBM: %s total=%s paginas=%s",
                    municipio, payload.get("total"), total_pages,
                )

        if not results:
            break

        for item in results:
            listing = to_listing(item)
            if listing is None or listing["id"] in seen:
                continue
            validate(listing)
            seen.add(listing["id"])
            listings.append(listing)

        if total_pages and page >= total_pages:
            break
        page += 1

    logger.info("HBM %s: %d listings", municipio, len(listings))
    return listings
