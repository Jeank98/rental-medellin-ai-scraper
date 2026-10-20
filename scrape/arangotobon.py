"""Arango Tobon Inmobiliaria two-phase Medellin rental scraper.

The portal moved from server-rendered ASP.NET routes to a WordPress theme, so
the search inventory now lives on ``/todas-las-propiedades/`` behind a GET form
(``destinacion``, ``municipio``, ``clase``, ``pag``). Cards carry identity,
type, price and area; the detail template exposes rooms, parking and estrato.
"""

from __future__ import annotations

import logging
from typing import TypedDict
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

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

BASE_URL = "https://arangotobon.com"
SEARCH_PATH = "/todas-las-propiedades/"
SEARCH_URL = f"{BASE_URL}{SEARCH_PATH}?destinacion=Arriendo&municipio=medellin"
PORTAL = "arangotobon"
PREFIX = "ATB"
CARDS_PER_PAGE = 12
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
RESIDENTIAL_TYPES = frozenset(("apartamento", "casa", "apartaestudio"))

_DETAIL_FIELDS = ("habitaciones", "banos", "parqueaderos", "estrato", "barrio")
_ICON_CLASS = "material-symbols-outlined"


class UnsupportedCityError(KeyError):
    """Raised when the scraper is asked for a city outside its confirmed route."""


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
        "tipo": str,
        "precio": int,
        "area": int,
        "habitaciones": int,
        "banos": int,
        "parqueaderos": int,
        "estrato": int,
        "barrio": str,
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


def _visible_text(node: Tag | BeautifulSoup) -> str:
    """Join a node's text while dropping Material Symbols icon labels."""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, Tag):
            classes = child.get("class") or []
            if _ICON_CLASS in classes:
                continue
            text = child.get_text(" ", strip=True)
        else:
            text = str(child).strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _normalize_rental_price(raw: str) -> int:
    """Normalize the rental canon; the offer suffix after ``/`` is ignored."""
    return normalize_price(str(raw).strip())


def _extract_type(raw: str) -> str:
    """Normalize portal type, treating the portal's loft class as a studio."""
    cleaned = raw.strip(" .,:;#")
    folded = _fold(cleaned)
    if "APTO-LOFT" in folded or "APTO LOFT" in folded:
        return "apartaestudio"
    first_word = cleaned.casefold().split(" ", 1)[0]
    return normalize_tipo(first_word)


def _detail_url(raw: str) -> str:
    absolute = urljoin(BASE_URL, raw.strip())
    parsed = urlparse(absolute)
    if parsed.netloc != urlparse(BASE_URL).netloc:
        return ""
    clean = parsed._replace(query="", fragment="")
    path_parts = clean.path.strip("/").split("/")
    if len(path_parts) != 2 or path_parts[0].casefold() != "inmueble":
        return ""
    if not path_parts[1].isdecimal():
        return ""
    return urlunparse(clean)


def _code_from_url(url: str) -> str:
    path_parts = urlparse(url).path.strip("/").split("/")
    if len(path_parts) != 2 or path_parts[0].casefold() != "inmueble":
        return ""
    return path_parts[1] if path_parts[1].isdecimal() else ""


def _empty_listing() -> Listing:
    row: Listing = {column: "" for column in COLUMNS}  # type: ignore[typeddict-item]
    row["portal"] = PORTAL
    for field in ("precio", "area", "habitaciones", "banos", "parqueaderos", "estrato"):
        row[field] = 0
    return row


def _card_url(card: Tag) -> str:
    """Resolve the card's detail URL from its onclick handler or CTA anchor."""
    onclick = str(card.get("onclick") or "")
    candidate = ""
    marker = "window.location.href="
    position = onclick.find(marker)
    if position >= 0:
        candidate = onclick[position + len(marker) :].strip().strip("'\"")
    if not candidate:
        anchor = card.select_one("a.at-dest2-card-btn[href]")
        if anchor is not None:
            candidate = str(anchor.get("href") or "")
    return _detail_url(candidate)


def _card_tags(card: Tag) -> list[str]:
    return [tag.get_text(" ", strip=True) for tag in card.select(".at-dest2-tag")]


def _card_type(card: Tag, tags: list[str]) -> str:
    """Read the portal class from the second tag, falling back to the heading."""
    if len(tags) >= 2:
        return _extract_type(tags[1])
    heading = card.select_one("h3.at-dest2-card-name")
    if heading is not None:
        raw = heading.get_text(" ", strip=True)
        for separator in ("—", " - "):
            if separator in raw:
                raw = raw.split(separator, 1)[0]
        return _extract_type(raw)
    return ""


def _card_field_text(card: Tag, selector: str) -> str:
    node = card.select_one(selector)
    return _visible_text(node) if node is not None else ""


def _parse_card(card: Tag, url: str) -> Listing | None:
    tags = _card_tags(card)
    if tags and _fold(tags[0]) not in ("ARRIENDO", ""):
        return None
    raw_type = _card_type(card, tags)
    if raw_type not in RESIDENTIAL_TYPES:
        return None
    row = _empty_listing()
    row.update(
        {
            "id": f"{PREFIX}-{_code_from_url(url)}",
            "tipo": raw_type,
            "precio": _normalize_rental_price(_card_field_text(card, ".at-dest2-price")),
            "area": _number(_card_field_text(card, ".at-dest2-area")),
            "barrio": normalize_barrio(_card_field_text(card, ".at-dest2-location")),
            "url": url,
        }
    )
    return row


def parse_search_page(html: str) -> list[Listing]:
    """Parse one server-rendered results page and deduplicate detail URLs."""
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[Listing] = []
    seen_urls: set[str] = set()
    for card in soup.select(".at-dest2-card"):
        url = _card_url(card)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        row = _parse_card(card, url)
        if row is not None:
            rows.append(row)
    return rows


def count_cards(html: str) -> int:
    """Count every result card, including non-residential classes."""
    soup = BeautifulSoup(html or "", "html.parser")
    return len(soup.select(".at-dest2-card"))


def parse_total_results(html: str) -> int:
    """Read the ``de <strong>N</strong> propiedades`` counter."""
    soup = BeautifulSoup(html or "", "html.parser")
    for paragraph in soup.select("p.at-ti2-count"):
        strongs = paragraph.find_all("strong")
        if not strongs:
            continue
        total = _number(strongs[-1].get_text(" ", strip=True))
        if total:
            return total
    return 0


def _detail_feature_fields(soup: BeautifulSoup) -> dict[str, int]:
    """Map detail feature pills to numeric fields by their visible label."""
    fields = {"area": 0, "habitaciones": 0, "banos": 0, "parqueaderos": 0, "estrato": 0}
    for pill in soup.select(".at-sd-feat"):
        label = _visible_text(pill)
        folded = _fold(label)
        compact = "".join(folded.split())
        value = _number(label)
        if ("ALCOBA" in folded or "HABITAC" in folded) and not fields["habitaciones"]:
            fields["habitaciones"] = value
        elif "BANO" in folded and not fields["banos"]:
            fields["banos"] = value
        elif ("PARQUEADERO" in folded or "GARAJE" in folded) and not fields["parqueaderos"]:
            fields["parqueaderos"] = value
        elif "ESTRATO" in folded and not fields["estrato"]:
            fields["estrato"] = normalize_estrato(str(value))
        elif ("M2" in compact or "M²" in folded or "METRO" in folded) and not fields["area"]:
            fields["area"] = value
    return fields


def parse_detail_page(html: str) -> DetailFields:
    """Parse the detail template's coded chip, price, place and feature pills."""
    soup = BeautifulSoup(html or "", "html.parser")
    code_chip = soup.select_one(".at-sd-cod-chip")
    heading = soup.find(["h1", "h2"])
    heading_text = heading.get_text(" ", strip=True) if heading else ""
    price_node = soup.select_one(".at-sd-price-val")
    location_node = soup.select_one(".at-sd-loc")
    location = _visible_text(location_node) if location_node is not None else ""
    if "," in location:
        location = location.split(",", 1)[0]
    fields = _detail_feature_fields(soup)
    return {
        "codigo": str(_number(code_chip.get_text(" ", strip=True))) if code_chip else "",
        "tipo": _extract_type(heading_text),
        "precio": normalize_price(price_node.get_text(" ", strip=True)) if price_node else 0,
        "area": fields["area"],
        "habitaciones": fields["habitaciones"],
        "banos": fields["banos"],
        "parqueaderos": fields["parqueaderos"],
        "estrato": fields["estrato"],
        "barrio": normalize_barrio(location),
    }


def merge_detail(row: Listing, detail: DetailFields) -> bool:
    """Merge only verified detail data while preserving card identity."""
    expected_code = _code_from_url(row["url"])
    if not detail["codigo"] or detail["codigo"] != expected_code:
        logger.warning("Ignoring detail code mismatch for %s", row["id"])
        return False
    if detail["area"] and not row["area"]:
        row["area"] = detail["area"]
    if detail["habitaciones"]:
        row["habitaciones"] = detail["habitaciones"]
    if detail["banos"]:
        row["banos"] = detail["banos"]
    if detail["parqueaderos"]:
        row["parqueaderos"] = detail["parqueaderos"]
    if detail["estrato"]:
        row["estrato"] = detail["estrato"]
    if detail["barrio"]:
        row["barrio"] = detail["barrio"]
    return True


def build_page_url(page: int, ciudad: str = "medellin") -> str:
    """Build the verified Medellín rental route; page one has no ``pag`` param."""
    if _fold(ciudad.strip()) != "MEDELLIN":
        raise UnsupportedCityError(f"Arango Tobón only supports Medellín: {ciudad}")
    return SEARCH_URL if page <= 1 else f"{SEARCH_URL}&pag={page}"


def _last_page(html: str) -> int | None:
    total = parse_total_results(html)
    if not total:
        return None
    return max(1, -(-total // CARDS_PER_PAGE))


def _plan_phase_b(
    rows: list[Listing],
    ciudad: str,
    reuse_unchanged_details: bool,
) -> DetailReusePlan:
    """Reuse Arango Tobón detail-only fields from an unchanged active snapshot."""
    if not reuse_unchanged_details:
        return full_detail_plan(rows)

    plan = plan_active_detail_reuse(rows, PORTAL, ciudad, _DETAIL_FIELDS)
    logger.info(
        "ATB detail reuse: %d reused, %d detail pages to fetch",
        plan.reused_count,
        plan.detail_fetch_count,
    )
    print(
        "ATB detail reuse: "
        f"{plan.reused_count} reused; {plan.detail_fetch_count} detail pages fetched"
    )
    return plan


def scrape(
    ciudad: str = "medellin",
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
    reuse_unchanged_details: bool = False,
) -> list[Listing]:
    """Scrape Arango Tobón's Medellín inventory through two HTML phases."""
    try:
        build_page_url(1, ciudad)
    except UnsupportedCityError as exc:
        logger.warning("%s", exc)
        return []

    page_limit = max_pages if max_pages is not None else (1 if sample_only else None)
    by_id: dict[str, Listing] = {}
    page = 1
    last_page: int | None = None
    while page_limit is None or page <= page_limit:
        html = fetch_page(build_page_url(page, ciudad))
        if not html:
            break
        if count_cards(html) == 0:
            break
        if last_page is None:
            last_page = _last_page(html)
        page_rows = parse_search_page(html)
        new_ids = {str(row["id"]) for row in page_rows} - set(by_id)
        if not new_ids:
            break
        for row in page_rows:
            by_id.setdefault(str(row["id"]), row)
        if verbose:
            logger.info(
                "Arango Tobón page %d: %d cards, %d unique",
                page,
                count_cards(html),
                len(by_id),
            )
        if last_page is not None and page >= last_page:
            break
        page += 1

    rows = list(by_id.values())
    if not rows:
        return []

    plan = _plan_phase_b(rows, ciudad, reuse_unchanged_details)
    details = dict(
        bulk_fetch([row["url"] for row in plan.detail_listings if row["url"]])
    )
    for row in plan.detail_listings:
        html = details.get(row["url"], "")
        if html:
            merge_detail(row, parse_detail_page(html))
        else:
            logger.warning("No detail response for %s; keeping card defaults", row["id"])
    for row in rows:
        warnings = validate(row)
        if verbose:
            for warning in warnings:
                logger.warning("%s: %s", row["id"], warning)
    return rows
