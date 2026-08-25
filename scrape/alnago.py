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
    normalize_garaje,
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

    The legacy markup used an <article> element containing:
        Zona / value / Finalidad / Arriendo / Precio / $X /
        Cod: / NNN.. / Bedrooms / N / Bathrooms / N / Garages / N /
        <a href="/en/inmueble/NNN..">Ver inmueble</a>

    The current SSR markup uses the property link itself as the card and no
    longer emits <article> elements. Both shapes are kept here because the
    portal has changed its homepage markup before.

    Returns list of partial listing dicts (tipo, area, estrato = 0).
    """
    articles = resp.find_all("article")
    current_cards = not articles
    card_elements = articles or [
        link
        for link in resp.find_all("a")
        if "/inmueble/" in link.attrib.get("href", "")
    ]
    cards: list[dict] = []

    for article in card_elements:
        # Find inmueble link
        links = [article] if current_cards else [
            link
            for link in article.find_all("a")
            if link.attrib.get("href", "").startswith("/")
            and "inmueble" in link.attrib.get("href", "")
        ]
        if not links:
            continue

        href = links[0].attrib["href"]
        code = href.rsplit("/", 1)[-1].split("?", 1)[0]

        # Extract text-based fields from the article
        text = article.get_all_text()
        fields = (
            _parse_current_homepage_card_text(text)
            if current_cards
            else _parse_article_text(text)
        )

        codigo = fields.get("codigo", code)
        if not codigo:
            codigo = code

        listing = {
            "id": f"ALN-{codigo}",
            "portal": _PORTAL,
            "tipo": fields.get("tipo", ""),
            "precio": normalize_price(fields.get("precio", "")),
            "area": int(fields.get("area", "0") or "0"),
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


def _parse_current_homepage_card_text(text: str) -> dict[str, str]:
    """Parse the current SSR card text emitted by Alnago.

    Current cards contain a price, title, location, then bedroom, bathroom,
    parking, and area values as separate lines. The property link supplies the
    stable code, so the parser only maps the remaining displayed fields.
    """
    fields: dict[str, str] = {}
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    for line in lines:
        if line.startswith("$"):
            fields["precio"] = line
            break

    title_index = -1
    for index, line in enumerate(lines):
        lower = line.lower()
        if " en arriendo" in lower or " en venta" in lower:
            title_index = index
            marker = " en arriendo" if " en arriendo" in lower else " en venta"
            fields["tipo"] = normalize_tipo(line[: lower.index(marker)].strip())
            break

    if title_index < 0:
        return fields

    if title_index + 1 < len(lines):
        fields["zona"] = lines[title_index + 1].split(",", 1)[0].strip()

    numeric_values = [
        int(line)
        for line in lines[title_index + 2 :]
        if line.isdecimal()
    ]
    if len(numeric_values) >= 3:
        fields["bedrooms"] = str(numeric_values[0])
        fields["bathrooms"] = str(numeric_values[1])
        fields["garages"] = str(numeric_values[2])

    for line in lines[title_index + 2 :]:
        lower = line.lower()
        if "m²" in lower or "m2" in lower:
            fields["area"] = str(_extract_m2(line))
            break

    return fields


# ---------------------------------------------------------------------------
# Phase B — Detail page extraction
# ---------------------------------------------------------------------------
import re as _re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    """Extract plain text from HTML, dropping script/style content."""

    def __init__(self):
        super().__init__()
        self._text: list[str] = []
        self._skip = False
        self._skip_tag = ""

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower in ("script", "style", "noscript", "iframe"):
            self._skip = True
            self._skip_tag = tag_lower
        elif tag_lower in ("br",):
            self._text.append("\n")
        elif tag_lower in ("div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
                           "article", "section", "dl", "dt", "dd"):
            if self._text and self._text[-1] != "\n":
                self._text.append("\n")

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if self._skip and tag_lower == self._skip_tag:
            self._skip = False
            self._skip_tag = ""
        elif tag_lower in ("div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
                           "article", "section", "dl", "dt", "dd"):
            if self._text and self._text[-1] != "\n":
                self._text.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._text.append(data)

    def get_text(self) -> str:
        return "".join(self._text)


def _html_to_text(html: str) -> str:
    """Strip HTML tags using stdlib HTMLParser to get plain text."""
    extractor = _TextExtractor()
    extractor.feed(html)
    text = extractor.get_text()
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    text = text.replace("á", "á").replace("é", "é").replace("í", "í")
    text = text.replace("ó", "ó").replace("ú", "ú").replace("ñ", "ñ")
    text = text.replace("Á", "Á").replace("É", "É").replace("Í", "Í")
    text = text.replace("Ó", "Ó").replace("Ú", "Ú").replace("Ñ", "Ñ")
    return _re.sub(r"\n\s*\n", "\n", text).strip()


def _extract_detail_fields(html: str) -> dict:
    """Extract tipo, area, estrato, parqueaderos from detail page HTML.

    Detail page structure (server-rendered):
        [TIPO] en arriendo en [ZONA] Medellín
        Arriendo: $X
        Detalles / Código del inmueble / NNN.. / Alcobas / N / Baños / N /
        Área privada / N M2 / Área terreno / N M2 / Garaje / N
        ... description text containing "estrato N" ...

    Note: Some titles start with "En arriendo, Casa en..." (no leading tipo).
    We skip noise words ("en", "arriendo", "venta", "for", "rent", ...) until we
    find the first real tipo word.

    Returns parqueaderos=None when detail page has no garaje label — caller
    should keep the Phase A value in that case (distinguishes "garaje=0
    explicitly" from "garaje label not on page").
    """
    result = {"tipo": "", "area": 0, "estrato": 0, "parqueaderos": None}

    # Convert HTML to plain text by stripping tags
    text = _html_to_text(html)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    # --- Tipo: scan line containing trigger phrase, skip noise words ---
    # Edge case: "En arriendo, Casa en..." — first word is "en", not a tipo.
    # We iterate words, skipping known noise words, and use the first real word.
    _NOISE_WORDS = {
        "en", "arriendo", "venta", "for", "rent", "in", "sale", "y",
        "de", "el", "la", "los", "las", "un", "una", "the", "a", "an",
        "del",
    }
    _TRIGGERS = ("en arriendo", "en venta", "for rent", "for sale")

    for line in lines:
        lower = line.lower()
        if not any(t in lower for t in _TRIGGERS):
            continue
        words = [w.strip(",.;:!?¡¿()[]{}\"'") for w in lower.split()]
        for word in words:
            if not word or word in _NOISE_WORDS:
                continue
            translated = _TIPO_EN_TO_ES.get(word, word)
            result["tipo"] = normalize_tipo(translated)
            break
        break  # only process the first matching title line

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

    # --- Garaje: structured label with value on next line ---
    # Feature lists also contain a bare "Garaje" label, so only accept a
    # following value that can actually be normalized as parking data.
    _GARAJE_LABELS = {
        "garaje",
        "garajes",
        "parqueadero",
        "parqueaderos",
        "garage",
        "garages",
    }
    _GARAJE_VALUES = {
        "si",
        "sí",
        "no",
        "incluido",
        "sin",
        "sin garaje",
        "doble",
    }
    for i, line in enumerate(lines):
        if line.strip().lower() not in _GARAJE_LABELS or i + 1 >= len(lines):
            continue
        candidate = lines[i + 1].strip()
        if candidate.isdecimal() or candidate.lower() in _GARAJE_VALUES:
            result["parqueaderos"] = normalize_garaje(candidate)
            break

    # Fallback: inline format "Garaje: 2" or "Garaje 2" on same line.
    if result["parqueaderos"] is None:
        for line in lines:
            lower = line.strip().lower()
            for label in sorted(_GARAJE_LABELS, key=len, reverse=True):
                for separator in (":", " "):
                    prefix = f"{label}{separator}"
                    if not lower.startswith(prefix):
                        continue
                    candidate = line.strip()[len(prefix) :].strip()
                    if candidate.isdecimal() or candidate.lower() in _GARAJE_VALUES:
                        result["parqueaderos"] = normalize_garaje(candidate)
                        break
                if result["parqueaderos"] is not None:
                    break
            if result["parqueaderos"] is not None:
                break

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

    resp = Fetcher.get(_HOMEPAGE_URL)

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
            # None means "garaje label not on page" — keep Phase A value
            # (which may itself be 0 or a value from the homepage card)
            if detail.get("parqueaderos") is not None:
                card["parqueaderos"] = detail["parqueaderos"]

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
