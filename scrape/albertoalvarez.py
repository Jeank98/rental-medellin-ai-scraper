"""AlbertoAlvarez (AAL) — visible-text HTML card scraper.

Current result cards expose the contract fields as visible text. The legacy
textarea parser remains for older HTML responses.
"""

import json
import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from scrape.fetcher import fetch_page
from scrape.normalize import normalize_price, normalize_tipo, normalize_estrato, normalize_barrio
from scrape.validator import validate

logger = logging.getLogger(__name__)

_BASE = "https://albertoalvarez.com"
_TIPOS = ["apartamento", "casa", "apartaestudio"]
_PER_PAGE = 9

_TIPO_OVERRIDE = {
    "casa vivienda": "casa",
}


def _modern_card_for_link(link):
    """Find one modern result card containing a detail link."""
    for parent in link.parents:
        if getattr(parent, "name", "") != "div":
            continue
        detail_links = [
            candidate
            for candidate in parent.find_all("a", href=True)
            if "/inmuebles/detalle/arrendamientos/" in str(candidate.get("href", ""))
        ]
        if len(detail_links) == 1 and "Cod:" in parent.get_text(" ", strip=True):
            return parent
    return None


def _number_before_label(values: list[str], labels: tuple[str, ...]) -> int:
    """Read a numeric value immediately preceding a metric label."""
    for index, value in enumerate(values):
        if value.casefold() not in labels or index == 0:
            continue
        previous = values[index - 1].replace(".", "").replace(",", "")
        if previous.isdecimal():
            return int(previous)
    return 0


def _modern_card(article, tipo_url: str) -> dict | None:
    """Extract a listing from the current visible-text card structure."""
    link = article.find("a", href=True)
    if not link:
        return None
    href = str(link.get("href", ""))
    url = urljoin(_BASE, href)
    path_parts = urlparse(url).path.rstrip("/").split("/")
    code = path_parts[-2] if len(path_parts) >= 2 else ""
    if not code.startswith("AA-"):
        return None

    values = [value.strip() for value in article.stripped_strings if value.strip()]
    price = next((value for value in values if "$" in value), "")
    location = next(
        (
            value
            for value in values
            if "," in value and value.casefold().endswith(("medellín", "medellin"))
        ),
        "",
    )
    barrio = normalize_barrio(location.split(",", 1)[0]) if location else ""
    return {
        "id": f"AAL-{code}",
        "portal": "albertoalvarez",
        "tipo": normalize_tipo(tipo_url),
        "precio": normalize_price(price),
        "area": _number_before_label(values, ("metros",)),
        "habitaciones": _number_before_label(values, ("alcobas",)),
        "banos": _number_before_label(values, ("baños", "banos")),
        "parqueaderos": 0,
        "estrato": 0,
        "barrio": barrio,
        "url": url,
    }


def _extract_card(article, tipo_url: str) -> dict | None:
    """Extract listing fields from an article card's hidden JSON textarea."""
    textarea = article.find("textarea", class_="field-property")
    if not textarea:
        return None

    try:
        data = json.loads(textarea.get_text(strip=True))
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    code = str(data.get("code", "")).strip()
    raw_tipo = str(data.get("propertyType", "")).strip()
    tipo_raw = _TIPO_OVERRIDE.get(raw_tipo.lower(), raw_tipo)
    tipo = normalize_tipo(tipo_raw)
    precio = normalize_price(data.get("rentValue"))
    area = int(data.get("builtArea", 0) or 0)
    habitaciones = int(data.get("numberOfRooms", 0) or 0)
    household = data.get("householdFeatures") or {}
    banos = int(household.get("baths", 0) or 0)
    parqueaderos = int(household.get("AASimpleparking", 0) or 0)
    estrato = normalize_estrato(data.get("stratum"))
    barrio_raw = str(data.get("sectorName", "")).strip()
    barrio = normalize_barrio(barrio_raw)

    # Build URL slug from raw sectorName
    slug = barrio_raw.lower().replace(" ", "-")
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    url = f"{_BASE}/inmuebles/detalle/arrendamientos/{tipo_url}/{code}/{slug}-medellin/"

    listing = {
        "id": f"AAL-{code}" if code else "",
        "portal": "albertoalvarez",
        "tipo": tipo,
        "precio": precio,
        "area": area,
        "habitaciones": habitaciones,
        "banos": banos,
        "parqueaderos": parqueaderos,
        "estrato": estrato,
        "barrio": barrio,
        "url": url,
    }
    validate(listing)
    return listing


def parse_search_page(html: str, tipo_url: str) -> list[dict]:
    """Parse current Alberto Alvarez result cards from one search page."""
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[dict] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        if "/inmuebles/detalle/arrendamientos/" not in str(link.get("href", "")):
            continue
        card = _modern_card_for_link(link)
        if card is None:
            continue
        row = _modern_card(card, tipo_url)
        if row is not None and row["id"] not in seen:
            rows.append(row)
            seen.add(row["id"])
    return rows


def scrape(ciudad="medellin", sample_only=False, max_pages=None, verbose=False) -> list[dict]:
    """Scrape AlbertoAlvarez rental listings.

    Iterates over 3 tipos (apartamento, casa, apartaestudio), paginating
    until no cards or no new modern IDs are found or a limit is reached.

    Args:
        ciudad: City URL segment (default: medellin).
        sample_only: If True, limit to 3 pages per tipo.
        max_pages: Explicit page limit per tipo.
        verbose: Print per-page progress.

    Returns:
        List of standardized 11-column listing dicts.
    """
    all_listings: list[dict] = []
    modern_seen: set[str] = set()

    for tipo in _TIPOS:
        page = 1
        pages_fetched = 0

        if verbose:
            logger.info("AAL: fetching tipo=%s", tipo)

        while True:
            url = f"{_BASE}/inmuebles/arrendamientos/{tipo}/{ciudad}/?limit={_PER_PAGE}&pag={page}"

            if verbose:
                logger.info("AAL: %s page=%d", tipo, page)

            html = fetch_page(url)
            if not html:
                break

            soup = BeautifulSoup(html, "html.parser")
            articles = soup.find_all("article")
            if not articles:
                page_rows = parse_search_page(html, tipo)
                new_rows = [row for row in page_rows if row["id"] not in modern_seen]
                all_listings.extend(new_rows)
                modern_seen.update(row["id"] for row in new_rows)
                if not new_rows:
                    break
                pages_fetched += 1
                if max_pages is not None and pages_fetched >= max_pages:
                    break
                if sample_only and pages_fetched >= 3:
                    break
                page += 1
                continue

            cards_found = 0
            for article in articles:
                listing = _extract_card(article, tipo)
                if listing:
                    all_listings.append(listing)
                    cards_found += 1

            if cards_found == 0:
                break

            page += 1
            pages_fetched += 1

            if max_pages is not None and pages_fetched >= max_pages:
                break

            if sample_only and pages_fetched >= 3:
                break

    return all_listings
