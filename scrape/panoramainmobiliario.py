"""Panorama Inmobiliario two-phase HTML rental scraper.

Phase A fetches the three verified residential type streams from Panorama's
Wasi search endpoint.  Phase B enriches those rows from the official detail
pages, primarily with ``Zona / barrio`` and ``Estrato``.

The search result title, image alt text, and JSON-LD are intentionally not
used for the property type.  The filtered source stream and its structured
card tag are the type authority; detail-page type text is only a validation
signal.
"""

from __future__ import annotations

import logging
from typing import TypeAlias
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from scrape.fetcher import bulk_fetch, fetch_page
from scrape.normalize import normalize_barrio, normalize_estrato, normalize_price, normalize_tipo
from scrape.validator import validate

logger = logging.getLogger(__name__)

BASE_URL = "https://panoramainmobiliario.co"
PORTAL = "panoramainmobiliario"
PREFIX = "PAN"
CITY_IDS = {"medellin": "496"}
RESIDENTIAL_TYPES = ("apartaestudio", "apartamento", "casa")
TYPE_IDS = {"apartaestudio": "14", "apartamento": "2", "casa": "1"}
PER_PAGE = 12
MAX_PAGE_ATTEMPTS = 2
POSTGRES_INTEGER_MAX = 2_147_483_647

COLUMNS = [
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
]

Listing: TypeAlias = dict[str, str | int]
DetailFields: TypeAlias = dict[str, str | int]


class UnsupportedCityError(KeyError):
    """Raised when a city has no verified Panorama mapping."""


def _empty_listing() -> Listing:
    row: Listing = {column: "" for column in COLUMNS}
    row["portal"] = PORTAL
    for column in ("precio", "area", "habitaciones", "banos", "parqueaderos", "estrato"):
        row[column] = 0
    return row


def _city_id(ciudad: str) -> str:
    normalized = ciudad.casefold().replace("í", "i")
    city_id = CITY_IDS.get(normalized)
    if city_id is None:
        raise UnsupportedCityError(
            f"Panorama mapping is scoped to Medellin; got ciudad={ciudad}"
        )
    return city_id


def build_page_url(
    page: int,
    ciudad: str = "medellin",
    property_type: str = "apartamento",
) -> str:
    """Build Panorama's canonical filtered ``/search`` URL."""
    if page < 1:
        raise ValueError("page must be at least 1")
    city_id = _city_id(ciudad)
    if property_type not in TYPE_IDS:
        raise ValueError(f"unsupported residential type: {property_type}")

    query = [
        ("id_city", city_id),
        ("id_property_type", TYPE_IDS[property_type]),
        ("business_type[0]", "for_rent"),
        ("order_by", "created_at"),
        ("order", "desc"),
        ("page", str(page)),
        ("for_sale", "0"),
        ("for_rent", "1"),
        ("for_temporary_rent", "0"),
        ("for_transfer", "0"),
        ("lax_business_type", "1"),
    ]
    return f"{BASE_URL}/search?{urlencode(query)}"


def _lines(node: Tag | BeautifulSoup) -> list[str]:
    """Return non-empty visible text lines from a parsed node."""
    return [
        line.strip()
        for line in node.get_text("\n", strip=True).splitlines()
        if line.strip()
    ]


def _first_number(raw: str) -> int:
    """Return the first contiguous decimal number in visible text."""
    digits: list[str] = []
    started = False
    for character in raw:
        if character.isdecimal():
            digits.append(character)
            started = True
        elif started:
            break
    return int("".join(digits)) if digits else 0


def _detail_url(raw: str) -> str:
    """Return an official detail URL with a numeric final path segment."""
    absolute = urljoin(BASE_URL, raw.strip())
    parsed = urlparse(absolute)
    if parsed.netloc != urlparse(BASE_URL).netloc:
        return ""
    path = parsed.path.rstrip("/")
    code = path.rsplit("/", 1)[-1] if path else ""
    if not code.isdecimal():
        return ""
    return urlunparse(parsed._replace(query="", fragment=""))


def _code_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def _card_url(card: Tag) -> str:
    """Select the first official detail URL from any card anchor."""
    for anchor in card.find_all("a", href=True):
        url = _detail_url(str(anchor.get("href", "")))
        if url:
            return url
    return ""


def _rental_price(card: Tag) -> tuple[int, bool]:
    """Read only a price from a card block explicitly labelled Alquiler."""
    for block in card.select(".areaPrecio .row > div"):
        text = block.get_text(" ", strip=True)
        if "alquiler" in text.casefold() and "$" in text:
            price = normalize_price(text)
            prefix = []
            for character in text:
                if character.isdecimal():
                    break
                prefix.append(character)
            if "-" in prefix:
                price = -price
            return price, True
    return 0, False


def _card_metric(card: Tag, labels: tuple[str, ...]) -> int:
    for metric in card.select(".info_details .col-6"):
        text = metric.get_text(" ", strip=True)
        folded = text.casefold()
        if any(label in folded for label in labels):
            return _first_number(text)
    return 0


def _parse_card(card: Tag, property_type: str) -> Listing | None:
    """Extract card fields using the verified filtered type as authority."""
    if property_type not in RESIDENTIAL_TYPES:
        return None

    url = _card_url(card)
    code = _code_from_url(url)
    if not url or not code:
        return None

    card_type_node = card.select_one(".tag1")
    card_type = normalize_tipo(card_type_node.get_text(" ", strip=True)) if card_type_node else ""
    if card_type and card_type != property_type:
        logger.warning(
            "Panorama card %s has type %s in the filtered %s stream; skipping",
            code,
            card_type,
            property_type,
        )
        return None

    price, has_rental_offer = _rental_price(card)
    if not has_rental_offer:
        logger.warning("Panorama card %s has no explicit Alquiler offer; skipping", code)
        return None
    if price < 0 or price > POSTGRES_INTEGER_MAX:
        logger.warning(
            "Skipping Panorama listing PAN-%s: precio=%s outside PostgreSQL INTEGER range",
            code,
            price,
        )
        return None

    row = _empty_listing()
    row.update(
        {
            "id": f"{PREFIX}-{code}",
            "tipo": property_type,
            "precio": price,
            "area": _card_metric(card, ("área", "area")),
            "habitaciones": _card_metric(card, ("alcoba", "habitación", "habitacion")),
            "banos": _card_metric(card, ("baño", "bano")),
            "parqueaderos": _card_metric(card, ("garaje", "parqueadero")),
            "url": url,
        }
    )
    return row


def _parse_search_page(html: str, property_type: str) -> tuple[list[Listing], int]:
    soup = BeautifulSoup(html or "", "html.parser")
    cards = soup.select(".list-properties .item.item_small")
    rows: list[Listing] = []
    seen_ids: set[str] = set()
    for card in cards:
        row = _parse_card(card, property_type)
        if row is None or row["id"] in seen_ids:
            continue
        seen_ids.add(str(row["id"]))
        rows.append(row)
    return rows, len(cards)


def parse_search_page(html: str, property_type: str) -> list[Listing]:
    """Parse accepted residential cards from one filtered search page."""
    return _parse_search_page(html, property_type)[0]


def _fetch_search_page(url: str, property_type: str) -> tuple[list[Listing], int]:
    """Retry incomplete page responses without retrying full pages."""
    best_rows: list[Listing] = []
    best_card_count = -1

    for attempt in range(MAX_PAGE_ATTEMPTS):
        html = fetch_page(url)
        page_rows, card_count = _parse_search_page(html or "", property_type)
        if card_count > best_card_count:
            best_rows = page_rows
            best_card_count = card_count

        if card_count >= PER_PAGE:
            break
        if attempt + 1 < MAX_PAGE_ATTEMPTS:
            logger.debug(
                "Panorama page response incomplete (%s cards) for %s; retrying (%d/%d)",
                card_count,
                url,
                attempt + 1,
                MAX_PAGE_ATTEMPTS,
            )

    return best_rows, max(best_card_count, 0)


def _label_value(text: str) -> tuple[str, str]:
    if ":" not in text:
        return "", ""
    label, value = text.split(":", 1)
    return label.strip().casefold(), value.strip()


def parse_detail_page(html: str) -> DetailFields:
    """Extract explicit structured fields from a Panorama detail page."""
    fields: DetailFields = {
        "tipo": "",
        "area": 0,
        "habitaciones": 0,
        "banos": 0,
        "parqueaderos": 0,
        "estrato": 0,
        "barrio": "",
    }
    soup = BeautifulSoup(html or "", "html.parser")
    info_list: Tag | None = None
    for candidate in soup.select("ul.list-info-2"):
        if any("tipo de inmueble" in line.casefold() for line in _lines(candidate)):
            info_list = candidate
            break
    if info_list is None:
        return fields

    for item in info_list.select("li"):
        label, value = _label_value(item.get_text(" ", strip=True))
        if label == "tipo de inmueble":
            fields["tipo"] = normalize_tipo(value)
        elif label in ("área construida", "area construida"):
            fields["area"] = _first_number(value)
        elif label in ("alcobas", "habitaciones"):
            fields["habitaciones"] = _first_number(value)
        elif label in ("baño", "baños", "bano", "banos"):
            fields["banos"] = _first_number(value)
        elif label in ("garaje", "parqueadero", "parqueaderos"):
            fields["parqueaderos"] = _first_number(value)
        elif label == "estrato":
            fields["estrato"] = normalize_estrato(value)
        elif label in ("zona / barrio", "barrio", "sector"):
            fields["barrio"] = normalize_barrio(value)

    return fields


def merge_detail(row: Listing, detail: DetailFields) -> bool:
    """Merge positive detail values without replacing the filtered type."""
    detail_type = str(detail.get("tipo", ""))
    if detail_type and detail_type not in RESIDENTIAL_TYPES:
        logger.warning("Panorama detail %s has non-residential type %s", row["id"], detail_type)
        return False
    if detail_type and detail_type != row["tipo"]:
        logger.warning(
            "Panorama detail %s type %s differs from filtered type %s; keeping filter type",
            row["id"],
            detail_type,
            row["tipo"],
        )

    for field in ("area", "habitaciones", "banos", "parqueaderos", "estrato"):
        value = detail.get(field, 0)
        if row[field] == 0 and isinstance(value, int) and value > 0:
            row[field] = value
    if not row["barrio"] and detail.get("barrio"):
        row["barrio"] = str(detail["barrio"])
    return True


def _phase_a(ciudad: str, max_pages: int | None, verbose: bool) -> list[Listing]:
    """Fetch all three filtered streams and deduplicate by PAN-code."""
    by_id: dict[str, Listing] = {}
    for property_type in RESIDENTIAL_TYPES:
        page = 1
        while max_pages is None or page <= max_pages:
            url = build_page_url(page, ciudad, property_type)
            page_rows, card_count = _fetch_search_page(url, property_type)
            for row in page_rows:
                by_id.setdefault(str(row["id"]), row)
            if verbose:
                logger.info(
                    "Panorama %s page %d: %d cards, %d unique",
                    property_type,
                    page,
                    card_count,
                    len(by_id),
                )
            if card_count == 0 or card_count < PER_PAGE:
                break
            page += 1
    return list(by_id.values())


def _phase_b(listings: list[Listing], verbose: bool) -> list[Listing]:
    """Fetch detail pages and merge structured enrichment fields."""
    detail_urls = [str(row["url"]) for row in listings if row["url"]]
    if not detail_urls:
        return listings

    detail_map = dict(bulk_fetch(detail_urls))
    for row in listings:
        html = detail_map.get(str(row["url"]), "")
        if html:
            merge_detail(row, parse_detail_page(html))
        warnings = validate(row)
        if verbose:
            for warning in warnings:
                logger.warning("%s: %s", row["id"], warning)
    return listings


def scrape(
    ciudad: str = "medellin",
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> list[Listing]:
    """Scrape Panorama Medellín rentals using filtered two-phase HTML."""
    try:
        _city_id(ciudad)
    except UnsupportedCityError as error:
        logger.warning(str(error))
        return []

    page_limit = 1 if sample_only and max_pages is None else max_pages
    listings = _phase_a(ciudad, page_limit, verbose)
    if not listings:
        return []
    return _phase_b(listings, verbose)
