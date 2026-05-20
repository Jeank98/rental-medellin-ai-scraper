"""Arrendamientos Monserrate (MNS) — two-phase HTML scraper.

Phase A: Fetch 5 listing pages, extract precio + url from cards.
Phase B: Fetch each detail page for full fields using text-based
         label-value parsing (labels without colons).
"""

import html as _html_module
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

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r" {2,}")
_BLOCK_TAGS = [
    "</div>",
    "</p>",
    "</section>",
    "</article>",
    "<br",
    "</li>",
    "</tr>",
    "</td>",
    "</h1>",
    "</h2>",
    "</h3>",
    "</h4>",
    "</h5>",
    "</h6>",
]

_LABEL_MAP = {
    "tipo de inmueble:": "tipo",
    "tipo de inmueble": "tipo",
    "área:": "area",
    "área": "area",
    "alcobas:": "habitaciones",
    "alcobas": "habitaciones",
    "baños:": "banos",
    "baños": "banos",
    "garaje:": "parqueaderos",
    "garaje": "parqueaderos",
    "estrato:": "estrato",
    "estrato": "estrato",
    "sector:": "barrio",
    "sector": "barrio",
    "código:": "codigo",
    "código": "codigo",
    "codigo:": "codigo",
    "codigo": "codigo",
}

_CODIGO_IMG_RE = re.compile(r"[^\d](\d{4,5})(?:-\d+)?\.jpe?g")


def _html_to_text(html: str) -> str:
    for tag in _BLOCK_TAGS:
        html = html.replace(tag, tag + "\n")
    text = _HTML_TAG_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text)
    text = _html_module.unescape(text)
    return text


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


def _parse_detail_page(html: str) -> dict:
    fields: dict[str, str] = {}

    text = _html_to_text(html)
    lines = text.split("\n")
    non_empty = [l.strip() for l in lines if l.strip()]

    for i, line in enumerate(non_empty):
        line_lower = line.lower()

        for label_text, field_key in _LABEL_MAP.items():
            if field_key in fields:
                continue

            label_clean = label_text.rstrip(":").strip()

            # "Label: Value" on same line
            if line_lower.startswith(label_clean + ":") or line_lower.startswith(
                label_clean + " :"
            ):
                after = line.split(":", 1)[1].strip()
                if after:
                    fields[field_key] = after
                break

            # Label alone on its own line — value on next non-empty line
            if line_lower == label_clean:
                if i + 1 < len(non_empty):
                    fields[field_key] = non_empty[i + 1]
                break

            # Label followed by value with space (no colon)
            if line_lower.startswith(label_clean + " "):
                rest = line[len(label_clean) :].strip()
                if rest:
                    fields[field_key] = rest
                break

    # Código fallback: extract from image filename NNNNN-N.jpeg
    if "codigo" not in fields:
        match = _CODIGO_IMG_RE.search(html)
        if match:
            fields["codigo"] = match.group(1)

    return fields


def _merge_detail(listing: dict, detail: dict) -> None:
    codigo = detail.get("codigo", "")
    if codigo:
        listing["id"] = f"MNS-{codigo}"

    if detail.get("tipo"):
        listing["tipo"] = normalize_tipo(detail["tipo"])

    if detail.get("area"):
        area_str = detail["area"].lower()
        area_str = area_str.replace("m²", "").replace("m2", "").replace(" mt", "")
        area_str = area_str.replace("aprox.", "").replace("aproximadamente", "")
        digits = "".join(c for c in area_str if c.isdigit())
        if digits:
            listing["area"] = int(digits)

    if detail.get("habitaciones"):
        digits = "".join(c for c in detail["habitaciones"] if c.isdigit())
        if digits:
            listing["habitaciones"] = int(digits)

    if detail.get("banos"):
        digits = "".join(c for c in detail["banos"] if c.isdigit())
        if digits:
            listing["banos"] = int(digits)

    if detail.get("parqueaderos"):
        listing["parqueaderos"] = normalize_garaje(detail["parqueaderos"])

    if detail.get("estrato"):
        listing["estrato"] = normalize_estrato(detail["estrato"])

    if detail.get("barrio"):
        listing["barrio"] = normalize_barrio(detail["barrio"])


def scrape(
    ciudad="medellin",
    sample_only=False,
    max_pages=None,
    verbose=False,
) -> list[dict]:
    """Scrape Arrendamientos Monserrate listings — two-phase.

    Phase A: Fetch listing pages, extract card data (precio, url, barrio).
    Phase B: Fetch each detail page via bulk_fetch, extract all remaining
             fields using text-based label-value parsing.
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
        logger.info("MNS: sample_only — Phase B (detail pages) skipped. Run full scrape for complete data.")
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

    for listing in listings:
        validate(listing)

    return listings
