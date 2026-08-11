"""Zitios semantic-card scraper with a bounded detail-enrichment phase."""

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

logger = logging.getLogger(__name__)

_BASE = "https://zitios.com.co"
_SEARCH_URL = f"{_BASE}/inmuebles/g/arriendo/c/medell%C3%ADn/"
_RESIDENTIAL_ROUTES = ("apartamentos", "casas", "apartaestudios")
_RESIDENTIAL_TYPES = frozenset(("apartamento", "casa", "apartaestudio"))
_PORTAL = "zitios"
_PREFIX = "ZIT"
_TOTAL_PAGES = 4
Listing = TypedDict("Listing", {"id": str, "portal": str, "tipo": str, "precio": int, "area": int, "habitaciones": int, "banos": int, "parqueaderos": int, "estrato": int, "barrio": str, "url": str})
DetailFields = TypedDict("DetailFields", {"tipo": str, "precio": int, "area": int, "habitaciones": int, "banos": int, "parqueaderos": int | None, "estrato": int, "barrio": str})


def _page_url(page: int, property_type: str | None = None) -> str:
    search_url = _SEARCH_URL
    if property_type is not None:
        search_url = f"{_BASE}/inmuebles/g/arriendo/t/{property_type}/c/medell%C3%ADn/"
    return search_url if page <= 1 else f"{search_url}?pagina={page}"


def _canonical_url(raw: str) -> str:
    absolute = urljoin(_BASE, raw.strip())
    parsed = urlparse(absolute)
    clean_path = parsed.path.rstrip("/")
    return urlunparse(parsed._replace(path=clean_path, query="", fragment=""))


def _code_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    last_part = path.rsplit("/", 1)[-1]
    suffix = last_part.rsplit("_", 1)[-1]
    return suffix if suffix.isdecimal() else ""


def _number(raw: str) -> int:
    digits: list[str] = []
    for char in raw:
        if char.isdecimal():
            digits.append(char)
            continue
        if digits:
            break
    return int("".join(digits)) if digits else 0


def _text(tag: Tag) -> str:
    return " ".join(tag.stripped_strings).strip()


def _leaf_texts(soup: BeautifulSoup) -> list[str]:
    values: list[str] = []
    for tag in soup.find_all(["span", "p", "li", "h1", "h2", "h3"]):
        value = _text(tag)
        if value:
            values.append(value)
    return list(dict.fromkeys(values))


def _first_labeled(values: list[str], labels: tuple[str, ...]) -> str:
    for value in values:
        lower = value.casefold()
        for label in labels:
            if lower.startswith(label):
                return value[len(label):].lstrip(" :")
    return ""


def _type_from_url(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = slug.rsplit("_", 1)[0].casefold()
    for raw_type in (
        "apartaestudio", "apartamento", "casa", "local", "oficina",
        "bodega", "lote", "finca",
    ):
        if raw_type in slug.split("-"):
            return normalize_tipo(raw_type)
    return ""


def _type_from_heading(value: str) -> str:
    lower = value.casefold()
    for raw_type in (
        "apartaestudio", "apartamento", "casa", "local", "oficina",
        "bodega", "lote", "finca",
    ):
        if raw_type in lower:
            return normalize_tipo(raw_type)
    return ""


def _heading(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(["h1", "h2", "h3"]):
        value = _text(tag)
        if value:
            return value
    return ""


def _is_rental_only(heading: str) -> bool:
    compact = heading.casefold().replace(" ", "")
    if "arriendo/venta" in compact or "venta/arriendo" in compact:
        return False
    if "enventa" in compact and "en arriendo" not in heading.casefold():
        return False
    return "arriendo" in compact


def _attribute_value(
    root: Tag | BeautifulSoup,
    title: tuple[str, ...],
    attribute: str,
) -> str:
    for tag in root.find_all(["span", "meta"]):
        current_title = str(tag.get("title", "")).casefold()
        if any(label in current_title for label in title):
            value = tag.get(attribute)
            if value is not None:
                return str(value).strip()
            return _text(tag)
    return ""


def _property_link(article: Tag) -> str:
    for link in article.find_all("a"):
        href = str(link.get("href", ""))
        if "/inmueble/" in href:
            return _canonical_url(href)
    return ""


def _barrio(soup: BeautifulSoup) -> str:
    for meta in soup.find_all("meta"):
        if meta.get("itemprop") == "addressSubLocality":
            return normalize_barrio(str(meta.get("content", "")))
    for link in soup.find_all("a"):
        href = str(link.get("href", ""))
        if "/n/" in href:
            value = _text(link)
            if value:
                return normalize_barrio(value)
    return ""


def _explicit_no_parking(text: str) -> bool:
    lower = text.casefold()
    return any(
        phrase in lower
        for phrase in ("no cuenta con parqueadero", "sin parqueadero", "sin garaje")
    )


def _is_commercial_use(text: str) -> bool:
    normalized = " ".join(text.casefold().replace("-", " ").split())
    return any(marker in normalized for marker in ("casa comercial", "uso comercial"))


def _parse_card(article: Tag) -> Listing | None:
    url = _property_link(article)
    code = _code_from_url(url)
    heading = _heading(BeautifulSoup(str(article), "lxml"))
    if not url or not code or not _is_rental_only(heading):
        return None

    soup = BeautifulSoup(str(article), "lxml")
    if _is_commercial_use(f"{url} {heading} {soup.get_text(' ', strip=True)}"):
        return None
    values = _leaf_texts(soup)
    raw_type = _type_from_url(url) or _type_from_heading(heading)
    if raw_type not in _RESIDENTIAL_TYPES:
        return None
    garage = _attribute_value(soup, ("garaje", "garajes", "parqueadero"), "content")
    if not garage and _explicit_no_parking(soup.get_text(" ", strip=True)):
        garage = "0"

    return {
        "id": f"{_PREFIX}-{code}",
        "portal": _PORTAL,
        "tipo": raw_type,
        "precio": normalize_price(
            _attribute_value(soup, ("valor propiedad",), "content")
            or _first_labeled(values, ("$",))
        ),
        "area": _number(
            _attribute_value(soup, ("área construida", "area construida"), "content")
        ),
        "habitaciones": _number(
            _attribute_value(soup, ("alcobas", "habitaciones"), "content")
        ),
        "banos": _number(_attribute_value(soup, ("baños", "banos", "baño"), "content")),
        "parqueaderos": normalize_garaje(garage),
        "estrato": normalize_estrato(_number(_first_labeled(values, ("estrato",)))),
        "barrio": _barrio(soup),
        "url": url,
    }


def parse_search_page(html: str) -> list[Listing]:
    soup = BeautifulSoup(html or "", "lxml")
    rows: list[Listing] = []
    for article in soup.find_all("article"):
        row = _parse_card(article)
        if row is not None:
            rows.append(row)
    return rows


def parse_detail_page(html: str) -> DetailFields:
    soup = BeautifulSoup(html or "", "lxml")
    values = _leaf_texts(soup)
    body = soup.get_text(" ", strip=True)
    garage_value = _first_labeled(
        values, ("garaje", "garajes", "parqueadero", "parqueaderos")
    )
    garage: int | None = normalize_garaje(garage_value) if garage_value else None
    if garage is None and _explicit_no_parking(body):
        garage = 0
    return {
        "tipo": _type_from_heading(_heading(soup)),
        "precio": normalize_price(
            next((value for value in values if "$" in value), "")
        ),
        "area": _number(_first_labeled(
            values,
            (
                "área cons", "area cons", "área construida", "area construida",
                "área privada", "area privada", "área lote", "area lote",
            ),
        )),
        "habitaciones": _number(_first_labeled(values, ("alcobas", "habitaciones"))),
        "banos": _number(_first_labeled(values, ("baños", "banos", "baño"))),
        "parqueaderos": garage,
        "estrato": normalize_estrato(_number(_first_labeled(values, ("estrato",)))),
        "barrio": _barrio(soup),
    }


def _needs_detail(row: Listing) -> bool:
    return any(
        row[field] == 0
        for field in ("area", "habitaciones", "banos", "parqueaderos", "estrato")
    )


def _merge_detail(row: Listing, detail: DetailFields) -> None:
    if detail["tipo"]:
        row["tipo"] = row["tipo"] or detail["tipo"]
    for field in ("precio", "area", "habitaciones", "banos", "estrato"):
        if detail[field] > 0:
            row[field] = detail[field]
    # A successful detail response proves an omitted garage label is source-absent.
    row["parqueaderos"] = detail["parqueaderos"] or 0
    if detail["barrio"]:
        row["barrio"] = detail["barrio"]


def scrape(
    ciudad: str = "medellin",
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> list[Listing]:
    """Scrape Zitios Medellín rentals through bounded pagination and details."""
    page_limit = (
        _TOTAL_PAGES
        if max_pages is None
        else max(1, min(max_pages, _TOTAL_PAGES))
    )
    if sample_only and max_pages is None:
        page_limit = 1

    by_id: dict[str, Listing] = {}
    for property_type in _RESIDENTIAL_ROUTES:
        for page in range(1, page_limit + 1):
            html = fetch_page(_page_url(page, property_type)) or ""
            page_rows = parse_search_page(html)
            if not page_rows:
                break
            for row in page_rows:
                if row["id"] not in by_id:
                    by_id[row["id"]] = row
            if verbose:
                logger.info(
                    "Zitios %s page %d: %d cards, %d unique",
                    property_type,
                    page,
                    len(page_rows),
                    len(by_id),
                )

    rows = list(by_id.values())
    if not rows:
        return []

    detail_urls = [row["url"] for row in rows if _needs_detail(row) and row["url"]]
    details = {url: html for url, html in bulk_fetch(detail_urls) if html}
    for row in rows:
        html = details.get(row["url"], "")
        if html:
            _merge_detail(row, parse_detail_page(html))
    return list(rows)
