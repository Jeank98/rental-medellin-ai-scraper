"""Escala Inmobiliaria one-phase REST rental scraper.

The public SPA reads inventory from ``/api/v2/propiedades``. The endpoint is
filtered by numeric city, ``limite`` (page size, capped at 100) and
zero-based ``pagina``. Word filters such as ``page``/``limit``/city names are
ignored by the API, so the scraper only sends the numeric parameters.

Operation and property type are *not* sent as filters: a ``tipOper`` filter
drops rental records that the API files under the Venta bucket. Every city is
therefore queried across all operations and source records are guarded
locally for ``operacion == 'Arriendo'``, an accepted residential type and the
exact requested city.

No detail request is required; every contractual field is present in the
listing payload.

Pagination terminates on the first empty ``propiedades`` array. The reported
``total`` is recomputed per request and every page is cached independently, so
totals legitimately differ between pages of one crawl (verified live); a full
crawl still has to see at least the smallest reported total or it raises rather
than storing a partial inventory.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Iterable
from typing import Final, TypedDict
from urllib.parse import quote

from scrape.cities import normalize_city, resolve_city
from scrape.fetcher import fetch_json
from scrape.normalize import (
    normalize_barrio,
    normalize_estrato,
    normalize_garaje,
    normalize_price,
)

logger = logging.getLogger(__name__)

PORTAL: Final = "escalainmobiliaria"
PREFIX: Final = "ESC"
BASE_URL: Final = "https://escalainmobiliaria.com.co"
API_BASE: Final = f"{BASE_URL}/api/v2/propiedades"
DETAIL_BASE: Final = f"{BASE_URL}/propiedad/"
PAGE_SIZE: Final = 100

# The API answers with HTTP 200 and a declared ``error``/``detail`` payload when
# its upstream times out (verified live); one such response must not abort a
# whole city crawl.
_PAGE_ATTEMPTS: Final = 3
_PAGE_RETRY_DELAY_SECONDS: Final = 0.5

# Verified from /api/v2/catalogos on 2026-10-22.
CITY_IDS: Final[dict[str, int]] = {
    "medellin": 496,
    "envigado": 291,
    "itagui": 389,
    "la-estrella": 416,
    "sabaneta": 698,
}

# Source type ids use a different numbering than Portada: casa is 1,
# apartamento 2 and apartaestudio 14.
RESIDENTIAL_TYPES: Final[dict[str, int]] = {
    "apartamento": 2,
    "casa": 1,
    "apartaestudio": 14,
}
_SOURCE_TYPE_BY_ID: Final[dict[int, str]] = {
    type_id: name for name, type_id in RESIDENTIAL_TYPES.items()
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

_RENTAL_OPERATION: Final = "arriendo"


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


def build_page_url(city_id: int, pagina: int, limite: int = PAGE_SIZE) -> str:
    """Build the numeric-only API URL for one city and zero-based page."""
    if not isinstance(city_id, int) or isinstance(city_id, bool) or city_id < 1:
        raise ValueError("city_id must be a positive integer")
    if not isinstance(pagina, int) or isinstance(pagina, bool) or pagina < 0:
        raise ValueError("pagina must be a non-negative integer")
    if not isinstance(limite, int) or isinstance(limite, bool):
        raise ValueError("limite must be an integer")
    if not 1 <= limite <= PAGE_SIZE:
        raise ValueError(f"limite must be between 1 and {PAGE_SIZE}")
    return f"{API_BASE}?ciudad={city_id}&limite={limite}&pagina={pagina}"


def _source_key(raw) -> str:
    """Fold one source label for exact comparison without merging subtypes.

    ``normalize_city`` is the shared NFKD/casefold helper; using it here keeps
    the folding rules identical across portals without a second implementation.
    """
    if raw is None or isinstance(raw, bool):
        return ""
    return normalize_city(str(raw))


def _record_city_matches(raw, city_key: str, city_id: int) -> bool:
    """Accept a record only when its city is the requested city."""
    if raw is None or isinstance(raw, bool):
        return False
    if isinstance(raw, int):
        return raw == city_id
    if isinstance(raw, float):
        return raw.is_integer() and int(raw) == city_id
    text = str(raw).strip()
    if not text:
        return False
    if text.isdigit():
        return int(text) == city_id
    return normalize_city(text) == city_key


def _source_tipo(raw) -> str:
    """Return the canonical type for an *exact* source type, else ``''``.

    String matching is exact after folding: a mixed source label such as
    ``Casa-Finca`` or ``Casa Local`` must never be published as ``casa``.
    """
    if raw is None or isinstance(raw, bool):
        return ""
    if isinstance(raw, int):
        return _SOURCE_TYPE_BY_ID.get(raw, "")
    text = str(raw).strip()
    if not text:
        return ""
    if text.isdigit():
        return _SOURCE_TYPE_BY_ID.get(int(text), "")
    key = _source_key(text)
    return key if key in RESIDENTIAL_TYPES else ""


def _int_value(raw) -> int:
    """Normalize numeric API values, including decimal float values."""
    if raw is None or isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if math.isfinite(raw) else 0
    text = str(raw).strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def _price_value(raw) -> int:
    """Normalize a COP price without digit-joining decimal float strings."""
    if raw is None or isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if math.isfinite(raw) else 0
    text = str(raw).strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return normalize_price(text)


def _code_value(raw) -> str:
    """Return a stable source code as text, rejecting unusable identities."""
    if raw is None or isinstance(raw, bool):
        return ""
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        return str(int(raw)) if math.isfinite(raw) and raw.is_integer() else ""
    if not isinstance(raw, str):
        return ""
    return raw.strip()


def _validate_page(data) -> tuple[list[dict], int]:
    """Validate one API page, rejecting error payloads and unusable identities."""
    if not isinstance(data, dict):
        raise RuntimeError("Escala API returned no JSON object")

    records = data.get("propiedades")
    if not isinstance(records, list):
        message = data.get("message") or data.get("error")
        detail = f": {message}" if message else ""
        raise RuntimeError(
            f"Escala API returned an invalid payload: expected propiedades{detail}"
        )

    for item in records:
        if not isinstance(item, dict):
            raise RuntimeError("Escala API returned a malformed propiedad record")
        if not _code_value(item.get("codigo")):
            raise RuntimeError(
                "Escala API returned a propiedad without a usable codigo"
            )

    total = data.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise RuntimeError("Escala API response is missing a valid total")
    return records, total


def _build_listing(item: dict, city_key: str, city_id: int) -> Listing | None:
    """Map one validated source record to the canonical contract."""
    code = _code_value(item["codigo"])

    if not _record_city_matches(item.get("ciudad"), city_key, city_id):
        logger.debug("Skipping Escala record %s from another city", code)
        return None

    if _source_key(item.get("operacion")) != _RENTAL_OPERATION:
        logger.debug("Skipping Escala record %s outside Arriendo", code)
        return None

    tipo = _source_tipo(item.get("tipo"))
    if not tipo:
        logger.debug(
            "Skipping Escala record %s with unsupported tipo %r",
            code,
            item.get("tipo"),
        )
        return None

    return {
        "id": f"{PREFIX}-{code}",
        "portal": PORTAL,
        "tipo": tipo,
        "precio": _price_value(item.get("precio")),
        "area": _int_value(item.get("area")),
        "habitaciones": _int_value(item.get("habitaciones")),
        "banos": _int_value(item.get("banos")),
        "parqueaderos": (
            _int_value(item.get("parqueadero"))
            or normalize_garaje(item.get("parqueadero"))
        ),
        "estrato": normalize_estrato(item.get("estrato")),
        "barrio": normalize_barrio(item.get("barrio")),
        "url": f"{DETAIL_BASE}{quote(code, safe='-')}",
    }


def parse_search_response(data, ciudad: str) -> list[Listing]:
    """Parse and normalize one API page for a canonical requested city."""
    city_key = resolve_city(ciudad)
    city_id = CITY_IDS[city_key]
    records, _total = _validate_page(data)
    listings: list[Listing] = []
    for item in records:
        listing = _build_listing(item, city_key, city_id)
        if listing is not None:
            listings.append(listing)
    return listings


def deduplicate_listings(rows: Iterable[Listing]) -> list[Listing]:
    """Keep the first row for each stable Escala code."""
    seen: set[str] = set()
    unique: list[Listing] = []
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        unique.append(row)
    return unique


def _validate_max_pages(max_pages: int | None) -> None:
    if max_pages is not None and (
        not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1
    ):
        raise ValueError("max_pages must be at least 1")


def _is_declared_failure(data) -> bool:
    """True when the API answered with a declared failure instead of a page.

    Verified live on 2026-10-22: ``/api/v2/propiedades`` can return HTTP 200
    with ``{"error": "No se pudieron cargar las propiedades", "detail":
    "The operation was aborted due to timeout"}`` and no ``propiedades`` key.
    That is a transient upstream failure, not an inventory statement.
    """
    return data is None or (isinstance(data, dict) and "propiedades" not in data)


def _fetch_page(city_id: int, pagina: int) -> dict:
    """Fetch one page, retrying only declared upstream failures.

    Callers validate the payload before consuming it, so a payload that keeps
    failing here is reported once with the city and page that failed instead
    of aborting a whole city crawl on one transient timeout.
    """
    for attempt in range(1, _PAGE_ATTEMPTS + 1):
        data = fetch_json(build_page_url(city_id, pagina, PAGE_SIZE))
        if not _is_declared_failure(data):
            return data
        logger.warning(
            "Escala API city %d page %d failed (attempt %d/%d)",
            city_id,
            pagina,
            attempt,
            _PAGE_ATTEMPTS,
        )
        if attempt < _PAGE_ATTEMPTS:
            time.sleep(_PAGE_RETRY_DELAY_SECONDS)

    raise RuntimeError(
        f"Escala API failed for city {city_id} page {pagina} "
        f"after {_PAGE_ATTEMPTS} attempts"
    )


def _scrape_city(
    city_key: str,
    sample_only: bool,
    max_pages: int | None,
    verbose: bool,
) -> list[Listing]:
    """Crawl every operation for one city and keep locally verified rentals.

    Termination is the first empty ``propiedades`` array, not the reported
    ``total``: the API recomputes ``total`` on every request and serves each
    page from an independent CDN cache entry, so totals legitimately differ
    between pages of one crawl. The reported totals are therefore advisory
    progress metadata plus a completeness floor: a full crawl must have seen
    at least the smallest total the API ever reported, otherwise records were
    lost (repeated, skipped, truncated or inconsistent pages) and the crawl
    raises instead of storing a partial inventory.
    """
    city_id = CITY_IDS[city_key]
    page_cap = max_pages if max_pages is not None else (1 if sample_only else None)

    listings: list[Listing] = []
    seen_codes: set[str] = set()
    reported_totals: list[int] = []
    pagina = 0

    while True:
        if page_cap is not None and pagina >= page_cap:
            break

        records, page_total = _validate_page(_fetch_page(city_id, pagina))

        if not records:
            if not reported_totals:
                # An empty first page with a non-zero total is contradictory;
                # an empty first page with total 0 is a genuinely empty city.
                if page_total:
                    raise RuntimeError(
                        f"Escala pagination for {city_key} returned an empty "
                        f"page 0 while reporting total {page_total}"
                    )
                break
            # Totals from empty pages are ignored: a stale cached empty page
            # must not lower the completeness floor of a full crawl.
            floor = min(reported_totals)
            if len(seen_codes) < floor:
                raise RuntimeError(
                    f"Escala pagination for {city_key} ended early: page {pagina} "
                    f"is empty after {len(seen_codes)}/{floor} records"
                )
            break

        reported_totals.append(page_total)

        page_keys = [_code_value(item["codigo"]) for item in records]
        new_keys = [key for key in page_keys if key not in seen_codes]
        if not new_keys:
            raise RuntimeError(
                f"Escala pagination for {city_key} repeated page {pagina}"
            )
        seen_codes.update(new_keys)
        if len(seen_codes) > max(reported_totals):
            raise RuntimeError(
                f"Escala pagination for {city_key} returned {len(seen_codes)} "
                f"records but reported a total of at most {max(reported_totals)}"
            )

        for item in records:
            listing = _build_listing(item, city_key, city_id)
            if listing is not None:
                listings.append(listing)

        if verbose:
            logger.info(
                "Escala: %s page %d -> %d/%d records, %d rentals",
                city_key,
                pagina,
                len(seen_codes),
                page_total,
                len(listings),
            )
        pagina += 1

    if verbose and len(set(reported_totals)) > 1:
        logger.info(
            "Escala: %s live total drifted %d..%d across %d pages; "
            "kept %d unique source records",
            city_key,
            min(reported_totals),
            max(reported_totals),
            len(reported_totals),
            len(seen_codes),
        )

    return deduplicate_listings(listings)


def scrape_cities(
    ciudades: Iterable[str],
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> dict[str, list[Listing]]:
    """Scrape each requested city once, keyed by canonical city name."""
    _validate_max_pages(max_pages)
    requested: list[str] = []
    for value in ciudades:
        key = resolve_city(value)
        if key not in requested:
            requested.append(key)
    return {
        city_key: _scrape_city(
            city_key,
            sample_only=sample_only,
            max_pages=max_pages,
            verbose=verbose,
        )
        for city_key in requested
    }


def scrape(
    ciudad: str = "medellin",
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> list[Listing]:
    """Scrape Escala's rental inventory for one canonical city."""
    _validate_max_pages(max_pages)
    city_key = resolve_city(ciudad)
    return _scrape_city(
        city_key,
        sample_only=sample_only,
        max_pages=max_pages,
        verbose=verbose,
    )
