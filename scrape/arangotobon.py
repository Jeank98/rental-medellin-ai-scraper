"""Arango Tobon Inmobiliaria two-phase Medellin rental scraper."""

from __future__ import annotations

import logging
from typing import TypedDict
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from scrape.fetcher import bulk_fetch, fetch_page
from scrape.normalize import (
    normalize_barrio,
    normalize_estrato,
    normalize_garaje,
    normalize_price,
    normalize_tipo,
)
from scrape.validator import validate

logger = logging.getLogger(__name__)

BASE_URL = "https://www.arangotobon.com"
SEARCH_URL = (
    f"{BASE_URL}/inmuebles/Arriendo/"
    "clases_Apartamento_Apto-Loft_Apartaestudio_Casa/"
    "municipios_Medell%C3%ADn/"
)
PORTAL = "arangotobon"
PREFIX = "ATB"
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


def _lines(node: Tag | BeautifulSoup) -> list[str]:
    return [
        line.strip()
        for line in node.get_text("\n", strip=True).splitlines()
        if line.strip()
    ]


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


def _normalize_rental_price(raw: str) -> int:
    """Normalize Arango Tobon's rental side when rent and sale share one price."""
    value = str(raw).strip()
    if " - " in value:
        value = value.split(" - ", 1)[0].strip()
    return normalize_price(value)


def _extract_type(raw: str) -> str:
    """Normalize portal type, treating the portal's loft class as a studio."""
    cleaned = raw.strip(" .,:;")
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
    if not _code_from_slug(path_parts[1]):
        return ""
    return urlunparse(clean)


def _code_from_slug(slug: str) -> str:
    code = slug.split("-", 1)[0]
    return code if code.isdecimal() else ""


def _code_from_url(url: str) -> str:
    path_parts = urlparse(url).path.strip("/").split("/")
    if len(path_parts) != 2 or path_parts[0].casefold() != "inmueble":
        return ""
    return _code_from_slug(path_parts[1])


def _empty_listing() -> Listing:
    row: Listing = {column: "" for column in COLUMNS}  # type: ignore[typeddict-item]
    row["portal"] = PORTAL
    for field in ("precio", "area", "habitaciones", "banos", "parqueaderos", "estrato"):
        row[field] = 0
    return row


def _card_type(card: Tag) -> str:
    heading = card.find("h3")
    if heading is not None:
        raw = heading.get_text(" ", strip=True).split(" - ", 1)[0]
        if raw:
            return _extract_type(raw)
    return ""


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


def _card_barrio(card: Tag) -> str:
    location = card.select_one(".proerty_text h4")
    if location is None:
        return ""
    parts = [part.strip() for part in location.get_text(" ", strip=True).split(",") if part.strip()]
    if parts and _fold(parts[-1]) == "MEDELLIN":
        parts.pop()
    return normalize_barrio(parts[-1] if parts else "")


def _parse_card(card: Tag, url: str) -> Listing | None:
    raw_type = _card_type(card)
    if raw_type not in RESIDENTIAL_TYPES:
        return None
    metrics = _card_metrics(card)
    row = _empty_listing()
    row.update(
        {
            "id": f"{PREFIX}-{_code_from_url(url)}",
            "tipo": raw_type,
            "precio": _normalize_rental_price(
                card.select_one(".favroute2 p").get_text(" ", strip=True)
                if card.select_one(".favroute2 p")
                else ""
            ),
            "area": metrics["area"],
            "habitaciones": metrics["habitaciones"],
            "banos": metrics["banos"],
            "barrio": _card_barrio(card),
            "url": url,
        }
    )
    return row


def parse_search_page(html: str) -> list[Listing]:
    """Parse one server-rendered results page and deduplicate card anchors."""
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[Listing] = []
    seen_urls: set[str] = set()
    for card in soup.select(".property_item"):
        url = ""
        for anchor in card.find_all("a", href=True):
            candidate = _detail_url(str(anchor.get("href", "")))
            if candidate:
                url = candidate
                break
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        row = _parse_card(card, url)
        if row is not None:
            rows.append(row)
    return rows


def _detail_rows(soup: BeautifulSoup) -> dict[str, str]:
    rows: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
        if len(cells) >= 2:
            rows[_fold(cells[0].rstrip(" :"))] = cells[1]
    return rows


def _detail_blocks(soup: BeautifulSoup) -> list[str]:
    return [item.get_text(" ", strip=True) for item in soup.select("ul.bloques li")]


def _structured_parking(blocks: list[str]) -> int:
    labels = ("PARQUEADERO", "PARQUEADEROS", "GARAJE", "GARAJES")
    for block in blocks:
        folded = _fold(block)
        if not any(label in folded for label in labels):
            continue
        value = _value_after_label(block, labels)
        number = _number(value)
        return number if number else normalize_garaje(value)
    return 0


def parse_detail_page(html: str) -> DetailFields:
    """Parse structured detail fields; narrative parking text is ignored."""
    soup = BeautifulSoup(html or "", "html.parser")
    rows = _detail_rows(soup)
    blocks = _detail_blocks(soup)
    heading = soup.find(["h1", "h2"])
    heading_text = heading.get_text(" ", strip=True) if heading else ""
    return {
        "codigo": rows.get("CODIGO", "").strip(),
        "tipo": _extract_type(heading_text),
        "precio": _normalize_rental_price(rows.get("PRECIO", "")),
        "area": _number(rows.get("AREA", "")),
        "habitaciones": _number_after_label(" ".join(blocks), ("ALCOBA", "ALCOBAS", "HABITACION", "HABITACIONES")),
        "banos": _number_after_label(" ".join(blocks), ("BANO", "BANOS")),
        "parqueaderos": _structured_parking(blocks),
        "estrato": normalize_estrato(rows.get("ESTRATO", "")),
        "barrio": normalize_barrio(rows.get("BARRIO", "")),
    }


def merge_detail(row: Listing, detail: DetailFields) -> bool:
    """Merge only verified detail data while preserving card identity."""
    expected_code = _code_from_url(row["url"])
    if not detail["codigo"] or detail["codigo"] != expected_code:
        logger.warning("Ignoring detail code mismatch for %s", row["id"])
        return False
    if detail["estrato"]:
        row["estrato"] = detail["estrato"]
    if detail["barrio"]:
        row["barrio"] = detail["barrio"]
    row["parqueaderos"] = detail["parqueaderos"]
    return True


def build_page_url(page: int, ciudad: str = "medellin") -> str:
    """Build the verified Medellín rental route; page one is the canonical root."""
    if _fold(ciudad.strip()) != "MEDELLIN":
        raise UnsupportedCityError(f"Arango Tobón only supports Medellín: {ciudad}")
    return SEARCH_URL if page <= 1 else f"{SEARCH_URL}{page}"


def scrape(
    ciudad: str = "medellin",
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> list[Listing]:
    """Scrape Arango Tobón's Medellín inventory through two HTML phases."""
    try:
        first_url = build_page_url(1, ciudad)
    except UnsupportedCityError as exc:
        logger.warning("%s", exc)
        return []

    page_limit = max_pages if max_pages is not None else (1 if sample_only else None)
    by_id: dict[str, Listing] = {}
    page = 1
    while page_limit is None or page <= page_limit:
        html = fetch_page(first_url if page == 1 else build_page_url(page, ciudad))
        if not html:
            break
        page_rows = parse_search_page(html)
        if not page_rows:
            break
        new_ids = {str(row["id"]) for row in page_rows} - set(by_id)
        if not new_ids:
            break
        for row in page_rows:
            by_id.setdefault(str(row["id"]), row)
        if verbose:
            logger.info("Arango Tobón page %d: %d cards, %d unique", page, len(page_rows), len(by_id))
        page += 1

    rows = list(by_id.values())
    if not rows:
        return []

    details = dict(bulk_fetch([row["url"] for row in rows if row["url"]]))
    for row in rows:
        html = details.get(row["url"], "")
        if html:
            merge_detail(row, parse_detail_page(html))
        else:
            logger.warning("No detail response for %s; keeping card defaults", row["id"])
        warnings = validate(row)
        if verbose:
            for warning in warnings:
                logger.warning("%s: %s", row["id"], warning)
    return rows
