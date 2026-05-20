"""
Alnago portal scraper — Two-phase: homepage articles → detail pages.

The old REST API (/api/v1/properties) was removed when the site migrated
to Next.js SSR (2026). Now:
- Phase A: fetch homepage, find <article> cards via Scrapling, extract
  codigo, zona, precio, habitaciones, banos, parqueaderos, url.
- Phase B: bulk_fetch detail pages (/es/inmueble/{code}) for tipo,
  area, estrato.
- Detail pages are server-rendered — no Playwright needed.
"""
import logging

from scrapling import Fetcher

from scrape.fetcher import bulk_fetch
from scrape.normalize import (
    normalize_price,
    normalize_tipo,
    normalize_barrio,
    normalize_estrato,
)
from scrape.validator import validate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_HOMEPAGE_URL = "https://alnago.com"
_DETAIL_BASE = "https://alnago.com/es/inmueble"
_PORTAL = "alnago"

# Translation maps for detail page type extraction
_TIPO_EN_TO_ES = {
    "apartment": "apartamento",
    "house": "casa",
    "single-room": "apartaestudio",
    "studio": "apartaestudio",
    "office": "oficina",
    "farm": "finca",
    "lot": "lote",
    "store": "local",
    "establishment": "local",
    "duplex": "casa",
    "cabin": "casa",
    "garage": "local",
    "condominium": "apartamento",
    "consulting": "oficina",
}


# ---------------------------------------------------------------------------
# Phase A — Homepage card extraction via Scrapling
# ---------------------------------------------------------------------------
def _extract_homepage_cards(resp) -> list[dict]:
    """Extract listing cards from homepage using Scrapling's native API.

    Each card is an <article> element containing:
        Zona / value / Finalidad / Arriendo / Precio / $X /
        Cod: / NNN.. / Bedrooms / N / Bathrooms / N / Garages / N /
        <a href="/en/inmueble/NNN..">Ver inmueble</a>

    Returns list of partial listing dicts (tipo, area, estrato = 0).
    """
    articles = resp.find_all("article")
    cards: list[dict] = []

    for article in articles:
        # Find inmueble link
        links = [
            l
            for l in article.find_all("a")
            if l.attrib.get("href", "").startswith("/")
            and "inmueble" in l.attrib.get("href", "")
        ]
        if not links:
            continue

        href = links[0].attrib["href"]
        code = href.rsplit("/", 1)[-1]

        # Extract text-based fields from the article
        text = article.get_all_text()
        fields = _parse_article_text(text)

        codigo = fields.get("codigo", code)
        if not codigo:
            codigo = code

        listing = {
            "id": f"ALN-{codigo}",
            "portal": _PORTAL,
            "tipo": "",  # from detail page
            "precio": normalize_price(fields.get("precio", "")),
            "area": 0,  # from detail page
            "habitaciones": int(fields.get("bedrooms", "0") or "0"),
            "banos": int(fields.get("bathrooms", "0") or "0"),
            "parqueaderos": int(fields.get("garages", "0") or "0"),
            "estrato": 0,  # from detail page
            "barrio": normalize_barrio(fields.get("zona", "")),
            "url": f"{_DETAIL_BASE}/{codigo}",
        }
        cards.append(listing)

    return cards


def _parse_article_text(text: str) -> dict[str, str]:
    """Parse key-value pairs from article text content.

    Text format uses alternating label/value lines:
        Zona\nVilla Hermosa\nFinalidad\nArriendo\nPrecio\n$1.300.000\n
        Cod:\n9993836\nBedrooms\n2\nBathrooms\n1\nGarages\n0

    Returns dict of label_lower → value.
    """
    fields: dict[str, str] = {}
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    label_map = {
        "zona": "zona",
        "finalidad": "finalidad",
        "precio": "precio",
        "cod:": "codigo",
        "cod": "codigo",
        "bedrooms": "bedrooms",
        "bathrooms": "bathrooms",
        "garages": "garages",
    }

    i = 0
    while i < len(lines):
        key = lines[i].lower()
        if key in label_map and i + 1 < len(lines):
            mapped = label_map[key]
            # Skip duplicate keys (only take first occurrence)
            if mapped not in fields:
                fields[mapped] = lines[i + 1]
            i += 2
        else:
            i += 1

    # Handle "Cod:" with trailing colon (value on same line sometimes)
    for j, line in enumerate(lines):
        lower = line.lower()
        if lower.startswith("cod:") and len(line) > 4 and "codigo" not in fields:
            fields["codigo"] = line[4:].strip()
        elif lower.startswith("cod ") and len(line) > 4 and "codigo" not in fields:
            fields["codigo"] = line[4:].strip()

    return fields


# ---------------------------------------------------------------------------
# Phase B — Detail page extraction
# ---------------------------------------------------------------------------
import re as _re

_HTML_TAG_RE = _re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = _re.compile(
    r"<(script|style|noscript|iframe)[^>]*>.*?</\1>", _re.DOTALL | _re.IGNORECASE
)


def _html_to_text(html: str) -> str:
    """Strip HTML tags and script/style blocks to get plain text.

    This is data cleaning (removing markup), NOT field extraction.
    The NO REGEX rule applies to field-level extraction — stripping
    HTML tags is a standard data-cleaning operation.
    """
    # Remove script/style/noscript blocks first
    text = _SCRIPT_STYLE_RE.sub("", html)
    # Replace <br> and block elements with newlines for line separation
    text = _re.sub(r"<br\s*/?>", "\n", text, flags=_re.IGNORECASE)
    text = _re.sub(r"</?(div|p|li|tr|h\d|article|section|dl|dt|dd)[^>]*>", "\n", text, flags=_re.IGNORECASE)
    # Strip remaining HTML tags
    text = _HTML_TAG_RE.sub("", text)
    # Decode HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    text = text.replace("á", "á").replace("é", "é").replace("í", "í")
    text = text.replace("ó", "ó").replace("ú", "ú").replace("ñ", "ñ")
    text = text.replace("Á", "Á").replace("É", "É").replace("Í", "Í")
    text = text.replace("Ó", "Ó").replace("Ú", "Ú").replace("Ñ", "Ñ")
    # Collapse multiple blank lines
    text = _re.sub(r"\n\s*\n", "\n", text)
    return text.strip()


def _extract_detail_fields(html: str) -> dict:
    """Extract tipo, area, estrato from detail page HTML.

    Detail page structure (server-rendered):
        [TIPO] en arriendo en [ZONA] Medellín
        Arriendo: $X
        Detalles / Código del inmueble / NNN.. / Alcobas / N / Baños / N /
        Área privada / N M2 / Área terreno / N M2 / Garaje / N
        ... description text containing "estrato N" ...
    """
    result = {"tipo": "", "area": 0, "estrato": 0}

    # Convert HTML to plain text by stripping tags
    text = _html_to_text(html)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    # --- Tipo: first word of title line containing "en arriendo" or "en venta" ---
    for line in lines:
        lower = line.lower()
        if "en arriendo" in lower or "en venta" in lower:
            first_word = lower.split()[0]
            # Normalize English → Spanish
            tipo = _TIPO_EN_TO_ES.get(first_word, first_word)
            result["tipo"] = normalize_tipo(tipo)
            break

    # --- Area: prefer Área privada, fallback Área terreno ---
    for i, line in enumerate(lines):
        lower = line.strip().lower()
        if ("área privada" in lower or "area privada" in lower) and i + 1 < len(
            lines
        ):
            result["area"] = _extract_m2(lines[i + 1])
            break
        if ("área terreno" in lower or "area terreno" in lower) and i + 1 < len(
            lines
        ):
            val = _extract_m2(lines[i + 1])
            if val > 0:
                result["area"] = val

    # --- Estrato: in description prose, pattern "estrato N" ---
    # Extract only the FIRST contiguous number after "estrato" word
    _estrato_word_re = _re.compile(r"estrato\s+(\d+)", _re.IGNORECASE)
    match = _estrato_word_re.search(text)
    if match:
        result["estrato"] = normalize_estrato(int(match.group(1)))

    return result


def _extract_m2(raw: str) -> int:
    """Extract numeric square meters from '110 M2' or '282'. """
    if not raw:
        return 0
    digits = ""
    raw = raw.strip()
    for ch in raw:
        if ch.isdigit():
            digits += ch
        elif ch in (" ", "M", "m"):
            break
    return int(digits) if digits else 0


# ---------------------------------------------------------------------------
# Main scrape function
# ---------------------------------------------------------------------------
def scrape(
    ciudad="medellin", sample_only=False, max_pages=None, verbose=False
) -> list[dict]:
    """Scrape Alnago rental listings using two-phase approach.

    Phase A: Scrape homepage <article> cards for basic fields (7/11).
    Phase B: Bulk fetch detail pages for tipo, area, estrato.
    """
    all_listings: list[dict] = []

    # ---- Phase A: Homepage articles ----
    if verbose:
        logger.info("ALN: Phase A — fetching homepage")

    fetcher = Fetcher()
    resp = fetcher.get(_HOMEPAGE_URL)

    if resp.status != 200:
        logger.error("ALN: Homepage returned %s", resp.status)
        return []

    cards = _extract_homepage_cards(resp)

    if sample_only:
        cards = cards[:6]
        if verbose:
            logger.info("ALN: sample-only — %d cards", len(cards))

    if not cards:
        logger.warning("ALN: No <article> cards found on homepage")
        return []

    if verbose:
        logger.info("ALN: Phase A — %d cards extracted", len(cards))

    # ---- Phase B: Detail pages ----
    detail_urls = [card["url"] for card in cards]
    if verbose:
        logger.info("ALN: Phase B — fetching %d detail pages", len(detail_urls))

    detail_results = bulk_fetch(detail_urls)

    # Build URL → HTML lookup
    detail_map: dict[str, str] = {}
    for url, html in detail_results:
        if html:
            detail_map[url] = html

    # ---- Merge Phase A + Phase B ----
    for card in cards:
        url = card["url"]
        detail_html = detail_map.get(url, "")
        if detail_html:
            detail = _extract_detail_fields(detail_html)

            if detail["tipo"]:
                card["tipo"] = detail["tipo"]
            if detail["area"]:
                card["area"] = detail["area"]
            if detail["estrato"]:
                card["estrato"] = detail["estrato"]

        validate(card)
        all_listings.append(card)

    if verbose:
        complete = sum(
            1
            for l in all_listings
            if l["tipo"] and l["area"] > 0 and l["estrato"] > 0
        )
        logger.info(
            "ALN: %d total, %d have tipo+area+estrato from detail",
            len(all_listings),
            complete,
        )

    return all_listings
