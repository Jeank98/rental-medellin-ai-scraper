"""Total Bienes SAS scraper — canonical one-phase HTML pagination.

Residential type routes and two numbered Medellin pages bound the crawl; the
page-1 load-more repeats page-2 cards. IDs are deduplicated defensively, and
generic property links/rendered text avoid CSS selectors or detail requests.
"""

import logging
from collections.abc import Iterable
from typing import Final, TypedDict

from bs4 import BeautifulSoup
from bs4.element import Tag

from scrape.fetcher import fetch_page
from scrape.normalize import normalize_garaje, normalize_price, normalize_tipo
from scrape.validator import validate

logger = logging.getLogger(__name__)

BASE_URL: Final = "https://totalbienes.com"
RESIDENTIAL_TYPE_URLS: Final[tuple[str, ...]] = (
    f"{BASE_URL}/arriendo-apartamentos-medellin",
    f"{BASE_URL}/arriendo-casas-medellin",
    f"{BASE_URL}/arriendo-apartaestudios-medellin",
)
CANONICAL_PAGE_URLS: Final[tuple[str, ...]] = (
    f"{BASE_URL}/properties/medellin",
    f"{BASE_URL}/properties/medellin/pagina/2",
)
RESIDENTIAL_TYPES: Final[frozenset[str]] = frozenset(
    {"apartamento", "casa", "apartaestudio"}
)
_ZERO_BEDROOM_TYPES: Final = frozenset({"local", "oficina", "bodega", "lote", "finca"})
_COMMERCIAL_USE_MARKERS: Final = ("casa comercial", "uso comercial")


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


def _empty_listing() -> Listing:
    """Return an empty listing with canonical key order and defaults."""
    return {
        "id": "",
        "portal": "totalbienes",
        "tipo": "",
        "precio": 0,
        "area": 0,
        "habitaciones": 0,
        "banos": 0,
        "parqueaderos": 0,
        "estrato": 0,
        "barrio": "",
        "url": "",
    }


def _fragments(card: Tag) -> list[str]:
    """Return visible text plus semantic aria labels from a card."""
    fragments = [
        str(fragment).strip()
        for fragment in card.stripped_strings
        if str(fragment).strip()
    ]
    for element in card.find_all(True):
        label = element.get("aria-label")
        if label:
            fragments.append(str(label).strip())
    return fragments


def _number_from(text: str, start: int) -> int:
    """Read the first integer after a text offset, ignoring separators."""
    index = start
    while index < len(text) and not text[index].isdigit():
        index += 1
    digits: list[str] = []
    while index < len(text) and (text[index].isdigit() or text[index] in ".,"):
        if text[index].isdigit():
            digits.append(text[index])
        index += 1
    return int("".join(digits)) if digits else 0


def _number_before(text: str, marker_start: int) -> int:
    """Read the integer immediately before a unit marker such as m²."""
    index = marker_start - 1
    while index >= 0 and not text[index].isdigit():
        index -= 1
    digits: list[str] = []
    while index >= 0 and (text[index].isdigit() or text[index] in ".,"):
        if text[index].isdigit():
            digits.append(text[index])
        index -= 1
    return int("".join(reversed(digits))) if digits else 0


def _marker_position(text: str, markers: tuple[str, ...]) -> tuple[int, str] | None:
    """Find the earliest case-insensitive marker and return its spelling."""
    lowered = text.casefold()
    matches = [(lowered.find(marker.casefold()), marker) for marker in markers]
    matches = [(position, marker) for position, marker in matches if position >= 0]
    return min(matches) if matches else None


def _number_after(text: str, markers: tuple[str, ...]) -> int:
    """Extract a numeric field following one of its visible labels."""
    match = _marker_position(text, markers)
    if not match:
        return 0
    index = match[0] - 1
    while index >= 0 and text[index].isspace():
        index -= 1
    if index >= 0 and text[index].isdigit():
        end = index + 1
        while index >= 0 and (text[index].isdigit() or text[index] in ".,"):
            index -= 1
        return int(
            "".join(reversed(text[index + 1 : end].replace(".", "").replace(",", "")))
        )
    return _number_from(text, match[0] + len(match[1]))


def _extract_price(text: str) -> int:
    """Select the rental amount when a card contains sale and rental prices."""
    lowered = text.casefold()
    position = 0
    candidates: list[int] = []
    while True:
        marker = lowered.find("arriendo", position)
        if marker < 0:
            break
        dollar = text.find("$", marker, marker + 100)
        if dollar >= 0:
            value = _number_from(text, dollar + 1)
            if value:
                candidates.append(value)
        position = marker + len("arriendo")
    return candidates[-1] if candidates else normalize_price(text)


def _extract_area(text: str) -> int:
    """Extract the integer immediately preceding the square-meter unit."""
    match = _marker_position(text, ("m²", "m2", "mt2", "mts²"))
    return _number_before(text, match[0]) if match else 0


def _extract_tipo(fragments: list[str]) -> str:
    """Extract the property type from a card title fragment."""
    for fragment in fragments:
        lowered = fragment.casefold()
        marker = _marker_position(lowered, (" en arriendo/venta", " en arriendo"))
        if marker:
            return normalize_tipo(fragment[: marker[0]].strip())
    return ""


def _is_commercial_use(fragments: list[str], href: str) -> bool:
    """Reject explicit commercial-use markers from card text or URL."""
    card_text = " ".join(fragments).casefold()
    url_text = href.casefold().replace("-", " ").replace("_", " ")
    haystack = f"{card_text} {url_text}"
    return any(marker in haystack for marker in _COMMERCIAL_USE_MARKERS)


def _extract_barrio(fragments: list[str]) -> str:
    """Extract the neighborhood from a location fragment containing Medellin."""
    for fragment in fragments:
        lowered = fragment.casefold()
        if "," not in fragment or "medell" not in lowered:
            continue
        marker = _marker_position(lowered, (" en arriendo/venta", " en arriendo"))
        location = fragment[marker[0] + len(marker[1]) :] if marker else fragment
        location = location.strip(" :")
        if location.casefold().startswith("en "):
            location = location[3:]
        return location.split(",", 1)[0].strip()
    return ""


def _extract_parking(text: str) -> int:
    """Map the card's binary parking label to the numeric contract."""
    match = _marker_position(text, ("parqueadero", "parqueaderos"))
    if not match:
        return 0
    tail = text[match[0] + len(match[1]) :].casefold()
    for value in ("sí", "si", "no"):
        position = tail.find(value)
        if 0 <= position < 20:
            return normalize_garaje(value)
    return 0


def _property_id(href: str, fragments: list[str]) -> str:
    """Build the stable TB identifier from visible code or numeric URL suffix."""
    for fragment in fragments:
        for token in fragment.replace(":", " ").split():
            clean = token.strip(".,;").upper()
            if clean.startswith("TB-") and clean[3:].isdigit():
                return clean
    suffix = href.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return f"TB-{suffix}" if suffix.isdigit() else ""


def _absolute_url(href: str) -> str:
    """Convert a property href into the required absolute permalink."""
    if href.startswith(("http://", "https://")):
        return href
    return f"{BASE_URL}/{href.lstrip('/')}" if href else ""


def _parse_card(card: Tag) -> Listing | None:
    """Parse one generic property anchor into the 11-column contract."""
    href = str(card.get("href", "")).strip()
    fragments = _fragments(card)
    if _is_commercial_use(fragments, href):
        return None
    listing = _empty_listing()
    listing["id"] = _property_id(href, fragments)
    if not listing["id"]:
        return None

    text = " ".join(fragments)
    listing["url"] = _absolute_url(href)
    listing["tipo"] = _extract_tipo(fragments)
    listing["precio"] = _extract_price(text)
    listing["area"] = _extract_area(text)
    listing["habitaciones"] = _number_after(
        text, ("habitaciones", "habitación", "alcobas", "alcoba")
    )
    listing["banos"] = _number_after(text, ("baños", "baño", "banos", "bano"))
    listing["parqueaderos"] = _extract_parking(text)
    listing["estrato"] = _number_after(text, ("estrato",))
    listing["barrio"] = _extract_barrio(fragments)

    if listing["tipo"] in _ZERO_BEDROOM_TYPES and not listing["habitaciones"]:
        listing["habitaciones"] = 0
    return listing


def deduplicate_listings(rows: Iterable[Listing]) -> list[Listing]:
    """Keep the first row for each stable property ID."""
    seen: set[str] = set()
    unique: list[Listing] = []
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        unique.append(row)
    return unique


def filter_residential_listings(rows: Iterable[Listing]) -> list[Listing]:
    """Keep only the normalized residential contract types."""
    return [row for row in rows if row["tipo"] in RESIDENTIAL_TYPES]


def parse_search_page(html: str) -> list[Listing]:
    """Extract property anchors from one rendered numbered search page."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Listing] = []
    for element in soup.find_all("a", href=True):
        href = str(element.get("href", ""))
        if "/property/" not in href:
            continue
        listing = _parse_card(element)
        if listing:
            rows.append(listing)
    return deduplicate_listings(rows)


def _source_urls(sample_only: bool, max_pages: int | None) -> tuple[str, ...]:
    """Build residential-prefilter sources plus the bounded city pages."""
    page_limit = 1 if sample_only and max_pages is None else len(CANONICAL_PAGE_URLS)
    if max_pages is not None:
        page_limit = min(page_limit, max(0, max_pages))
    return (*RESIDENTIAL_TYPE_URLS, *CANONICAL_PAGE_URLS[:page_limit])


def scrape(
    ciudad: str = "medellin",
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> list[Listing]:
    """Scrape Total Bienes' finite numbered Medellin rental inventory."""
    if ciudad.casefold() not in {"medellin", "medellín"}:
        logger.warning(
            "Total Bienes canonical inventory is Medellin only, not %s", ciudad
        )
        return []

    rows: list[Listing] = []
    for source_number, url in enumerate(_source_urls(sample_only, max_pages), start=1):
        html = fetch_page(url)
        if not html:
            logger.warning("Failed to fetch Total Bienes source %d", source_number)
            continue
        page_rows = filter_residential_listings(parse_search_page(html))
        rows.extend(page_rows)
        if verbose:
            logger.info(
                "Total Bienes source %d: %d residential cards",
                source_number,
                len(page_rows),
            )

    rows = deduplicate_listings(rows)
    for row in rows:
        warnings = validate(dict(row))
        if verbose:
            for warning in warnings:
                print(f"  [ANOMALY] {row['id']} — {warning}")

    return rows
