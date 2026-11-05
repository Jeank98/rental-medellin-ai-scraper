"""Arrendamientos SantaFe (ASF) — two-phase JSON API scraper.

The portal was rebuilt as a Next.js app: the old server-rendered
``/propiedades`` HTML (``.property-card``) no longer exists and the page ships
only a client shell. Both phases now read the app's own JSON endpoints:

Phase A: ``/apisf/properties?page=N&oferta=Arriendo&ciudad=<label>`` (12/page).
Phase B: ``/apisf/property/<code>`` for estrato, parqueaderos and the
         authoritative area/rooms.

Both responses are wrapped in ``<html><body>…</body></html>``, so they are
unwrapped before parsing.
"""

import json
import logging
import math
import re
from typing import Final
from urllib.parse import quote

from scrape.detail_reuse import (
    DetailReusePlan,
    full_detail_plan,
    plan_active_detail_reuse,
)
from scrape.fetcher import bulk_fetch, fetch_page
from scrape.normalize import (
    normalize_barrio,
    normalize_estrato,
    normalize_price,
    normalize_tipo,
)
from scrape.validator import validate

logger = logging.getLogger(__name__)

PORTAL: Final = "arrendamientossantafe"
_BASE_URL: Final = "https://arrendamientossantafe.com"
_API_SEARCH: Final = f"{_BASE_URL}/apisf/properties"
_API_DETAIL: Final = f"{_BASE_URL}/apisf/property"
_PER_PAGE: Final = 12
_DETAIL_WORKERS: Final = 8

CITY_LABELS: Final[dict[str, str]] = {
    "medellin": "Medellín",
    "medellín": "Medellín",
    "envigado": "Envigado",
    "itagui": "Itagüí",
    "itagüí": "Itagüí",
    "sabaneta": "Sabaneta",
    "la estrella": "La Estrella",
}

RESIDENTIAL_TYPES: Final = {"apartamento", "apartaestudio", "casa"}

_DETAIL_FIELDS = ("banos", "estrato", "parqueaderos")

_WRAPPER_RE = re.compile(r"^\s*<html><body>|</body></html>\s*$", re.IGNORECASE)


def _plan_phase_b(
    listings: list[dict],
    ciudad: str,
    reuse_unchanged_details: bool,
) -> DetailReusePlan:
    """Select detail requests, falling back to the complete current path."""
    if not reuse_unchanged_details:
        return full_detail_plan(listings)

    plan = plan_active_detail_reuse(
        listings,
        PORTAL,
        ciudad,
        _DETAIL_FIELDS,
    )
    logger.info(
        "ASF detail reuse: %d reused, %d detail pages to fetch",
        plan.reused_count,
        plan.detail_fetch_count,
    )
    print(
        "ASF detail reuse: "
        f"{plan.reused_count} reused; {plan.detail_fetch_count} detail pages fetched"
    )
    return plan


class UnsupportedCityError(KeyError):
    """Raised when the requested city has no verified SantaFe filter."""


def resolve_city_label(ciudad: str) -> str:
    key = " ".join(str(ciudad).strip().casefold().replace("-", " ").split())
    if key in CITY_LABELS:
        return CITY_LABELS[key]
    known = ["medellin", "envigado", "itagui", "sabaneta", "la estrella"]
    raise UnsupportedCityError(
        f"SantaFe has no verified filter for {ciudad!r}; known: {known}"
    )


def _unwrap(raw: str) -> str:
    return _WRAPPER_RE.sub("", str(raw).strip())


def search_url(page: int, ciudad_label: str) -> str:
    return (
        f"{_API_SEARCH}?page={page}&oferta=Arriendo"
        f"&ciudad={quote(ciudad_label)}"
    )


def detail_url(code: str) -> str:
    return f"{_API_DETAIL}/{code}"


def parse_json_payload(raw: str) -> dict:
    body = _unwrap(raw)
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError(f"SantaFe returned a non-JSON payload: {error}") from error


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
    """Map one search record to the 11-column schema (detail fields still 0)."""
    code = str(item.get("codigo") or item.get("id") or "").strip()
    if not code:
        return None

    tipo = normalize_tipo(item.get("type") or item.get("tipo") or "")
    if tipo not in RESIDENTIAL_TYPES:
        return None

    precio = _int(item.get("price_raw")) or normalize_price(item.get("price") or "")
    if precio <= 0:
        return None

    return {
        "id": f"ASF-{code}",
        "portal": PORTAL,
        "tipo": tipo,
        "precio": precio,
        "area": _int(str(item.get("size") or "").split("M")[0]),
        "habitaciones": _int(item.get("bedrooms")),
        "banos": _int(item.get("bathrooms")),
        "parqueaderos": _int(item.get("parqueaderos")),
        "estrato": 0,
        "barrio": normalize_barrio(item.get("location") or ""),
        "url": f"{_BASE_URL}{item.get('url') or f'/propiedad/{code}'}",
    }


def _apply_detail(listing: dict, detail: dict) -> None:
    """Overlay the authoritative detail fields onto a listing."""
    area = _int(detail.get("area"))
    if area:
        listing["area"] = area
    for field, key in (
        ("habitaciones", "habitaciones"),
        ("banos", "banos"),
        ("parqueaderos", "parqueaderos"),
    ):
        value = _int(detail.get(key))
        if value:
            listing[field] = value
    estrato = normalize_estrato(_int(detail.get("estrato")))
    if estrato:
        listing["estrato"] = estrato
    if detail.get("sector"):
        listing["barrio"] = normalize_barrio(detail["sector"]) or listing["barrio"]
    precio = _int(detail.get("price_raw"))
    if precio > 0:
        listing["precio"] = precio


def _phase_b(listings: list[dict], verbose: bool = False) -> list[dict]:
    """Phase B: fetch detail JSON per listing and merge the richer fields."""
    targets = [listing for listing in listings if listing["id"].startswith("ASF-")]
    if not targets:
        return listings

    codes = [listing["id"].split("ASF-", 1)[1] for listing in targets]
    urls = [detail_url(code) for code in codes]

    logging.getLogger("scrapling").setLevel(logging.WARNING)
    try:
        results = bulk_fetch(urls, max_workers=_DETAIL_WORKERS)
    finally:
        logging.getLogger("scrapling").setLevel(logging.NOTSET)

    detail_map = dict(results)
    enriched = 0
    for listing, url in zip(targets, urls):
        raw = detail_map.get(url)
        if not raw:
            continue
        try:
            _apply_detail(listing, parse_json_payload(raw))
            enriched += 1
        except ValueError as error:
            if verbose:
                logger.warning("ASF detail parse failed for %s: %s", listing["id"], error)

    logger.info("ASF Phase B: %d/%d detailed", enriched, len(targets))
    return listings


def scrape(
    ciudad="medellin",
    sample_only=False,
    max_pages=None,
    verbose=False,
    reuse_unchanged_details: bool = False,
) -> list[dict]:
    """Scrape Arrendamientos SantaFe rentals for one municipality.

    Phase A: paginate the search API (12 per page, ``total``/``has_more``).
    Phase B: fetch each listing's detail JSON for estrato/parqueaderos.
    """
    label = resolve_city_label(ciudad)
    if sample_only and max_pages is None:
        max_pages = 3

    first = parse_json_payload(str(fetch_page(search_url(1, label))))
    total = _int(first.get("total"))
    total_pages = max(1, math.ceil(total / _PER_PAGE)) if total else 1
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)

    if verbose:
        logger.info("ASF: %s total=%s paginas=%d", label, total, total_pages)

    pages: list[dict] = [first]
    if total_pages > 1:
        rest_urls = [search_url(page, label) for page in range(2, total_pages + 1)]
        for _url, raw in bulk_fetch(rest_urls, max_workers=_DETAIL_WORKERS):
            if not raw:
                continue
            try:
                pages.append(parse_json_payload(raw))
            except ValueError:
                continue

    listings: list[dict] = []
    seen: set[str] = set()
    for payload in pages:
        for item in payload.get("results") or []:
            listing = to_listing(item)
            if listing is None or listing["id"] in seen:
                continue
            seen.add(listing["id"])
            validate(listing)
            listings.append(listing)

    if verbose:
        logger.info("ASF Phase A: %d listings from %d pages", len(listings), total_pages)

    if not listings:
        return []

    plan = _plan_phase_b(listings, ciudad, reuse_unchanged_details)
    _phase_b(plan.detail_listings, verbose=verbose)

    if sample_only:
        print(f"Sample: {len(listings)} listing(s) extracted")

    return listings
