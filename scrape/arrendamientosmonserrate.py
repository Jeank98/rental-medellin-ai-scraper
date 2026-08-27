"""Arrendamientos Monserrate (MNS) — two-phase HTML scraper.

Phase A: Fetch 5 listing pages, extract precio + url from cards.
Phase B: Fetch each detail page for full fields from the structured
         product attributes table and SKU.
"""

import hashlib
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrape.fetcher import fetch_page, bulk_fetch
from scrape.normalize import (
    normalize_price,
    normalize_tipo,
    normalize_estrato,
    normalize_garaje,
    normalize_barrio,
)
from scrape.validator import validate

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

_BASE = "https://www.arrendamientosmonserrate.com"
_LISTING_PAGES = 5
_LISTING_URL = "/inmuebles/page/{page}/?swoof=1&product_cat=arrendamiento"

_NUMBER_TOKEN_RE = re.compile(r"(?<!\d)\d+(?:[.,]\d+)*(?!\d)")

_DETAIL_LABEL_MAP = {
    "tipo de inmueble": "tipo",
    "tipo": "tipo",
    "área": "area",
    "area": "area",
    "alcobas": "habitaciones",
    "habitaciones": "habitaciones",
    "baños": "banos",
    "banos": "banos",
    "garaje": "parqueaderos",
    "garajes": "parqueaderos",
    "parqueadero": "parqueaderos",
    "parqueaderos": "parqueaderos",
    "estrato": "estrato",
    "sector": "barrio",
    "barrio": "barrio",
    "código": "codigo",
    "codigo": "codigo",
}


def _has_class(value, class_name: str) -> bool:
    if isinstance(value, (list, tuple)):
        return class_name in value
    return class_name in str(value or "").split()


def _clean_node_text(node) -> str:
    return " ".join(node.stripped_strings).strip()


def _canonical_label(raw: str) -> str:
    return " ".join(raw.replace("\xa0", " ").split()).rstrip(":").strip().casefold()


def _normalize_monserrate_tipo(raw) -> str:
    cleaned = " ".join(str(raw or "").split()).strip(" .,;:")
    if cleaned.casefold() == "casa unifamiliar":
        cleaned = "casa"
    return normalize_tipo(cleaned)


def _parse_number_token(token: str) -> int:
    parts = token.replace(",", ".").split(".")
    if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
        return int("".join(parts))
    return int(parts[0])


def _first_bounded_number(raw, maximum: int) -> int:
    for match in _NUMBER_TOKEN_RE.finditer(str(raw or "")):
        value = _parse_number_token(match.group(0))
        if 0 <= value <= maximum:
            return value
    return 0


def _fallback_id(url: str) -> str:
    digest = hashlib.sha256(str(url or "").encode("utf-8")).hexdigest()[:12]
    return f"MNS-URL-{digest}"


def _ensure_unique_ids(listings: list[dict]) -> None:
    used_ids: set[str] = set()
    for listing in listings:
        listing_id = (listing.get("id") or "").strip() or _fallback_id(
            listing.get("url", "")
        )
        if listing_id in used_ids:
            url_digest = hashlib.sha256(
                str(listing.get("url") or "").encode("utf-8")
            ).hexdigest()[:10]
            candidate = f"{listing_id}-{url_digest}"
            suffix = 2
            while candidate in used_ids:
                candidate = f"{listing_id}-{url_digest}-{suffix}"
                suffix += 1
            listing_id = candidate
        listing["id"] = listing_id
        used_ids.add(listing_id)


def _parse_listing_page(html: str, verbose: bool = False) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.find_all("li", class_=lambda c: c and "product" in c)
    if not cards:
        cards = []
        for li in soup.find_all("li"):
            a = li.find("a", href=True)
            if not a:
                continue
            text = li.get_text()
            if re.search(r"\$\s*[\d.]+", text):
                cards.append(li)

    listings: list[dict] = []
    for card in cards:
        a_tag = card.find("a", href=True)
        if not a_tag:
            continue
        url = urljoin(_BASE, a_tag["href"])

        card_text = card.get_text()
        price_match = re.search(r"\$\s*([\d.]+)", card_text)
        if not price_match:
            continue
        precio = normalize_price(price_match.group(0))
        if not precio:
            continue

        title_el = card.find(
            ["h2", "h3"],
            class_=lambda c: c and ("title" in c.lower() if c else False),
        )
        barrio = ""
        if title_el:
            barrio = normalize_barrio(title_el.get_text(strip=True))

        listing = {
            "id": "",
            "portal": "arrendamientosmonserrate",
            "tipo": "",
            "precio": precio,
            "area": 0,
            "habitaciones": 0,
            "banos": 0,
            "parqueaderos": 0,
            "estrato": 0,
            "barrio": barrio,
            "url": url,
        }
        listings.append(listing)

    return listings


def _parse_detail_page(html: str) -> dict[str, str]:
    """Read only structured WooCommerce attributes and the product SKU."""
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}

    attributes_table = soup.find(
        "table",
        class_=lambda value: _has_class(value, "shop_attributes"),
    )
    if attributes_table:
        for row in attributes_table.find_all("tr"):
            label_node = row.find("th")
            value_node = row.find("td")
            if not label_node or not value_node:
                continue
            field_key = _DETAIL_LABEL_MAP.get(
                _canonical_label(_clean_node_text(label_node))
            )
            if field_key and field_key not in fields:
                value = _clean_node_text(value_node)
                if value:
                    fields[field_key] = value

    sku_node = None
    for wrapper in soup.find_all(
        "span",
        class_=lambda value: _has_class(value, "sku_wrapper"),
    ):
        sku_node = wrapper.find(
            "span",
            class_=lambda value: _has_class(value, "sku"),
        )
        if sku_node:
            break
    if not sku_node:
        sku_node = soup.find(
            "span",
            class_=lambda value: _has_class(value, "sku"),
        )
    if sku_node:
        codigo = _clean_node_text(sku_node)
        if codigo:
            fields["codigo"] = codigo

    return fields


def _merge_detail(listing: dict, detail: dict) -> None:
    codigo = str(detail.get("codigo") or "").strip()
    listing["id"] = (
        f"MNS-{codigo}" if codigo else _fallback_id(listing.get("url", ""))
    )
    if detail.get("tipo"):
        listing["tipo"] = _normalize_monserrate_tipo(detail["tipo"])
    if detail.get("area"):
        listing["area"] = _first_bounded_number(detail["area"], maximum=10_000)

    if detail.get("habitaciones"):
        listing["habitaciones"] = _first_bounded_number(
            detail["habitaciones"], maximum=20
        )

    if detail.get("banos"):
        listing["banos"] = _first_bounded_number(detail["banos"], maximum=20)

    if detail.get("parqueaderos"):
        listing["parqueaderos"] = normalize_garaje(detail["parqueaderos"])

    if detail.get("estrato"):
        estrato = normalize_estrato(detail["estrato"])
        listing["estrato"] = estrato if 1 <= estrato <= 6 else 0

    if detail.get("barrio"):
        listing["barrio"] = normalize_barrio(detail["barrio"])

def scrape(
    ciudad="medellin",
    sample_only=False,
    max_pages=None,
    verbose=False,
) -> list[dict]:
    """Scrape Arrendamientos Monserrate listings — two-phase.

    Phase A: Fetch listing pages, extract precio + url from cards.
    Phase B: Fetch each detail page via bulk_fetch and extract only the
             product attributes table and SKU.
    """
    max_listing_pages = max_pages if max_pages is not None else _LISTING_PAGES
    if sample_only:
        max_listing_pages = min(max_listing_pages, 2)

    # ── Phase A: Collect card listings ──────────────────────────────────
    listings: list[dict] = []
    for page in range(1, max_listing_pages + 1):
        url = urljoin(_BASE, _LISTING_URL.format(page=page))

        if verbose:
            logger.info(
                "MNS Phase A: fetching listing page %d/%d",
                page,
                max_listing_pages,
            )

        html = fetch_page(url)
        if not html:
            if verbose:
                logger.warning("MNS Phase A: empty response for page %d", page)
            break

        page_listings = _parse_listing_page(html, verbose)
        if not page_listings:
            if verbose:
                logger.info("MNS Phase A: no cards on page %d, stopping", page)
            break

        if verbose:
            logger.info(
                "MNS Phase A: page %d → %d listing(s)",
                page,
                len(page_listings),
            )

        listings.extend(page_listings)

    if not listings:
        return []

    if sample_only:
        logger.info(
            "MNS: sample_only — Phase B (detail pages) skipped. "
            "Run full scrape for complete data."
        )
        _ensure_unique_ids(listings)
        return listings

    # ── Phase B: Fetch detail pages ─────────────────────────────────────
    detail_urls = [l["url"] for l in listings]

    if verbose:
        logger.info("MNS Phase B: fetching %d detail pages...", len(detail_urls))

    bulk_results = bulk_fetch(detail_urls)

    for url, html in bulk_results:
        if not html:
            continue
        detail = _parse_detail_page(html)
        for listing in listings:
            if listing["url"] == url:
                _merge_detail(listing, detail)
                break

    _ensure_unique_ids(listings)
    for listing in listings:
        validate(listing)

    return listings
