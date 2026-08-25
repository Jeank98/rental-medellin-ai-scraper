"""Portada Inmobiliaria scraper - one-phase REST API extraction.

The public Vue application calls a structured SIMI API. All contractual fields
are present in each response record, so no detail-page requests are needed.
"""

import base64
import logging
import math
from collections.abc import Iterable
from typing import Final, TypedDict
from urllib.parse import quote

from scrape.fetcher import fetch_json
from scrape.normalize import (
    normalize_barrio,
    normalize_estrato,
    normalize_garaje,
    normalize_price,
    normalize_tipo,
)
from scrape.validator import validate

logger = logging.getLogger(__name__)

PORTAL: Final = "portadainmobiliaria"
API_BASE: Final = "https://api-crinmo.azurewebsites.net/simi/v2.1.1/filtroInmueble"
DETAIL_BASE: Final = "https://portadainmobiliaria.com/busqueda/#/inmueble/"
CITY_ID: Final = 25974
OPERATION_ID: Final = 1
PAGE_SIZE: Final = 12
MIN_RENT: Final = 500000
MAX_RENT: Final = 50000000
RESIDENTIAL_TYPES: Final[dict[str, int]] = {
    "apartamento": 1,
    "casa": 2,
    "apartaestudio": 11,
}

COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "portal",
    "tipo",
    "precio",
    "area",
    "habitaciones",
    "banos",
    "parqueaderos",
    "estrato",
    "barrio",
    "url",
)

# This value is embedded in the portal's public JavaScript client. It is not a
# user credential; the API rejects requests without the same public header.
_PUBLIC_API_VALUE: Final = (
    "Authorization:ZtRnKg4B7p2DLS93mxWeQCjtY9LVkMB63HPdq3ER-679"
)
API_HEADERS: Final[dict[str, str]] = {
    "Authorization": "Basic "
    + base64.b64encode(_PUBLIC_API_VALUE.encode("ascii")).decode("ascii"),
}


class Listing(TypedDict):
    """The exact eleven-column output contract."""

    id: str
    portal: str
    tipo: str
    precio: int
    area: int
    habitaciones: int
    banos: int
    parqueaderos: int
    estrato: int
    barrio: str
    url: str


def build_api_url(page: int, tipo_id: int) -> str:
    """Build the canonical path-based API URL for one residential type."""
    return (
        f"{API_BASE}/limite/{page}/total/{PAGE_SIZE}"
        f"/ciudad/{CITY_ID}/barrio/0/tipoInm/{tipo_id}"
        f"/tipOper/{OPERATION_ID}/valmin/{MIN_RENT}/valmax/{MAX_RENT}"
        "/campo/fecha/precio/0/order/desc/banios/0/alcobas/0/garajes/0"
        "/sede/0/usuario/0"
    )


def _integer_value(raw) -> int:
    """Normalize numeric API values, including decimal area strings."""
    if raw is None or isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    text = str(raw).strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def _validate_response(data) -> tuple[list[dict], dict]:
    """Validate a useful API response and reject textual error payloads."""
    if not isinstance(data, dict):
        raise RuntimeError("Portada API returned no JSON object")

    message = data.get("message")
    if message:
        raise RuntimeError(f"Portada API error: {message}")

    items = data.get("Inmuebles")
    metadata = data.get("datosGrales")
    if not isinstance(items, list) or not isinstance(metadata, dict):
        raise RuntimeError(
            "Portada API returned an invalid payload: expected Inmuebles and datosGrales"
        )
    return items, metadata


def _build_listing(item: dict) -> Listing | None:
    """Map one structured API record to the canonical listing contract."""
    code = str(item.get("Codigo_Inmueble") or "").strip()
    if not code:
        logger.warning("Skipping Portada record without Codigo_Inmueble")
        return None

    tipo = normalize_tipo(item.get("Tipo_Inmueble", ""))
    if tipo not in RESIDENTIAL_TYPES:
        logger.warning("Skipping Portada record %s with unsupported tipo %r", code, tipo)
        return None

    return {
        "id": f"POR-{code}",
        "portal": PORTAL,
        "tipo": tipo,
        "precio": normalize_price(item.get("Canon")),
        "area": _integer_value(item.get("AreaConstruida")),
        "habitaciones": _integer_value(item.get("Alcobas")),
        "banos": _integer_value(item.get("banios")),
        "parqueaderos": (
            _integer_value(item.get("garaje"))
            or normalize_garaje(item.get("garaje"))
        ),
        "estrato": normalize_estrato(item.get("Estrato")),
        "barrio": normalize_barrio(item.get("Barrio")),
        "url": f"{DETAIL_BASE}{quote(code, safe='-')}" if code else "",
    }


def parse_search_response(data, expected_tipo: str | None = None) -> list[Listing]:
    """Parse and normalize one API response page."""
    items, _metadata = _validate_response(data)
    listings: list[Listing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        listing = _build_listing(item)
        if listing is None:
            continue
        if expected_tipo and listing["tipo"] != expected_tipo:
            logger.warning(
                "Skipping Portada record %s returned under unexpected tipo %s",
                listing["id"],
                listing["tipo"],
            )
            continue
        listings.append(listing)
    return listings


def deduplicate_listings(rows: Iterable[Listing]) -> list[Listing]:
    """Keep the first row for each complete Portada property code."""
    seen: set[str] = set()
    unique: list[Listing] = []
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        unique.append(row)
    return unique


def _total_pages(metadata: dict) -> int:
    """Read the API page count, falling back to total inventory size."""
    reported = _integer_value(metadata.get("fin"))
    if reported > 0:
        return reported
    total = _integer_value(metadata.get("totalInmuebles"))
    return max(1, math.ceil(total / PAGE_SIZE)) if total else 1


def _fetch_page(page: int, tipo_id: int) -> dict:
    """Fetch one type/page response; callers validate before consuming it."""
    url = build_api_url(page, tipo_id)
    return fetch_json(url, headers=API_HEADERS)


def scrape(
    ciudad: str = "medellin",
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> list[Listing]:
    """Scrape Portada's Medellin rental inventory through the REST API."""
    if ciudad.casefold() not in {"medellin", "medellín"}:
        raise ValueError("Portada Inmobiliaria only supports Medellin")
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages must be at least 1")

    all_listings: list[Listing] = []
    for expected_tipo, tipo_id in RESIDENTIAL_TYPES.items():
        first_response = _fetch_page(1, tipo_id)
        _items, metadata = _validate_response(first_response)
        total_pages = _total_pages(metadata)
        if max_pages is not None:
            total_pages = min(total_pages, max_pages)
        elif sample_only:
            total_pages = 1

        for page in range(1, total_pages + 1):
            response = (
                first_response
                if page == 1
                else _fetch_page(page, tipo_id)
            )
            page_listings = parse_search_response(response, expected_tipo)
            all_listings.extend(page_listings)
            if verbose:
                logger.info(
                    "Portada: page %d/%d %s -> %d listings",
                    page,
                    total_pages,
                    expected_tipo,
                    len(page_listings),
                )
            for listing in page_listings:
                validate(listing)
            if not page_listings:
                break

    return deduplicate_listings(all_listings)
