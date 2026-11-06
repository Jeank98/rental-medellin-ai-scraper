"""Arrendamientos Las Vegas (LVG) — one-phase REST API extraction.

The site is a Next.js app whose search page is client-rendered; the inventory
comes from ``/api/properties``, which answers plain HTTP (no Turnstile, no JS)
and already carries every contractual field, so no detail phase is needed.

The payload is wrapped as ``<html><body>…</body></html>`` and ``perpage`` is
capped at 50 by the server.
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

PORTAL: Final = "arrendamientoslasvegas"
BASE_URL: Final = "https://arrendamientoslasvegas.com"
API_URL: Final = f"{BASE_URL}/api/properties"
PAGE_SIZE: Final = 50  # the API caps perpage at 50
MIN_RENT: Final = 200_000
MAX_RENT: Final = 200_000_000
RESIDENTIAL_TYPES: Final = {"apartamento", "apartaestudio", "casa"}

CITY_CODES: Final[dict[str, int]] = {
    "medellin": 5001,
    "envigado": 5266,
    "itagui": 5360,
    "sabaneta": 5631,
    "la estrella": 5380,
}

_WRAPPER_RE = re.compile(r"^\s*<html><body>|</body></html>\s*$", re.IGNORECASE)


class UnsupportedCityError(KeyError):
    """Raised when the requested city has no verified Las Vegas city code."""


def _city_key(ciudad: str) -> str:
    folded = (
        str(ciudad).strip().casefold().replace("-", " ")
        .replace("í", "i").replace("á", "a").replace("é", "e").replace("ó", "o")
        .replace("ú", "u").replace("ü", "u")
    )
    return " ".join(folded.split())


def resolve_city_code(ciudad: str) -> int:
    code = CITY_CODES.get(_city_key(ciudad))
    if code is None:
        known = ["medellin", "envigado", "itagui", "sabaneta", "la estrella"]
        raise UnsupportedCityError(
            f"Las Vegas has no verified city code for {ciudad!r}; known: {known}"
        )
    return code


def build_api_url(page: int, city_code: int) -> str:
    return (
        f"{API_URL}?perpage={PAGE_SIZE}&status=1&page={page}"
        f"&biz=1,3&city={quote(str(city_code))}"
    )


def parse_payload(raw: str) -> dict:
    body = _WRAPPER_RE.sub("", str(raw).strip())
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError(f"Las Vegas returned a non-JSON payload: {error}") from error


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
    """Map one API record to the 11-column schema."""
    code = str(item.get("codpro") or "").strip()
    if not code:
        return None

    tipo = normalize_tipo(item.get("type") or "")
    if tipo not in RESIDENTIAL_TYPES:
        return None

    precio = _int(item.get("rent")) or _int(item.get("price"))
    if not MIN_RENT <= precio <= MAX_RENT:
        return None

    return {
        "id": f"LVG-{code}",
        "portal": PORTAL,
        "tipo": tipo,
        "precio": precio,
        "area": _int(item.get("area_cons")),
        "habitaciones": _int(item.get("bedrooms")),
        "banos": _int(item.get("bathrooms")),
        "parqueaderos": _int(item.get("parking")),
        "estrato": _int(item.get("stratum")),
        "barrio": normalize_barrio(item.get("neighborhood") or ""),
        "url": f"{BASE_URL}/inmuebles/{code}",
    }


def scrape(
    ciudad="medellin", sample_only=False, max_pages=None, verbose=False
) -> list[dict]:
    """Scrape Arrendamientos Las Vegas rentals for one municipality."""
    city_code = resolve_city_code(ciudad)
    page_limit = max_pages if max_pages is not None else (3 if sample_only else None)

    listings: list[dict] = []
    seen: set[str] = set()
    page = 1
    last_page = 0

    while True:
        if page_limit is not None and page > page_limit:
            break

        if verbose:
            logger.info("LVG: city=%s pagina=%d", city_code, page)

        try:
            payload = parse_payload(str(fetch_page(build_api_url(page, city_code))))
        except Exception as error:  # noqa: BLE001 - surfaced by the caller
            logger.error("LVG: fallo la página %d: %s", page, error)
            break

        if page == 1:
            last_page = _int(payload.get("last_page"))
            if verbose:
                logger.info(
                    "LVG: total=%s paginas=%s", payload.get("total"), last_page
                )

        items = payload.get("data") or []
        if not items:
            break

        for item in items:
            listing = to_listing(item)
            if listing is None or listing["id"] in seen:
                continue
            validate(listing)
            seen.add(listing["id"])
            listings.append(listing)

        if last_page and page >= last_page:
            break
        page += 1

    logger.info("LVG %s: %d listings", city_code, len(listings))
    return listings
