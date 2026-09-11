"""La Palma Inmobiliaria (LPI) two-phase rental scraper."""

import logging
from typing import TypedDict
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from scrape.detail_reuse import (
    DetailReusePlan,
    full_detail_plan,
    plan_active_detail_reuse,
)
from scrape.fetcher import bulk_fetch, fetch_page
from scrape.normalize import normalize_barrio, normalize_price, normalize_tipo
from scrape.validator import validate

logger = logging.getLogger(__name__)

_BASE_URL = "https://lapalmainmobiliaria.com.co"
_PORTAL = "lapalmainmobiliaria"
_PREFIX = "LPI"
_CITY_IDS = {"medellin": "496"}
RESIDENTIAL_TYPES = ("apartamento", "casa", "apartaestudio")
_TYPE_IDS = {"apartamento": "2", "casa": "1", "apartaestudio": "14"}
_COLUMNS = ["id", "portal", "tipo", "precio", "area", "habitaciones", "banos", "parqueaderos", "estrato", "barrio", "url"]
_TYPE_WORDS = ("APARTAESTUDIO", "APARTAMENTO", "BODEGA", "OFICINA", "LOCAL", "CASA", "FINCA", "LOTE")
_UNAVAILABLE_WORDS = ("ALQUILADO", "ARRENDADO")
_UNAVAILABLE_DETAIL_MARKERS = ("NO SE ENCONTRO INMUEBLE",)
Listing = TypedDict("Listing", {"id": str, "portal": str, "tipo": str, "precio": int, "area": int, "habitaciones": int, "banos": int, "parqueaderos": int, "estrato": int, "barrio": str, "url": str})
DetailFields = TypedDict("DetailFields", {"estrato": int, "barrio": str})

_DETAIL_FIELDS = ("estrato", "barrio")
class UnsupportedCityError(KeyError): pass


def _fold(value: str) -> str:
    """Uppercase text while making Spanish labels accent-insensitive."""
    return value.upper().translate(str.maketrans("ÁÉÍÓÚÜÑ", "AEIOUUN"))


def _lines(node) -> list[str]:
    """Return non-empty visible text lines from a parsed HTML node."""
    return [line.strip() for line in node.get_text("\n", strip=True).splitlines() if line.strip()]


def _first_number(value: str) -> int:
    """Read the first contiguous integer in a label value."""
    digits = ""
    started = False
    for character in value:
        if character.isdecimal():
            digits += character
            started = True
        elif started:
            break
    return int(digits) if digits else 0


def _last_number(value: str) -> int:
    """Read the last contiguous integer before a field label."""
    digits = ""
    for character in reversed(value):
        if character.isdecimal():
            digits = character + digits
        elif digits:
            break
    return int(digits) if digits else 0


def _number_for_labels(lines: list[str], labels: tuple[str, ...]) -> int:
    """Extract a number adjacent to one of the supplied visible labels."""
    for index, line in enumerate(lines):
        folded = _fold(line)
        for label in labels:
            position = folded.find(label)
            if position < 0:
                continue
            if (
                position == 0
                and ":" not in line
                and index > 0
                and lines[index - 1].strip().isdecimal()
            ):
                return int(lines[index - 1].strip())
            before = _last_number(line[:position])
            if before:
                return before
            after = line[position + len(label) :]
            value = _first_number(after)
            if value or "0" in after:
                return value
            if index + 1 < len(lines) and lines[index + 1].strip().isdecimal():
                return int(lines[index + 1].strip())
    return 0


def _text_for_labels(lines: list[str], labels: tuple[str, ...]) -> str:
    """Extract the text after a colon-bearing visible label."""
    for index, line in enumerate(lines):
        folded = _fold(line)
        for label in labels:
            position = folded.find(label)
            if position < 0:
                continue
            value = line[position + len(label) :].strip()
            if value.startswith(":"):
                value = value[1:].strip()
            if not value and index + 1 < len(lines):
                value = lines[index + 1].strip()
            if value:
                return value
    return ""


def _listing_url(href: str) -> str:
    """Return an official detail URL whose final path segment is numeric."""
    url = urljoin(_BASE_URL, href.strip())
    parsed = urlparse(url)
    if parsed.netloc != urlparse(_BASE_URL).netloc:
        return ""
    path = parsed.path.rstrip("/")
    code = path.rsplit("/", 1)[-1] if path else ""
    return url if code.isdecimal() else ""


def _code_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def _unique_listing_urls(node) -> set[str]:
    return {url for anchor in node.find_all("a", href=True) if (url := _listing_url(str(anchor.get("href", ""))))}


def _card_for_anchor(anchor):
    for parent in anchor.parents:
        if getattr(parent, "name", "") != "div":
            continue
        if len(_unique_listing_urls(parent)) != 1:
            continue
        text = _fold(" ".join(_lines(parent)))
        if "ARRIENDO" in text and "AREA" in text and "ALCOBA" in text:
            return parent
    return None


def _is_unavailable(card) -> bool:
    lines = {_fold(line) for line in _lines(card)}
    return any(any(word in line for word in _UNAVAILABLE_WORDS) for line in lines)



def _is_unavailable_detail(html: str) -> bool:
    """Recognize La Palma's explicit detail-page not-found response."""
    soup = BeautifulSoup(html, "html.parser")
    text = _fold(" ".join(_lines(soup)))
    return any(marker in text for marker in _UNAVAILABLE_DETAIL_MARKERS)

def _extract_type(lines: list[str]) -> str:
    text = _fold(" ".join(lines))
    if "CASA COMERCIAL" in text or "USO COMERCIAL" in text:
        return ""
    for line in lines:
        folded = _fold(line)
        for type_word in _TYPE_WORDS:
            if type_word in folded:
                return normalize_tipo(type_word.lower())
    return ""


def _extract_card(card, url: str) -> Listing:
    lines = _lines(card)
    listing = dict.fromkeys(_COLUMNS, "")
    listing.update(
        {
            "id": f"{_PREFIX}-{_code_from_url(url)}",
            "portal": _PORTAL,
            "tipo": _extract_type(lines),
            "precio": 0,
            "area": _number_for_labels(lines, ("AREA",)),
            "habitaciones": _number_for_labels(lines, ("ALCOBA", "HABIT")),
            "banos": _number_for_labels(lines, ("BANO",)),
            "parqueaderos": _number_for_labels(lines, ("PARQUEADER", "GARAJE")),
            "estrato": 0,
            "barrio": "",
            "url": url,
        }
    )
    for line in lines:
        if "$" in line:
            listing["precio"] = normalize_price(line)
            break
    return listing


def _parse_page(html: str) -> tuple[list[Listing], set[str]]:
    """Parse available rows and all source IDs from one search page."""
    soup = BeautifulSoup(html, "html.parser")
    listings: list[Listing] = []
    source_ids: set[str] = set()
    seen_urls: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = _listing_url(str(anchor.get("href", "")))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        code = _code_from_url(url)
        source_ids.add(code)
        card = _card_for_anchor(anchor)
        if card is not None and not _is_unavailable(card):
            listings.append(_extract_card(card, url))
    return listings, source_ids


def parse_search_page(html: str) -> list[Listing]:
    """Parse active rental cards from one official search page."""
    return _parse_page(html)[0]


def parse_detail_page(html: str) -> DetailFields:
    """Extract only explicit detail fields added by La Palma's detail page."""
    soup = BeautifulSoup(html, "html.parser")
    lines = _lines(soup)
    return {
        "estrato": _number_for_labels(lines, ("ESTRATO",)),
        "barrio": normalize_barrio(
            _text_for_labels(lines, ("ZONA", "BARRIO", "SECTOR"))
        ),
    }


def build_page_url(page: int, ciudad: str = "medellin", property_type: str | None = None) -> str:
    """Build the official search URL with optional residential type filtering."""
    city_id = _CITY_IDS.get(ciudad.casefold())
    if city_id is None:
        raise UnsupportedCityError(
            f"La Palma only supports the verified Medellin city filter: {ciudad}"
        )
    query = [
        ("id_city", city_id),
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
    if property_type is not None:
        query.insert(1, ("id_property_type", _TYPE_IDS[property_type]))
    return f"{_BASE_URL}/search?{urlencode(query)}"


def _phase_a(ciudad: str, max_pages: int | None, verbose: bool) -> list[Listing]:
    """Walk pages until an empty or stale page and deduplicate source IDs."""
    listings: list[Listing] = []
    seen_ids: set[str] = set()
    for property_type in RESIDENTIAL_TYPES:
        source_ids_seen: set[str] = set()
        page = 1
        while max_pages is None or page <= max_pages:
            html = fetch_page(build_page_url(page, ciudad, property_type))
            if not html:
                break
            page_rows, source_ids = _parse_page(html)
            if not source_ids - source_ids_seen:
                break
            source_ids_seen.update(source_ids)
            for row in page_rows:
                if row["id"] not in seen_ids:
                    listings.append(row)
                    seen_ids.add(row["id"])
            if verbose:
                logger.info("La Palma %s page %d: %d cards", property_type, page, len(page_rows))
            page += 1
    return listings


def _plan_phase_b(
    listings: list[Listing],
    ciudad: str,
    reuse_unchanged_details: bool,
) -> DetailReusePlan:
    """Reuse cached fields while probing every detail page for availability."""
    if not reuse_unchanged_details:
        return full_detail_plan(listings)

    plan = plan_active_detail_reuse(listings, _PORTAL, ciudad, _DETAIL_FIELDS)
    logger.info(
        "LPI detail reuse: %d cached; %d availability pages to fetch",
        plan.reused_count,
        len(listings),
    )
    print(
        "LPI detail reuse: "
        f"{plan.reused_count} cached; {len(listings)} availability pages fetched"
    )
    return plan


def _phase_b(
    detail_listings: list[Listing],
    listings: list[Listing],
    verbose: bool,
) -> list[Listing]:
    """Fetch every detail page, classify ghosts, and enrich outstanding rows."""
    # A price-stable cached row still needs a fresh response: the search card
    # can remain while La Palma serves its explicit not-found detail page.
    detail_url_set = {row["url"] for row in detail_listings if row["url"]}
    urls = [row["url"] for row in listings if row["url"]]
    detail_map = dict(bulk_fetch(urls))

    for row in listings:
        html = detail_map.get(row["url"], "")
        if not html:
            continue
        if _is_unavailable_detail(html):
            row["status"] = "unavailable"
        elif row["url"] in detail_url_set:
            row.update(parse_detail_page(html))

    for row in listings:
        if row.get("status") == "unavailable":
            continue
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
    reuse_unchanged_details: bool = False,
) -> list[Listing]:
    """Scrape La Palma's Medellin rental inventory using two phases."""
    if sample_only and max_pages is None:
        max_pages = 3
    listings = [
        row
        for row in _phase_a(ciudad, max_pages, verbose)
        if row["tipo"] in RESIDENTIAL_TYPES
    ]
    if not listings:
        return []
    plan = _plan_phase_b(listings, ciudad, reuse_unchanged_details)
    return _phase_b(plan.detail_listings, listings, verbose)
