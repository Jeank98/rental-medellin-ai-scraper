"""Lonja Inmobiliaria del Sur two-phase rental scraper.

Discovery is one server-rendered, paginated route that combines the three
residential source classes for every requested municipality.  Detail pages are
static HTML tables, so the portal needs no browser and no API.

The route grammar is the portal's own filter syntax, where the accented
municipality names must be sent percent-encoded and multi-word names are joined
with a hyphen (``Itagüí``, ``La-Estrella``, ``Medellín``).  Class and
municipality filters are combined with ``_`` after the ``clases_`` and
``municipios_`` prefixes.
"""

from __future__ import annotations

import logging
import re
from typing import TypedDict
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from scrape.cities import CITY_LABELS, normalize_city, resolve_city
from scrape.fetcher import bulk_fetch, fetch_page
from scrape.normalize import (
    normalize_barrio,
    normalize_estrato,
    normalize_garaje,
    normalize_price,
)
from scrape.validator import validate

logger = logging.getLogger(__name__)

BASE_URL = "https://www.lonjainmobiliariadelsur.com"
PORTAL = "lonjainmobiliariadelsur"
PREFIX = "LJS"
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

#: Source classes accepted by the contract; ``Casa-Finca`` and ``Casa-Local``
#: are different products and must never be collapsed into ``casa``.
RESIDENTIAL_TYPES = frozenset(("apartamento", "casa", "apartaestudio"))
SOURCE_CLASSES = ("Apartamento", "Apartaestudio", "Casa")
_SOURCE_TYPES = {
    "APARTAMENTO": "apartamento",
    "CASA": "casa",
    "APARTAESTUDIO": "apartaestudio",
}

#: The published combined route lists municipalities in this order.
SOURCE_CITY_ORDER = ("itagui", "envigado", "la-estrella", "sabaneta", "medellin")

CARD_SELECTOR = ".property_item"
CARDS_PER_PAGE = 16
SAMPLE_DETAILS_PER_CITY = 3
_SAMPLE_MULTI_CITY_PAGES = 3
_MAX_DISCOVERY_PAGES = 200
_MAX_DB_PRICE = 2_147_483_647

_LEADING_DIGITS = re.compile(r"\d+")
#: The results page states its count as ``N Encontrados`` on every page.  The
#: leading boundary keeps ``0 encontrados`` from matching inside ``40
#: encontrados``.
_TOTAL_PATTERN = re.compile(r"\b(\d+)\s+encontrados?\b", re.IGNORECASE)
_EMPTY_PATTERNS = (
    re.compile(r"\b0\s+encontrados?\b", re.IGNORECASE),
    re.compile(r"\bno\s+se\s+encontr", re.IGNORECASE),
    re.compile(r"\bsin\s+resultados\b", re.IGNORECASE),
    re.compile(
        r"\bno\s+hay\s+(?:resultados|inmuebles|propiedades|avisos?)\b", re.IGNORECASE
    ),
)
_CHALLENGE_MARKERS = (
    "just a moment",
    "cf-challenge",
    "cf_chl",
    "challenge-platform",
    "attention required",
    "access denied",
    "verify you are human",
    "checking your browser",
    "unusual traffic",
)


class LonjaError(RuntimeError):
    """Base class for failures that must abort a Lonja crawl."""


class LonjaFetchError(LonjaError):
    """The portal returned no response for a required page."""


class LonjaChallengeError(LonjaError):
    """An anti-bot interstitial replaced the listing content."""


class LonjaIntegrityError(LonjaError):
    """A page contradicts the expected listing identity or structure."""


class LonjaIncompleteError(LonjaError):
    """Pagination stopped before the portal's declared result count."""


Listing = TypedDict(
    "Listing",
    {
        "id": str,
        "portal": str,
        "tipo": str,
        "precio": int,
        "area": int,
        "habitaciones": int,
        "banos": int,
        "parqueaderos": int,
        "estrato": int,
        "barrio": str,
        "url": str,
    },
)
DetailFields = TypedDict(
    "DetailFields",
    {
        "codigo": str,
        "municipio": str,
        "operacion": str,
        "barrio": str,
        "estrato": int,
        "precio": int,
        "area": int,
        "habitaciones": int,
        "banos": int,
        "parqueaderos": int,
    },
)


def _fold(value: str) -> str:
    """Fold Spanish accents for label comparisons without pattern matching."""
    return value.upper().translate(str.maketrans("ÁÉÍÓÚÜÑ", "AEIOUUN"))


def _number(value: str) -> int:
    """Return the first contiguous decimal number in visible text."""
    digits = ""
    started = False
    for character in value:
        if character.isdecimal():
            digits += character
            started = True
        elif started:
            break
    return int(digits) if digits else 0


def _value_after_label(value: str, labels: tuple[str, ...]) -> str:
    folded = _fold(value)
    for raw_label in labels:
        label = _fold(raw_label)
        position = folded.find(label)
        if position >= 0:
            return value[position + len(raw_label) :].lstrip(" :")
    return ""


def _number_after_label(value: str, labels: tuple[str, ...]) -> int:
    return _number(_value_after_label(value, labels))


def _rental_price(raw: str) -> int:
    """Read the rental side of a combined rent/sale price.

    Listings offered for both operations print the monthly rent first
    (``$1,500,000 - $260,000,000``); the sale value must never reach the
    rental snapshot.
    """
    value = str(raw or "").strip()
    if " - " in value:
        value = value.split(" - ", 1)[0].strip()
    price = normalize_price(value)
    if price > _MAX_DB_PRICE:
        raise LonjaIntegrityError(f"price out of database range: {raw!r}")
    return price


def _extract_type(raw: str) -> str:
    """Map a card's source class, rejecting non-residential products."""
    head = raw.split(" - ", 1)[0].strip(" .,:;")
    return _SOURCE_TYPES.get(_fold(head), "")


def _operation_from_slug(slug: str) -> str:
    """Read the source operation stated by a detail slug.

    The portal spells the operation as hyphen-delimited slug tokens:
    ``arriendo`` for rental-only, ``venta`` for sale-only and
    ``arriendo-o-venta`` for a combined listing.  ``''`` means the slug carries
    no operation evidence, never that the listing is for rent.
    """
    tokens = set(unquote(slug).casefold().split("-"))
    rental = "arriendo" in tokens
    sale = "venta" in tokens
    if rental and sale:
        return "ambos"
    if rental:
        return "arriendo"
    if sale:
        return "venta"
    return ""


def _operation_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return _operation_from_slug(path.rsplit("/", 1)[-1]) if path else ""


def _detail_operation(heading: str) -> str:
    """Read the operation stated by a detail heading.

    The detail page titles rental listings ``... para Arriendo, Código N``,
    combined listings ``... para Arriendo o Venta, Código N`` and sale-only
    listings ``... para Venta, Código N``.
    """
    folded = _fold(heading)
    rental = "ARRIENDO" in folded
    sale = "VENTA" in folded
    if rental and sale:
        return "ambos"
    if rental:
        return "arriendo"
    if sale:
        return "venta"
    return ""


def _code_from_slug(slug: str) -> str:
    """Return the leading numeric source code of a detail slug."""
    match = _LEADING_DIGITS.match(slug)
    return match.group(0) if match else ""


def _detail_url(raw: str) -> str:
    """Return the canonical same-host detail URL, or ``''``."""
    absolute = urljoin(BASE_URL, raw.strip())
    parsed = urlparse(absolute)
    if parsed.netloc != urlparse(BASE_URL).netloc:
        return ""
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not _code_from_slug(slug):
        return ""
    return urlunparse(parsed._replace(query="", fragment=""))


def _code_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return _code_from_slug(path.rsplit("/", 1)[-1]) if path else ""


def _empty_listing() -> Listing:
    row: Listing = {column: "" for column in COLUMNS}  # type: ignore[typeddict-item]
    row["portal"] = PORTAL
    for field in ("precio", "area", "habitaciones", "banos", "parqueaderos", "estrato"):
        row[field] = 0
    return row


def _card_type(card: Tag) -> str:
    heading = card.find("h3")
    if heading is None:
        return ""
    return _extract_type(heading.get_text(" ", strip=True))


def _card_metrics(card: Tag) -> dict[str, int]:
    metrics = {"area": 0, "habitaciones": 0, "banos": 0}
    meta = card.select_one(".property_meta")
    if meta is None:
        return metrics
    for span in meta.find_all("span"):
        value = span.get_text(" ", strip=True)
        folded = _fold(value)
        compact = "".join(folded.split())
        if "M2" in compact or "METRO" in folded:
            metrics["area"] = _number(value)
        elif "ALCOBA" in folded or "HABIT" in folded:
            metrics["habitaciones"] = _number(value)
        elif "BANO" in folded:
            metrics["banos"] = _number(value)
    return metrics


def _parse_card(card: Tag, url: str) -> Listing | None:
    tipo = _card_type(card)
    if tipo not in RESIDENTIAL_TYPES:
        return None
    if _operation_from_url(url) == "venta":
        return None
    metrics = _card_metrics(card)
    price_node = card.select_one(".favroute2 p")
    row = _empty_listing()
    row.update(
        {
            "id": f"{PREFIX}-{_code_from_url(url)}",
            "tipo": tipo,
            "precio": _rental_price(
                price_node.get_text(" ", strip=True) if price_node else ""
            ),
            "area": metrics["area"],
            "habitaciones": metrics["habitaciones"],
            "banos": metrics["banos"],
            "url": url,
        }
    )
    return row


def _card_city_hint(card: Tag) -> str:
    """Return the card's municipality hint, if its location names one.

    Card location text is not authoritative: it is used only to schedule a
    bounded detail sample, while the detail table's ``Municipio`` decides the
    published city.
    """
    node = card.select_one(".proerty_text h4")
    if node is None:
        return ""
    tail = node.get_text(" ", strip=True).rsplit(",", 1)[-1]
    try:
        return resolve_city(tail)
    except ValueError:
        return ""


def _page_cards(
    soup: BeautifulSoup,
) -> tuple[list[str], list[Listing], dict[str, str]]:
    """Parse one results page into raw pagination codes, rows and city hints.

    Raw source codes are collected before type/operation acceptance, so page
    size, repeat detection and progress never depend on how many cards this
    portal accepts.  ``hints`` maps each card URL to its location municipality
    hint (``''`` when the location names no supported city).
    """
    codes: list[str] = []
    seen: set[str] = set()
    rows: list[Listing] = []
    hints: dict[str, str] = {}
    for card in soup.select(CARD_SELECTOR):
        url = ""
        for anchor in card.find_all("a", href=True):
            candidate = _detail_url(str(anchor.get("href", "")))
            if candidate:
                url = candidate
                break
        code = _code_from_url(url)
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
        hints[url] = _card_city_hint(card)
        row = _parse_card(card, url)
        if row is not None:
            rows.append(row)
    return codes, rows, hints


def _parse_cards(soup: BeautifulSoup) -> list[Listing]:
    return _page_cards(soup)[1]


def parse_search_page(html: str) -> list[Listing]:
    """Parse one results page, rejecting out-of-scope source records."""
    return _parse_cards(BeautifulSoup(html or "", "html.parser"))


def _result_total(soup: BeautifulSoup) -> int | None:
    """Return the result count the page declares as ``N Encontrados``."""
    match = _TOTAL_PATTERN.search(soup.get_text(" ", strip=True))
    return int(match.group(1)) if match else None


def parse_result_total(html: str) -> int | None:
    """Return the declared result count of a results page, if present."""
    return _result_total(BeautifulSoup(html or "", "html.parser"))


def _detail_rows(soup: BeautifulSoup) -> dict[str, str]:
    rows: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
        if len(cells) >= 2:
            rows[_fold(cells[0].rstrip(" :"))] = cells[1]
    return rows


def _detail_blocks(soup: BeautifulSoup) -> list[str]:
    return [item.get_text(" ", strip=True) for item in soup.select("ul.bloques li")]


_PARKING_LABELS = ("PARQUEADERO", "PARQUEADEROS", "GARAJE", "GARAJES")
_NON_PRIVATE_PARKING = ("VISITANTE", "VISITANTES", "COMUNAL")


def _structured_parking(blocks: list[str]) -> int:
    """Return private parking only when a block is labelled as such.

    Blocks that describe visitor or shared-building parking are a different
    amenity; prose mentions are never turned into a private parking count.
    """
    for block in blocks:
        folded = _fold(block)
        if not folded.startswith(_PARKING_LABELS):
            continue
        if any(marker in folded for marker in _NON_PRIVATE_PARKING):
            continue
        value = _value_after_label(block, _PARKING_LABELS)
        number = _number(value)
        return number if number else normalize_garaje(value)
    return 0


def parse_detail_page(html: str) -> DetailFields:
    """Parse the structured detail table; narrative amenities are ignored."""
    soup = BeautifulSoup(html or "", "html.parser")
    rows = _detail_rows(soup)
    blocks = _detail_blocks(soup)
    heading = soup.find("h1")
    return {
        "codigo": rows.get("CODIGO", "").strip(),
        "municipio": rows.get("MUNICIPIO", "").strip(),
        "operacion": _detail_operation(
            heading.get_text(" ", strip=True) if heading else ""
        ),
        "barrio": normalize_barrio(rows.get("BARRIO", "")),
        "estrato": normalize_estrato(rows.get("ESTRATO", "")),
        "precio": _rental_price(rows.get("PRECIO", "")),
        "area": _number(rows.get("AREA", "")),
        "habitaciones": _number_after_label(
            " ".join(blocks), ("ALCOBA", "ALCOBAS", "HABITACION", "HABITACIONES")
        ),
        "banos": _number_after_label(" ".join(blocks), ("BANO", "BANOS")),
        "parqueaderos": _structured_parking(blocks),
    }


def merge_detail(row: Listing, detail: DetailFields) -> str:
    """Merge verified detail fields and return the canonical source city.

    The detail's ``Código``, ``Municipio`` and heading operation are the
    identity guards: a detail that does not describe this Lonja card aborts the
    crawl instead of silently publishing another listing's data or a sale's
    price into a rental snapshot.

    Raises:
        LonjaIntegrityError: on a foreign identity, a code mismatch, a missing
            municipality, or a detail that states no operation.
    """
    expected_code = _code_from_url(row["url"])
    if (
        not expected_code
        or row["portal"] != PORTAL
        or str(row["id"]) != f"{PREFIX}-{expected_code}"
    ):
        raise LonjaIntegrityError(f"{row['id']!r} is not a Lonja source identity")
    if not detail["codigo"] or detail["codigo"] != expected_code:
        raise LonjaIntegrityError(
            f"detail code {detail['codigo']!r} does not match {row['id']}"
        )
    if not detail["municipio"]:
        raise LonjaIntegrityError(f"detail for {row['id']} has no municipality")
    if not detail["operacion"]:
        raise LonjaIntegrityError(f"detail for {row['id']} states no operation")

    for field in ("precio", "area", "habitaciones", "banos"):
        if not row[field] and detail[field]:
            row[field] = detail[field]
    if detail["estrato"]:
        row["estrato"] = detail["estrato"]
    if detail["barrio"]:
        row["barrio"] = detail["barrio"]
    row["parqueaderos"] = detail["parqueaderos"]
    return normalize_city(detail["municipio"])


def build_search_url(ciudades, page: int = 1) -> str:
    """Build the combined rental route for the requested municipalities."""
    cities = _canonical_cities(ciudades)
    if page < 1:
        raise ValueError(f"page must be at least 1, got {page}")
    ordered = [city for city in SOURCE_CITY_ORDER if city in cities]
    missing = [city for city in cities if city not in ordered]
    if missing:
        raise LonjaIntegrityError(f"no source municipality token for {missing}")
    municipalities = "_".join(
        quote(CITY_LABELS[city].replace(" ", "-"), safe="-") for city in ordered
    )
    classes = "_".join(SOURCE_CLASSES)
    base = f"{BASE_URL}/inmuebles/Arriendo/clases_{classes}/municipios_{municipalities}"
    return base if page == 1 else f"{base}/{page}"


def _canonical_cities(ciudades) -> list[str]:
    if isinstance(ciudades, str):
        raise TypeError("ciudades must be an iterable of city names, not a string")
    requested: list[str] = []
    for raw in ciudades:
        city = resolve_city(raw)
        if city not in requested:
            requested.append(city)
    if not requested:
        raise ValueError("at least one city is required")
    return requested


def _looks_challenged(html: str) -> bool:
    head = html[:20000].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def _is_legit_empty(soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ", strip=True)
    return any(pattern.search(text) for pattern in _EMPTY_PATTERNS)


def _discover(
    cities: list[str],
    max_pages: int | None,
    sample_only: bool,
    verbose: bool,
) -> tuple[list[Listing], dict[str, str]]:
    """Walk the shared listing stream once and deduplicate source codes.

    Pagination is measured on the raw source codes every card carries, not on
    the accepted rows, so rejected classes never shorten a page or look like
    progress.  The declared ``N Encontrados`` count is read on every page and
    must stay consistent; a partial snapshot that stops short of it raises.

    Returns:
        The accepted listings and the card municipality hints keyed by URL.
    """
    if sample_only and max_pages is None:
        max_pages = 1 if len(cities) == 1 else _SAMPLE_MULTI_CITY_PAGES

    base_url = build_search_url(cities)
    by_id: dict[str, Listing] = {}
    hints: dict[str, str] = {}
    raw_codes: set[str] = set()
    declared_total: int | None = None
    page = 1
    stopped_by_cap = False
    while True:
        url = base_url if page == 1 else f"{base_url}/{page}"
        html = fetch_page(url)
        if not html:
            raise LonjaFetchError(f"no response for {url}")
        if _looks_challenged(html):
            raise LonjaChallengeError(f"anti-bot interstitial at {url}")

        soup = BeautifulSoup(html, "html.parser")
        card_count = len(soup.select(CARD_SELECTOR))
        raw_page, page_rows, page_hints = _page_cards(soup)
        if card_count and not raw_page:
            raise LonjaIntegrityError(
                f"{url} rendered {card_count} cards without a source code"
            )
        page_total = _result_total(soup)
        if not raw_page:
            if page == 1 and not by_id:
                if page_total == 0 or _is_legit_empty(soup):
                    break
                raise LonjaIntegrityError(
                    f"{url} rendered no listings and no explicit empty result"
                )
            if page_total is not None and page_total > 0:
                raise LonjaIncompleteError(
                    f"{url} declares {page_total} results but rendered no listings"
                )
            if page_total != 0 and not _is_legit_empty(soup):
                raise LonjaIntegrityError(
                    f"{url} rendered no listings and no explicit empty result"
                )
            break
        if page_total == 0:
            raise LonjaIntegrityError(
                f"{url} declares 0 results but rendered {len(raw_page)} cards"
            )
        if page_total is not None:
            if declared_total is None:
                declared_total = page_total
            elif page_total != declared_total:
                raise LonjaIntegrityError(
                    f"{url} declares {page_total} results but {declared_total} "
                    "were declared on an earlier page"
                )

        new_codes = set(raw_page) - raw_codes
        if not new_codes:
            raise LonjaIntegrityError(f"{url} repeated an earlier page of listings")
        raw_codes.update(new_codes)
        for row in page_rows:
            by_id.setdefault(str(row["id"]), row)
        for hint_url, hint in page_hints.items():
            hints.setdefault(hint_url, hint)
        if verbose:
            logger.info(
                "Lonja page %d: %d cards, %d accepted, %d unique raw",
                page,
                len(raw_page),
                len(page_rows),
                len(raw_codes),
            )

        if max_pages is not None and page >= max_pages:
            stopped_by_cap = True
            break
        if declared_total is not None and len(raw_codes) >= declared_total:
            break
        if declared_total is None and len(raw_page) < CARDS_PER_PAGE:
            break
        page += 1
        if page > _MAX_DISCOVERY_PAGES:
            raise LonjaIntegrityError(
                f"pagination exceeded {_MAX_DISCOVERY_PAGES} pages"
            )

    if (
        declared_total is not None
        and not stopped_by_cap
        and len(raw_codes) < declared_total
    ):
        raise LonjaIncompleteError(
            f"portal declared {declared_total} listings but pagination stopped at "
            f"{len(raw_codes)}"
        )
    return list(by_id.values()), hints


def _sample_plan(
    rows: list[Listing],
    hints: dict[str, str],
    cities: list[str],
) -> list[Listing]:
    """Schedule at most three sampled details per requested city.

    Card location is a hint only, so slots a city cannot fill from hinted cards
    are filled from cards whose location names no supported municipality.  The
    total schedule never exceeds three requests per requested city and is fixed
    before any detail is fetched.
    """
    hinted: dict[str, list[Listing]] = {city: [] for city in cities}
    unknown: list[Listing] = []
    for row in rows:
        hint = hints.get(str(row["url"]), "")
        if hint in hinted:
            hinted[hint].append(row)
        else:
            unknown.append(row)

    plan: list[Listing] = []
    spare = 0
    for city in cities:
        chosen = hinted[city][:SAMPLE_DETAILS_PER_CITY]
        spare += SAMPLE_DETAILS_PER_CITY - len(chosen)
        plan.extend(chosen)
    if spare:
        plan.extend(unknown[:spare])
    return plan


def _fetch_details(rows: list[Listing]) -> dict[str, DetailFields]:
    """Fetch and parse the scheduled details; failures abort the crawl."""
    urls = [str(row["url"]) for row in rows]
    responses = dict(bulk_fetch(urls))
    details: dict[str, DetailFields] = {}
    for url in urls:
        if url in details:
            continue
        html = responses.get(url, "")
        if not html:
            raise LonjaFetchError(f"no detail response for {url}")
        if _looks_challenged(html):
            raise LonjaChallengeError(f"anti-bot interstitial at {url}")
        details[url] = parse_detail_page(html)
    return details


def _scrape(
    cities: list[str],
    sample_only: bool,
    max_pages: int | None,
    verbose: bool,
) -> dict[str, list[Listing]]:
    grouped: dict[str, list[Listing]] = {city: [] for city in cities}
    listings, hints = _discover(cities, max_pages, sample_only, verbose)
    scheduled = _sample_plan(listings, hints, cities) if sample_only else listings
    if scheduled:
        details = _fetch_details(scheduled)
        for row in scheduled:
            detail = details[str(row["url"])]
            if detail["operacion"] == "venta":
                logger.warning("Skipping %s: source operation is sale-only", row["id"])
                continue
            source_city = merge_detail(row, detail)
            if source_city not in grouped:
                logger.warning(
                    "Skipping %s: municipality %r is outside the requested cities",
                    row["id"],
                    detail["municipio"],
                )
                continue
            grouped[source_city].append(row)

    if sample_only:
        for city in grouped:
            grouped[city] = grouped[city][:SAMPLE_DETAILS_PER_CITY]

    for rows in grouped.values():
        for row in rows:
            warnings = validate(row)
            if verbose:
                for warning in warnings:
                    logger.warning("%s: %s", row["id"], warning)
    return grouped


def scrape_cities(
    ciudades,
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> dict[str, list[Listing]]:
    """Scrape the requested cities in one shared discovery stream."""
    requested = _canonical_cities(ciudades)
    if max_pages is not None and max_pages < 1:
        raise ValueError(f"max_pages must be at least 1, got {max_pages}")
    return _scrape(requested, sample_only, max_pages, verbose)


def scrape(
    ciudad: str = "medellin",
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> list[Listing]:
    """Scrape one canonical city through the shared two-phase engine."""
    city = resolve_city(ciudad)
    return scrape_cities(
        [city],
        sample_only=sample_only,
        max_pages=max_pages,
        verbose=verbose,
    )[city]
