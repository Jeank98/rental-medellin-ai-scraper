"""Proser Inmobiliaria two-phase rental scraper.

Phase A reads the canonical Medellin rental search cards. Phase B fetches each
official detail page because estrato and the labeled neighborhood are absent
from cards. Parsing is based on semantic DOM text, not CSS selectors or regex.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TypeAlias
from urllib.parse import parse_qs, urlencode, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from scrape.fetcher import bulk_fetch, fetch_page
from scrape.normalize import normalize_barrio, normalize_price, normalize_tipo
from scrape.proserinmobiliaria_detail import merge_detail, parse_detail_page
from scrape.validator import validate

logger = logging.getLogger(__name__)

BASE_URL = "https://proserinmobiliaria.com"
PORTAL = "proserinmobiliaria"
PREFIX = "PRO"
COLUMNS = [
    "id", "portal", "tipo", "precio", "area", "habitaciones", "banos",
    "parqueaderos", "estrato", "barrio", "url",
]
Listing: TypeAlias = dict[str, str | int]

_PER_PAGE = 12
_SEARCH_PARAMS = (
    ("id_city", "496"),
    ("business_type[0]", "for_rent"),
    ("order_by", "created_at"),
    ("order", "desc"),
    ("for_sale", "0"),
    ("for_rent", "1"),
    ("for_temporary_rent", "0"),
    ("for_transfer", "0"),
    ("lax_business_type", "1"),
)
_TIPOS = {"apartamento", "casa", "apartaestudio", "local", "oficina", "bodega", "lote", "finca"}


def _page_url(page: int) -> str:
    params = list(_SEARCH_PARAMS)
    params.insert(4, ("page", str(page)))
    return f"{BASE_URL}/search?{urlencode(params)}"


def _empty_listing() -> Listing:
    row: Listing = {column: "" for column in COLUMNS}
    row["portal"] = PORTAL
    for column in ("precio", "area", "habitaciones", "banos", "parqueaderos", "estrato"):
        row[column] = 0
    return row


def _detail_url(raw: str) -> str:
    url = raw if raw.startswith("http") else f"{BASE_URL}/{raw.lstrip('/')}"
    parsed = urlparse(url)
    code = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if parsed.netloc != urlparse(BASE_URL).netloc or not code.isdecimal():
        return ""
    return url


def _code_from_url(url: str) -> str:
    code = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return code if code.isdecimal() else ""


def _lines(node: Tag) -> list[str]:
    return [line.strip() for line in node.get_text("\n", strip=True).splitlines() if line.strip()]


def _number_fragment(raw: str) -> str:
    fragment: list[str] = []
    started = False
    for char in raw.replace(",", ""):
        if char.isdecimal() or (char == "." and started):
            fragment.append(char)
            started = True
        elif started:
            break
    return "".join(fragment)


def _contract_number(raw: str, field: str) -> int:
    fragment = _number_fragment(raw)
    if not fragment:
        return 0
    if fragment.count(".") > 1:
        fragment = fragment.replace(".", "")
    try:
        value = Decimal(fragment)
    except InvalidOperation:
        return 0
    rounded = value.to_integral_value(rounding=ROUND_HALF_UP)
    if value != rounded:
        logger.warning(
            "Proser %s=%s is fractional; normalized with ROUND_HALF_UP to %s",
            field, fragment, rounded,
        )
    return int(rounded)


def _value_before_label(lines: list[str], labels: tuple[str, ...], field: str) -> int:
    for index, line in enumerate(lines):
        lowered = line.casefold()
        for label in labels:
            position = lowered.find(label)
            if position < 0:
                continue
            inline = _number_fragment(line[:position])
            if inline:
                return _contract_number(inline, field)
            normalized_line = line.casefold().strip(" :")
            if (normalized_line == label or normalized_line.startswith(f"{label} ")) and index > 0:
                return _contract_number(lines[index - 1], field)
    return 0


def _price_after_rent_label(lines: list[str]) -> int:
    """Select the amount labeled Alquiler, never the sale amount."""
    for index, line in enumerate(lines):
        if line.casefold().strip(" :") != "alquiler":
            continue
        for candidate in lines[index + 1:index + 4]:
            if "$" not in candidate:
                continue
            price = normalize_price(candidate)
            if price:
                return price
    return 0


def _tipo(lines: list[str]) -> str:
    """Find the first recognized property type in a card's text."""
    for line in lines:
        raw = line.strip(" .,:")
        normalized = normalize_tipo(raw)
        if normalized in _TIPOS:
            return normalized
        first_word = raw.casefold().split(" ", 1)[0]
        normalized = normalize_tipo(first_word)
        if normalized in _TIPOS:
            return normalized
    return ""


def _title(card: Tag, lines: list[str]) -> str:
    """Read the card heading, falling back to the first arriendo line."""
    for heading in card.find_all(("h1", "h2", "h3", "h4")):
        text = heading.get_text(" ", strip=True)
        if text:
            return text
    for line in lines:
        if "arriendo" in line.casefold() or "alquiler" in line.casefold():
            return line
    return ""


def _infer_barrio(title: str) -> str:
    """Infer a card neighborhood from the title until detail data is merged."""
    lowered = title.casefold()
    marker = "arriendo" if "arriendo" in lowered else "alquiler"
    if marker not in lowered:
        return ""
    value = title[lowered.find(marker) + len(marker):].split(",", 1)[0].strip(" .")
    for suffix in (" medellín", " medellin", " antioquia"):
        if value.casefold().endswith(suffix):
            value = value[:-len(suffix)].strip(" .")
    return normalize_barrio(value)


def _card_for_link(link: Tag) -> Tag | None:
    """Find the smallest semantic card ancestor containing its rental offer."""
    candidate: Tag | None = None
    parent = link.parent
    while isinstance(parent, Tag):
        if parent.name == "div":
            lines = _lines(parent)
            text = " ".join(lines).casefold()
            has_metric = sum(label in text for label in ("alcoba", "garaje", "baño", "área")) >= 2
            if has_metric:
                candidate = parent
                if "alquiler" in text and "$" in text:
                    return parent
        parent = parent.parent
    return candidate


def _is_marketplace(card: Tag) -> bool:
    """Reject cards explicitly labeled MARKETPLACE because provenance is not first-party."""
    return any(line.casefold().strip() == "marketplace" for line in _lines(card))


def _parse_card(card: Tag, url: str) -> Listing:
    """Parse one accepted search card into the complete contract shape."""
    lines = _lines(card)
    row = _empty_listing()
    row["id"] = f"{PREFIX}-{_code_from_url(url)}"
    row["tipo"] = _tipo(lines)
    row["precio"] = _price_after_rent_label(lines)
    row["area"] = _value_before_label(lines, ("área", "area"), "area")
    row["habitaciones"] = _value_before_label(lines, ("alcoba", "alcobas"), "habitaciones")
    row["banos"] = _value_before_label(lines, ("baño", "baños"), "banos")
    row["parqueaderos"] = _value_before_label(lines, ("garaje", "garajes"), "parqueaderos")
    row["barrio"] = _infer_barrio(_title(card, lines))
    row["url"] = url
    return row


def _page_numbers(soup: BeautifulSoup) -> set[int]:
    """Read numeric page query values from pagination links."""
    pages: set[int] = set()
    for link in soup.find_all("a", href=True):
        for value in parse_qs(urlparse(str(link.get("href"))).query).get("page", []):
            if value.isdecimal():
                pages.add(int(value))
    return pages


def _parse_search_page(html: str) -> tuple[list[Listing], set[int], int]:
    """Parse accepted cards, pagination values, and raw card count."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Listing] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        url = _detail_url(str(link.get("href")))
        if not url or url in seen:
            continue
        card = _card_for_link(link)
        if card is None:
            continue
        seen.add(url)
        if _is_marketplace(card):
            logger.warning("Skipping marketplace listing %s", url)
            continue
        rows.append(_parse_card(card, url))
    return rows, _page_numbers(soup), len(seen)


def parse_search_page(html: str) -> tuple[list[Listing], set[int]]:
    rows, pages, _ = _parse_search_page(html)
    return rows, pages


def scrape(ciudad: str = "medellin", sample_only: bool = False, max_pages: int | None = None, verbose: bool = False) -> list[Listing]:
    """Scrape Medellin rental listings with card parsing followed by details."""
    if ciudad.casefold().replace("í", "i") != "medellin":
        logger.warning("Proser mapping is scoped to Medellín; got ciudad=%s", ciudad)
        return []
    page_limit = max_pages if max_pages is not None else (1 if sample_only else None)
    listings: list[Listing] = []
    seen: set[str] = set()
    page = 1
    while page_limit is None or page <= page_limit:
        html = fetch_page(_page_url(page))
        if not html:
            break
        page_rows, _, raw_count = _parse_search_page(html)
        for row in page_rows:
            if row["id"] not in seen:
                listings.append(row)
                seen.add(str(row["id"]))
        if verbose:
            logger.info("Proser page %d: %d accepted cards", page, len(page_rows))
        if raw_count < _PER_PAGE:
            break
        page += 1
    if not listings:
        return []

    detail_map = dict(bulk_fetch([str(row["url"]) for row in listings]))
    complete: list[Listing] = []
    for row in listings:
        url = str(row["url"])
        html = detail_map.get(url, "")
        if not html:
            logger.warning("Dropping %s; detail fields were not fetched", row["id"])
            continue
        if not merge_detail(row, parse_detail_page(html, url)):
            continue
        warnings = validate(row)
        if verbose:
            for warning in warnings:
                logger.warning("%s: %s", row["id"], warning)
        complete.append(row)
    if sample_only:
        print(f"Sample: {len(complete)} listing(s) extracted")
    return complete
