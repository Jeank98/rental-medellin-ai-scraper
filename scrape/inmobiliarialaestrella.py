"""Inmobiliaria La Estrella (LES) two-phase rental scraper.

Phase A enumerates the three official residential Livewire routes without a
municipal filter: the site's ``s=municipio-en-...`` facet is not reliable
(Itagui returns La Estrella properties and Envigado returns nothing).  Every
route is exhausted through the page's real load-more interaction, and a route
that stops producing cards while its loader image is still visible fails
instead of being published as a partial snapshot.

Phase B fetches each unique detail page once.  The JSON-LD
``RealEstateListing`` block is the authoritative source for metrics and the
municipality used to group rows into the requested city scopes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Final, TypedDict
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag
from playwright.sync_api import Page

from scrape.cities import normalize_city, resolve_city
from scrape.fetcher import bulk_fetch, stealthy_fetch_with_action
from scrape.normalize import normalize_estrato
from scrape.validator import validate

logger = logging.getLogger(__name__)

PORTAL: Final = "inmobiliarialaestrella"
PREFIX: Final = "LES"
BASE_URL: Final = "https://www.inmobiliarialaestrella.com"

COLUMNS: Final[tuple[str, ...]] = (
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
)

# Official residential type filters.  The same routes are the only search
# sources: the unfiltered Arriendo route mixes commercial records, and the
# municipal facet is not trustworthy enough to scope production data.
SEARCH_URLS: Final[dict[str, str]] = {
    "apartamento": f"{BASE_URL}/resultados?gestion=Arriendo&tipo=Apartamentos",
    "casa": f"{BASE_URL}/resultados?gestion=Arriendo&tipo=Casas",
    "apartaestudio": f"{BASE_URL}/resultados?gestion=Arriendo&tipo=Apartaestudios",
}

ACCEPTED_TYPES: Final[frozenset[str]] = frozenset(
    {"apartamento", "casa", "apartaestudio"}
)

# Raw source class -> canonical type.  This mapping is exact on purpose:
# ``Casa-Finca`` and ``Casa-Local`` must never reach ``normalize_tipo``, which
# would collapse them to ``casa`` by splitting on the hyphen.
_SOURCE_TYPES: Final[dict[str, str]] = {
    "apartamento": "apartamento",
    "apartamentos": "apartamento",
    "apto": "apartamento",
    "casa": "casa",
    "casas": "casa",
    "apartaestudio": "apartaestudio",
    "apartaestudios": "apartaestudio",
}

_CARD_SELECTOR: Final = ".results_content--list ._list .estate_itm"
_RECOMMENDATION_MARKER: Final = "related"

# The site writes the neighbourhood inside the property description, e.g.
# ``Amantina Apartamentos, Sector Ditaires, Itagüí``.  A real label needs
# whitespace or a delimiter after the word: the global search control renders
# ``Sector/Ubicación`` and must never be read as a neighbourhood, and generic
# prose such as ``un sector residencial`` has no capitalised name after it.
_SECTOR_PATTERN: Final = re.compile(
    r"(?<![\w/])(?i:sector)\b\s*[:.\-–—]?\s+"
    r"(?P<value>[A-ZÁÉÍÓÚÑ][^,.;:()<>\n]{0,60})"
)
_DETAIL_WORKERS: Final = 10
_SAMPLE_DETAILS_PER_CITY: Final = 3
_SAMPLE_DISCOVERY_BATCHES: Final = 3
_SCROLL_PIXELS: Final = 5000
_SETTLE_INTERVAL_MS: Final = 250
_MIN_SETTLE_SAMPLES: Final = 12
_STABLE_SETTLE_SAMPLES: Final = 2
_MAX_SETTLE_SAMPLES: Final = 60
_INITIAL_CARD_SAMPLES: Final = 20

_STRUCTURAL_REJECTIONS: Final = frozenset(
    {"missing-code", "missing-price", "missing-url"}
)

_CARD_HREFS_JS: Final = """
() => Array.from(
    document.querySelectorAll('.results_content--list ._list .estate_itm'),
)
    .filter((card) => !card.closest('[class*="related"]'))
    .map((card) => ({
        text: card.innerText || '',
        hrefs: Array.from(card.querySelectorAll('a[href]')).map(
            (anchor) => anchor.href,
        ),
    }))
"""

# The loader is only used as a "not finished yet" signal, so it must be the
# element that actually disappears at the end of the route: the site keeps the
# ``.property_loader`` wrapper DIV mounted and removes its spinner IMG.
# Matching the wrapper class alone would report a permanent "still loading"
# state, and a bare ``img[src*="load"]`` match could catch a persistent
# download icon.  A redesign of the loader markup must be re-probed.
_LOADER_IMAGE_SELECTOR: Final = ".property_loader img"

_LOADER_IMAGES_JS: Final = f"""
() => Array.from(document.querySelectorAll({_LOADER_IMAGE_SELECTOR!r})).map(
    (image) => {{
        const box = image.getBoundingClientRect();
        const style = window.getComputedStyle(image);
        return {{
            width: box.width,
            height: box.height,
            display: style.display,
            visibility: style.visibility,
        }};
    }},
)
"""


class PortalDiscoveryError(RuntimeError):
    """The load-more route did not prove a complete card set."""


class PortalDetailError(RuntimeError):
    """A required detail page was missing, malformed, or for another listing."""


class Listing(TypedDict):
    """Canonical 11-column listing row."""

    id: str
    portal: str
    tipo: str
    precio: int
    area: int
    habitaciones: int
    banos: int
    parqueaderos: int
    estrato: int
    barrio: str
    url: str


class Detail(TypedDict):
    """Authoritative fields extracted from one detail page."""

    ciudad: str
    city_key: str
    operation: str
    precio: int
    area: int | None
    habitaciones: int | None
    banos: int | None
    parqueaderos: int
    estrato: int
    barrio: str


class _LivewireTracker:
    """Observe in-flight Livewire update requests while scrolling."""

    def __init__(self) -> None:
        self._pending: set[object] = set()

    @classmethod
    def attach(cls, page: Page) -> "_LivewireTracker | None":
        attach = getattr(page, "on", None)
        if not callable(attach):
            return None
        tracker = cls()
        try:
            attach("request", tracker._on_request)
            attach("requestfinished", tracker._on_finish)
            attach("requestfailed", tracker._on_finish)
        except Exception:  # pragma: no cover - backend without event support
            return None
        return tracker

    @staticmethod
    def _is_livewire(request: object) -> bool:
        method = getattr(request, "method", "")
        url = getattr(request, "url", "")
        return method == "POST" and "/livewire/update" in str(url)

    def _on_request(self, request: object) -> None:
        if self._is_livewire(request):
            self._pending.add(request)

    def _on_finish(self, request: object) -> None:
        if self._is_livewire(request):
            self._pending.discard(request)

    def in_flight(self) -> bool:
        return bool(self._pending)


def _int(value: object) -> int:
    """Convert a structured numeric value without digit-joining decimals."""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(int(value), 0)
    text = str(value).strip()
    if not text:
        return 0
    try:
        return max(int(float(text)), 0)
    except ValueError:
        digits = "".join(char for char in text if char.isdecimal())
        return int(digits) if digits else 0


def _optional_int(value: object) -> int | None:
    """Return a structured number, or ``None`` when the source field is absent."""
    if value is None or value == "":
        return None
    return _int(value)


def _first_int(text: str) -> int:
    """Return the first integer token in rendered text."""
    match = re.search(r"\d+", text)
    return int(match.group()) if match else 0


def _lines(element: Tag) -> list[str]:
    """Return non-empty rendered text lines from a DOM element."""
    return [
        line.strip() for line in element.get_text("\n").splitlines() if line.strip()
    ]


def _code_from_url(url: str) -> str:
    """Read the stable source code from the trailing path segment of a URL."""
    path = urlparse(url).path.rstrip("/")
    match = re.search(r"(\d{3,})$", path)
    return match.group(1) if match else ""


def _new_listing(code: str, url: str) -> Listing:
    """Create a row with the repository's zero defaults."""
    return {
        "id": f"{PREFIX}-{code}",
        "portal": PORTAL,
        "tipo": "",
        "precio": 0,
        "area": 0,
        "habitaciones": 0,
        "banos": 0,
        "parqueaderos": 0,
        "estrato": 0,
        "barrio": "",
        "url": url,
    }


def _visible_code(lines: list[str]) -> str:
    """Read a visible COD/Código label from a card or detail block."""
    for line in lines:
        match = re.match(
            r"(?:c[oó]digo|cod)\.?\s*[:#]?\s*(\d{3,})\b", line, re.IGNORECASE
        )
        if match:
            return match.group(1)
    return ""


def _identity_from_parts(lines: list[str], anchors: list[str]) -> tuple[str, str]:
    """Derive a card's code and detail URL from its text and link candidates."""
    visible = _visible_code(lines)
    if visible:
        for url in anchors:
            if re.search(rf"(?<!\d){re.escape(visible)}(?!\d)", urlparse(url).path):
                return visible, url
        if anchors:
            return visible, anchors[0]
        return visible, ""
    for url in anchors:
        code = _code_from_url(url)
        if code:
            return code, url
    return "", ""


def _card_identity(card: Tag) -> tuple[str, str]:
    """Return the card's stable code and detail URL.

    The visible COD/Código label is the source identity; a trailing numeric
    path segment is the fallback when the card does not render a label.  The
    detail link is chosen by matching that code when the URL exposes it.
    """
    anchors: list[str] = []
    for anchor in card.find_all("a", href=True):
        url = urljoin(BASE_URL, str(anchor.get("href", "")).strip())
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and url not in anchors:
            anchors.append(url)
    return _identity_from_parts(_lines(card), anchors)


def _is_recommendation(tag: Tag) -> bool:
    """Detect recommendation blocks so their cards never enter the results."""
    classes = " ".join(str(value) for value in (tag.get("class") or []))
    if _RECOMMENDATION_MARKER in classes.casefold():
        return True
    for parent in tag.parents:
        if not isinstance(parent, Tag):
            continue
        parent_classes = " ".join(str(value) for value in (parent.get("class") or []))
        if _RECOMMENDATION_MARKER in parent_classes.casefold():
            return True
    return False


def _result_cards(soup: BeautifulSoup) -> list[Tag]:
    """Return only the property cards inside the results container."""
    return [
        card for card in soup.select(_CARD_SELECTOR) if not _is_recommendation(card)
    ]


def _compact_type(raw: str) -> str:
    """Fold a source type label without collapsing compound types."""
    without_dashes = raw.replace("-", " ").replace("–", " ").replace("—", " ")
    lowered = without_dashes.casefold()
    cleaned = re.sub(r"[^a-záéíóúüñ ]", " ", lowered)
    return " ".join(cleaned.split())


def _type_from_lines(lines: list[str]) -> str:
    """Read the exact raw residential type from a card."""
    for line in lines:
        mapped = _SOURCE_TYPES.get(_compact_type(line))
        if mapped:
            return mapped
    for line in lines:
        padded = f" {_compact_type(line)}"
        for marker in (" en arriendo", " arriendo"):
            if marker not in padded:
                continue
            prefix = padded.split(marker, 1)[0].strip()
            mapped = _SOURCE_TYPES.get(prefix)
            if mapped:
                return mapped
    return ""


def _current_price(card: Tag) -> int:
    """Choose the current visible price, excluding struck-through values."""
    candidates: list[int] = []
    for element in card.find_all():
        text = element.get_text(" ", strip=True)
        if "$" not in text:
            continue
        if any("$" in child.get_text(" ", strip=True) for child in element.find_all()):
            continue
        parent: Tag | None = element
        old_price = False
        while isinstance(parent, Tag):
            if parent.name in {"del", "s", "strike"}:
                old_price = True
                break
            parent = parent.parent if isinstance(parent.parent, Tag) else None
        if not old_price:
            candidates.append(_int(text))
    return next((price for price in candidates if price), 0)


def _label_number(lines: list[str], labels: tuple[str, ...]) -> int:
    """Extract the number from a line containing one of the source labels."""
    for line in lines:
        lower = line.casefold()
        for label in labels:
            if label not in lower:
                continue
            label_start = lower.index(label)
            value = line[label_start + len(label) :]
            number = _first_int(value)
            if not number and line[:label_start].strip():
                number = _first_int(line[:label_start])
            if number:
                return number
    return 0


def _area_from_lines(lines: list[str]) -> int:
    """Read the number immediately before the square-metre unit."""
    for index, line in enumerate(lines):
        lower = line.casefold()
        for unit in ("m²", "m2", "mt2", "mts2"):
            if lower == unit and index:
                return _first_int(lines[index - 1])
            if unit in lower:
                return _first_int(line[: lower.index(unit)])
    return 0


def _parse_card(card: Tag, code: str, url: str) -> tuple[Listing | None, str]:
    """Parse one result card; the reason string is empty on success."""
    lines = _lines(card)
    compact_lines = [_compact_type(line) for line in lines]
    if any(
        value.startswith(("casa finca", "casas fincas", "casa local", "casas locales"))
        for value in compact_lines
    ):
        return None, "unsupported-type"
    tipo = _type_from_lines(lines)
    if tipo not in ACCEPTED_TYPES:
        return None, "unsupported-type"
    precio = _current_price(card)
    if not precio:
        return None, "missing-price"
    listing = _new_listing(code, url)
    listing["tipo"] = tipo
    listing["precio"] = precio
    listing["area"] = _area_from_lines(lines)
    listing["habitaciones"] = _label_number(
        lines, ("alcobas", "alcoba", "habitaciones", "habitación")
    )
    listing["banos"] = _label_number(lines, ("baños", "baño", "banos"))
    listing["parqueaderos"] = _label_number(
        lines, ("parqueaderos", "parqueadero", "parq.", "parq")
    )
    return listing, ""


def _card_city_hint(card: Tag) -> str:
    """Read the card's municipality hint from its ``en Arriendo - CITY`` title.

    The hint only schedules which details to sample; the detail JSON-LD
    ``addressLocality`` stays authoritative for grouping.
    """
    for line in _lines(card):
        match = re.search(r"\ben\s+arriendo\s*[-–—]\s*(.+)$", line, re.IGNORECASE)
        if match:
            return normalize_city(match.group(1))
    return ""


def _search_report(
    soup: BeautifulSoup,
) -> tuple[list[Listing], dict[str, str], dict[str, str]]:
    """Parse accepted rows, rejected cards, and per-code city hints."""
    listings: list[Listing] = []
    rejected: dict[str, str] = {}
    hints: dict[str, str] = {}
    seen_ids: set[str] = set()
    for position, card in enumerate(_result_cards(soup), start=1):
        code, url = _card_identity(card)
        if not code:
            rejected[f"card-{position}"] = "missing-code"
            continue
        if not url:
            rejected[f"card-{position}"] = "missing-url"
            continue
        hint = _card_city_hint(card)
        if hint:
            hints.setdefault(code, hint)
        listing, reason = _parse_card(card, code, url)
        if listing is None:
            rejected[code] = reason
            continue
        if listing["id"] in seen_ids:
            continue
        seen_ids.add(listing["id"])
        listings.append(listing)
    return listings, rejected, hints


def parse_search_report(html: str) -> tuple[list[Listing], dict[str, str]]:
    """Parse a rendered results page into accepted rows and rejected cards."""
    listings, rejected, _ = _search_report(BeautifulSoup(html, "html.parser"))
    return listings, rejected


def parse_search_html(html: str) -> list[Listing]:
    """Parse all unique accepted cards from a rendered results page."""
    listings, _ = parse_search_report(html)
    return listings


def _dict_nodes(value: object) -> list[dict]:
    """Flatten nested JSON-LD objects into a deterministic list."""
    nodes: list[dict] = []
    if isinstance(value, dict):
        nodes.append(value)
        for nested in value.values():
            nodes.extend(_dict_nodes(nested))
    elif isinstance(value, list):
        for nested in value:
            nodes.extend(_dict_nodes(nested))
    return nodes


def _has_type(node: dict, expected: str) -> bool:
    """Check a JSON-LD ``@type`` value that may be scalar or a list."""
    node_type = node.get("@type")
    values = node_type if isinstance(node_type, list) else [node_type]
    return any(str(value) == expected for value in values)


def _listing_urls(node: dict) -> list[str]:
    """Collect URLs declared by one JSON-LD listing object."""
    urls: list[str] = []
    for key in ("url", "mainEntityOfPage", "@id", "offers"):
        urls.extend(_string_urls(node.get(key)))
    return urls


def _real_estate_listing(soup: BeautifulSoup, expected_code: str) -> dict:
    """Return the ``RealEstateListing`` JSON-LD object for this property.

    A candidate that declares another property's code is a recommendation, not
    this page's listing, and is never accepted as a fallback: the page
    canonical alone does not make a foreign JSON-LD block authoritative.
    """
    candidates: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        candidates.extend(
            node for node in _dict_nodes(data) if _has_type(node, "RealEstateListing")
        )
    unidentified: list[dict] = []
    mismatched: set[str] = set()
    for node in candidates:
        codes = {code for url in _listing_urls(node) if (code := _code_from_url(url))}
        if expected_code in codes:
            return node
        if codes:
            mismatched.update(codes)
        else:
            unidentified.append(node)
    if candidates and not unidentified:
        raise PortalDetailError(
            f"detail JSON-LD belongs to another listing for {expected_code}: "
            f"saw {sorted(mismatched)[:5]}"
        )
    if unidentified:
        return unidentified[0]
    raise PortalDetailError("detail page has no RealEstateListing JSON-LD")


def _string_urls(value: object) -> list[str]:
    """Collect URL strings from a JSON-LD value of any supported shape."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        urls: list[str] = []
        for key in ("@id", "url", "identifier"):
            if key in value:
                urls.extend(_string_urls(value[key]))
        return urls
    if isinstance(value, list):
        urls = []
        for item in value:
            urls.extend(_string_urls(item))
        return urls
    return []


def _identity_urls(soup: BeautifulSoup, node: dict) -> list[str]:
    """Collect every page URL that can carry the source code."""
    urls: list[str] = []
    for link in soup.find_all("link", href=True):
        rel = link.get("rel") or []
        rel_values = rel if isinstance(rel, list) else [rel]
        if "canonical" in [str(value).casefold() for value in rel_values]:
            urls.append(str(link["href"]))
    for meta in soup.find_all("meta", attrs={"property": "og:url"}):
        content = meta.get("content")
        if content:
            urls.append(str(content))
    for key in ("url", "mainEntityOfPage", "@id", "offers"):
        value = node.get(key)
        urls.extend(_string_urls(value))
    return urls


def _visible_codes(soup: BeautifulSoup) -> set[str]:
    """Collect COD/Código labels from primary content only."""
    codes: set[str] = set()
    for line in _primary_lines(soup):
        match = re.match(
            r"(?:c[oó]digo|cod)\.?\s*[:#]?\s*(\d{3,})\b", line, re.IGNORECASE
        )
        if match:
            codes.add(match.group(1))
    return codes


def _url_has_code(url: str, code: str) -> bool:
    """Check whether a URL path carries ``code`` as a separate number token."""
    if not code:
        return False
    path = urlparse(url).path
    return bool(re.search(rf"(?<!\d){re.escape(code)}(?!\d)", path))


def _verify_identity(soup: BeautifulSoup, node: dict, expected_code: str) -> None:
    """Reject a detail page whose canonical code is not the card's code."""
    if any(_url_has_code(url, expected_code) for url in _identity_urls(soup, node)):
        return
    if expected_code in _visible_codes(soup):
        return
    for key in ("identifier", "sku"):
        for value in _string_urls(node.get(key)):
            if _url_has_code(value, expected_code):
                return
    raise PortalDetailError(
        f"detail identity mismatch for {expected_code}: "
        f"canonical URLs and labels do not carry that code"
    )


def _holders(node: dict) -> list[dict]:
    """Return the listing object and its nested structured subjects."""
    holders = [node]
    for key in ("about", "mainEntity"):
        value = node.get(key)
        if isinstance(value, dict):
            holders.append(value)
    return holders


def _metric(node: dict, key: str) -> int | None:
    """Read an optional structured metric from the listing or its subject."""
    for holder in _holders(node):
        if key in holder:
            value = _optional_int(holder[key])
            if value is not None:
                return value
    return None


def _floor_size(node: dict) -> int | None:
    """Read ``about.floorSize.value`` as a whole square-metre count."""
    for holder in _holders(node):
        floor_size = holder.get("floorSize")
        if isinstance(floor_size, dict):
            value = _optional_int(floor_size.get("value"))
            if value is not None:
                return value
        elif floor_size is not None:
            value = _optional_int(floor_size)
            if value is not None:
                return value
    return None


def _parking(node: dict) -> int:
    """Read the explicit Parqueaderos amenity; an omitted entry means zero."""
    for holder in _holders(node):
        features = holder.get("amenityFeature")
        entries = features if isinstance(features, list) else [features]
        for feature in entries:
            if isinstance(feature, dict):
                name = str(feature.get("name", ""))
                value = feature.get("value")
            elif isinstance(feature, str):
                name = feature
                value = None
            else:
                continue
            lowered = name.casefold()
            if "parqueadero" not in lowered and "parking" not in lowered:
                continue
            if isinstance(value, bool):
                return 1 if value else 0
            return _int(value)
    return 0


def _business_values(offer: dict) -> list[str]:
    """Collect nested ``businessFunction`` URL strings from one whole offer."""
    functions: list[str] = []

    def visit(candidate: object) -> None:
        if isinstance(candidate, dict):
            for key, nested in candidate.items():
                if key == "businessFunction":
                    functions.extend(_string_urls(nested))
                else:
                    visit(nested)
        elif isinstance(candidate, list):
            for item in candidate:
                visit(item)

    visit(offer)
    return functions


def _offer_entries(node: dict) -> list[dict]:
    """Return the structured offers attached to a listing."""
    offers = node.get("offers")
    entries = offers if isinstance(offers, list) else [offers]
    return [entry for entry in entries if isinstance(entry, dict)]


def _offer_operation(offer: dict) -> str:
    """Classify one offer as rent, sale, or unknown from businessFunction."""
    for value in _business_values(offer):
        lowered = value.casefold()
        if "leaseout" in lowered or "lease" in lowered or "rent" in lowered:
            return "rent"
        if "sell" in lowered:
            return "sale"
    return "unknown"


def _operation(node: dict, soup: BeautifulSoup) -> str:
    """Classify the detail page as ``rent``, ``sale``, or ``unknown``."""
    operations = {_offer_operation(offer) for offer in _offer_entries(node)}
    if "rent" in operations:
        return "rent"
    if "sale" in operations:
        return "sale"
    texts: list[str] = []
    heading = soup.find("h1")
    if isinstance(heading, Tag):
        texts.append(heading.get_text(" ", strip=True))
    if soup.title is not None:
        texts.append(soup.title.get_text(" ", strip=True))
    name = node.get("name")
    if isinstance(name, str):
        texts.append(name)
    joined = " ".join(texts).casefold()
    if "venta" in joined and "arriendo" not in joined:
        return "sale"
    if "arriendo" in joined:
        return "rent"
    return "unknown"


def _inside(node: NavigableString, marker: str) -> bool:
    """Check whether a text node lives under a class carrying ``marker``."""
    for parent in node.parents:
        if not isinstance(parent, Tag):
            continue
        classes = " ".join(str(value) for value in (parent.get("class") or []))
        if marker in classes.casefold():
            return True
    return False


def _inside_old_price(node: NavigableString) -> bool:
    """Check whether a text node is rendered as a struck-through old price."""
    for parent in node.parents:
        if isinstance(parent, Tag) and parent.name in {"del", "s", "strike"}:
            return True
    return False


def _primary_lines(soup: BeautifulSoup) -> list[str]:
    """Return visible primary-content lines, excluding recommendations."""
    lines: list[str] = []
    for text in soup.find_all(string=True):
        if not isinstance(text, NavigableString):
            continue
        line = str(text).strip()
        if not line:
            continue
        if _inside(text, _RECOMMENDATION_MARKER) or _inside_old_price(text):
            continue
        lines.append(line)
    return lines


def _labeled_value(lines: list[str], start_index: int, raw: str) -> tuple[str, int]:
    """Return a label value that may share the line or use the next line."""
    value = raw.strip(" :.-–—")
    if value:
        return value, start_index
    if start_index + 1 < len(lines):
        return lines[start_index + 1].strip(), start_index + 1
    return "", start_index


def _estrato(soup: BeautifulSoup) -> int:
    """Read the primary visible Estrato label; a missing label is zero."""
    lines = _primary_lines(soup)
    for index, line in enumerate(lines):
        match = re.match(r"estrato\b\s*[:.\-]?\s*(.*)$", line, re.IGNORECASE)
        if not match:
            continue
        value, _ = _labeled_value(lines, index, match.group(1))
        number = _first_int(value)
        if number:
            return normalize_estrato(number)
    return 0


def _sector(soup: BeautifulSoup, node: dict) -> str:
    """Read the explicit ``Sector`` name from the property's own description.

    Only the listing JSON-LD description and the detail heading are primary
    property content.  Scanning the whole document would let the site's
    ``Sector/Ubicación`` search control, navigation, or a recommendation block
    supply the neighbourhood; an absent explicit sector stays an empty string.
    """
    texts: list[str] = []
    description = node.get("description")
    if isinstance(description, str):
        texts.append(BeautifulSoup(description, "html.parser").get_text(" "))
    heading = soup.find("h1")
    if isinstance(heading, Tag):
        texts.append(heading.get_text(" ", strip=True))
    for text in texts:
        match = _SECTOR_PATTERN.search(text)
        if not match:
            continue
        cleaned = " ".join(match.group("value").split()).rstrip(" -–—")
        if cleaned.casefold() in {"", "-", "n/a", "no aplica"}:
            continue
        return cleaned
    return ""


def _address_locality(node: dict) -> str:
    """Read ``address.addressLocality`` from the listing and its property subject.

    Only the ``RealEstateListing`` and its ``about``/``mainEntity`` carry the
    property address.  Recursing into the whole graph would let an agency or
    provider object supply the municipality and misfile the listing.
    """
    for holder in _holders(node):
        address = holder.get("address")
        addresses = address if isinstance(address, list) else [address]
        for entry in addresses:
            if isinstance(entry, dict):
                locality = entry.get("addressLocality")
            elif isinstance(entry, str):
                locality = None
            else:
                continue
            if isinstance(locality, str) and locality.strip():
                return locality.strip()
    return ""


def _offer_price(node: dict) -> int:
    """Read the current rental price, preferring ``LeaseOut`` over any other offer.

    When the page carries a rental offer, only rental offers may supply the
    price: a ``Sell`` price is a purchase price and must never reach a rental
    scope.  Sale-only pages still yield their price so the caller can classify
    and drop the listing as a non-rental record instead of failing the crawl.
    """
    operations = [(_offer_operation(offer), offer) for offer in _offer_entries(node)]
    rentals = [offer for operation, offer in operations if operation == "rent"]
    unknowns = [offer for operation, offer in operations if operation == "unknown"]
    sales = [offer for operation, offer in operations if operation == "sale"]
    # A page with a rental offer never borrows a purchase price, even when the
    # rental offer itself omits one.  Sale-only pages are priced for
    # classification; the caller drops them as non-rental records.
    candidates = rentals + unknowns if rentals else unknowns + sales
    for offer in candidates:
        price = _optional_int(offer.get("price"))
        if price is None:
            specification = offer.get("priceSpecification")
            specs = (
                specification if isinstance(specification, list) else [specification]
            )
            for spec in specs:
                if isinstance(spec, dict):
                    price = _optional_int(spec.get("price"))
                    if price is not None:
                        break
        if price:
            return price
    return 0


def parse_detail(html: str, expected_code: str) -> Detail:
    """Parse one detail page and validate its identity and core fields."""
    soup = BeautifulSoup(html, "html.parser")
    node = _real_estate_listing(soup, expected_code)
    _verify_identity(soup, node, expected_code)
    locality = _address_locality(node)
    if not locality:
        raise PortalDetailError(f"{expected_code}: JSON-LD has no addressLocality")
    precio = _offer_price(node)
    if precio <= 0:
        raise PortalDetailError(f"{expected_code}: JSON-LD has no rental price")
    return {
        "ciudad": locality,
        "city_key": normalize_city(locality),
        "operation": _operation(node, soup),
        "precio": precio,
        "area": _floor_size(node),
        "habitaciones": _metric(node, "numberOfBedrooms"),
        "banos": _metric(node, "numberOfBathroomsTotal"),
        "parqueaderos": _parking(node),
        "estrato": _estrato(soup),
        "barrio": _sector(soup, node),
    }


def _snapshot_codes(page: Page) -> frozenset[str]:
    """Return the stable codes currently rendered by the results container."""
    entries = page.evaluate(_CARD_HREFS_JS) or []
    codes: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        hrefs = [str(href) for href in entry.get("hrefs") or []]
        code, _ = _identity_from_parts(lines, hrefs)
        if code:
            codes.add(code)
    return frozenset(codes)


def _initial_codes(page: Page) -> frozenset[str]:
    """Wait for the first rendered card set before starting load-more."""
    for _ in range(_INITIAL_CARD_SAMPLES):
        codes = _snapshot_codes(page)
        if codes:
            return codes
        page.wait_for_timeout(_SETTLE_INTERVAL_MS)
    raise PortalDiscoveryError("results container rendered no property cards")


def _image_visible(box: object) -> bool:
    """Report whether one rendered loader image occupies visible space."""
    if not isinstance(box, dict):
        return False
    try:
        width = float(box.get("width") or 0)
        height = float(box.get("height") or 0)
    except (TypeError, ValueError):
        return False
    return (
        width > 0
        and height > 0
        and box.get("display") != "none"
        and box.get("visibility") != "hidden"
    )


def _loader_visible(page: Page) -> bool:
    """Report whether a visible load-more loader image is still rendered."""
    images = page.evaluate(_LOADER_IMAGES_JS) or []
    return any(_image_visible(image) for image in images)


def _settle(page: Page, tracker: _LivewireTracker | None) -> None:
    """Wait until the card set and loader are stable and no request is pending."""
    previous: frozenset[str] | None = None
    stable = 0
    for sample in range(_MAX_SETTLE_SAMPLES):
        page.wait_for_timeout(_SETTLE_INTERVAL_MS)
        current = _snapshot_codes(page)
        in_flight = tracker is not None and tracker.in_flight()
        if in_flight or sample + 1 < _MIN_SETTLE_SAMPLES:
            previous = current
            stable = 0
            continue
        if current == previous:
            stable += 1
            if stable >= _STABLE_SETTLE_SAMPLES:
                return
        else:
            previous = current
            stable = 0
    raise PortalDiscoveryError("load-more never settled; refusing a partial snapshot")


def _drain_results(
    page: Page,
    batch_limit: int | None,
    tracker: _LivewireTracker | None,
) -> frozenset[str]:
    """Drive the real load-more UI until the card set is complete or bounded."""
    previous = _initial_codes(page)
    batches = 0
    while True:
        if batch_limit is not None and batches >= batch_limit:
            return previous
        page.mouse.wheel(0, _SCROLL_PIXELS)
        _settle(page, tracker)
        current = _snapshot_codes(page)
        batches += 1
        if not previous <= current:
            raise PortalDiscoveryError("result cards disappeared during load-more")
        if current != previous:
            previous = current
            continue
        if _loader_visible(page):
            raise PortalDiscoveryError(
                "load-more produced no new cards while its indicator was visible"
            )
        return previous


def _fetch_route(url: str, batch_limit: int | None) -> tuple[str, frozenset[str]]:
    """Render one typed route and prove the code set it exposed."""
    observed: dict[str, object] = {}

    def page_action(page: Page) -> None:
        try:
            tracker = _LivewireTracker.attach(page)
            observed["codes"] = _drain_results(page, batch_limit, tracker)
        except PortalDiscoveryError as error:
            observed["error"] = error
            raise

    rendered = stealthy_fetch_with_action(url, page_action)
    error = observed.get("error")
    if isinstance(error, PortalDiscoveryError):
        raise PortalDiscoveryError(f"{url}: {error}") from error
    if not rendered:
        raise PortalDiscoveryError(f"search page returned no rendered HTML: {url}")
    codes = observed.get("codes")
    if not isinstance(codes, frozenset):
        raise PortalDiscoveryError(
            f"search page never reached a stable card set: {url}"
        )
    return rendered, codes


def _discover(
    batch_limit: int | None, verbose: bool
) -> tuple[list[Listing], dict[str, str]]:
    """Enumerate all three typed routes and union their cards by code.

    Returns the unique cards plus a code -> municipality-hint map used to
    schedule sample details; the hint never overrides the detail municipality.
    """
    by_id: dict[str, Listing] = {}
    hints: dict[str, str] = {}
    for source_type, url in SEARCH_URLS.items():
        rendered, snapshot = _fetch_route(url, batch_limit)
        accepted, rejected, route_hints = _search_report(
            BeautifulSoup(rendered, "html.parser")
        )
        malformed = {
            code: reason
            for code, reason in rejected.items()
            if reason in _STRUCTURAL_REJECTIONS
        }
        if malformed:
            raise PortalDiscoveryError(
                f"{url}: malformed result cards {sorted(malformed.items())[:5]}"
            )
        if not accepted:
            raise PortalDiscoveryError(f"{url}: no accepted rental cards")
        expected = set(snapshot)
        parsed_codes = {_card_code(listing) for listing in accepted}
        missing = expected - parsed_codes - set(rejected)
        if missing:
            raise PortalDiscoveryError(
                f"{url}: rendered cards did not parse: {sorted(missing)[:5]}"
            )
        for listing in accepted:
            code = _card_code(listing)
            by_id.setdefault(listing["id"], listing)
            hint = route_hints.get(code, "")
            if hint and not hints.get(code):
                hints[code] = hint
        if verbose:
            print(
                f"  LES {source_type}: {len(accepted)} card(s), "
                f"{len(rejected)} excluded"
            )
    return list(by_id.values()), hints


def _card_code(listing: Listing) -> str:
    """Return the raw source code embedded in a canonical id."""
    return listing["id"].split("-", 1)[1]


def _fetch_details(urls: list[str]) -> dict[str, str]:
    """Fetch every required detail page or fail the crawl."""
    if not urls:
        return {}
    results = bulk_fetch(urls, max_workers=_DETAIL_WORKERS)
    if len(results) != len(urls):
        raise PortalDetailError(
            f"detail fetch returned {len(results)}/{len(urls)} responses"
        )
    details: dict[str, str] = {}
    for url, html in results:
        if not html:
            raise PortalDetailError(f"detail page fetch failed: {url}")
        details[url] = html
    return details


def _detail_or_card(value: int | None, fallback: int) -> int:
    """Prefer an authoritative detail value, including an explicit zero."""
    return fallback if value is None else value


def _finalize(card: Listing, detail: Detail, verbose: bool) -> dict:
    """Merge authoritative detail fields into one canonical row."""
    row = {
        "id": card["id"],
        "portal": PORTAL,
        "tipo": card["tipo"],
        "precio": detail["precio"],
        "area": _detail_or_card(detail["area"], card["area"]),
        "habitaciones": _detail_or_card(detail["habitaciones"], card["habitaciones"]),
        "banos": _detail_or_card(detail["banos"], card["banos"]),
        "parqueaderos": detail["parqueaderos"],
        "estrato": detail["estrato"],
        "barrio": detail["barrio"],
        "url": card["url"],
    }
    warnings = validate(row)
    if verbose:
        for warning in warnings:
            print(f"  [ANOMALY] {row['id']} — {warning}")
    return row


def _collect_all(
    cards: list[Listing],
    requested: list[str],
    verbose: bool,
) -> dict[str, list[dict]]:
    """Fetch every unique detail once and group rows by source municipality."""
    rows_by_city: dict[str, list[dict]] = {city: [] for city in requested}
    urls = list(dict.fromkeys(card["url"] for card in cards if card["url"]))
    details = _fetch_details(urls)
    for card in cards:
        html = details.get(card["url"])
        if html is None:
            raise PortalDetailError(f"missing detail response for {card['url']}")
        detail = parse_detail(html, _card_code(card))
        if detail["operation"] == "sale":
            logger.warning("%s is a sale listing; excluded", card["id"])
            continue
        if detail["operation"] != "rent":
            raise PortalDetailError(
                f"{card['id']}: detail page is not identifiable as a rental listing"
            )
        city = detail["city_key"]
        if city not in rows_by_city:
            logger.info("%s is in %s; outside the requested scope", card["id"], city)
            continue
        rows_by_city[city].append(_finalize(card, detail, verbose))
    return rows_by_city


def _sample_plan(
    cards: list[Listing],
    hints: dict[str, str],
    requested: list[str],
) -> list[Listing]:
    """Allocate at most three detail candidates per requested city before fetch.

    Cards expose only a municipality hint.  Cards hinted for a requested city
    fill that city's three slots; cards with no usable hint fill leftover slots
    round-robin, so one city's cards cannot consume another city's budget.  The
    detail JSON-LD municipality remains authoritative after fetching.
    """
    allocated: dict[str, list[Listing]] = {city: [] for city in requested}
    spare: list[Listing] = []
    for card in cards:
        city = hints.get(_card_code(card), "")
        if city not in allocated:
            spare.append(card)
        elif len(allocated[city]) < _SAMPLE_DETAILS_PER_CITY:
            allocated[city].append(card)
    pending = list(requested)
    cursor = 0
    while spare and pending:
        city = pending[cursor % len(pending)]
        allocated[city].append(spare.pop(0))
        cursor += 1
        pending = [
            candidate
            for candidate in pending
            if len(allocated[candidate]) < _SAMPLE_DETAILS_PER_CITY
        ]
    return [card for city in requested for card in allocated[city]]


def _collect_sample(
    cards: list[Listing],
    hints: dict[str, str],
    requested: list[str],
    verbose: bool,
) -> dict[str, list[dict]]:
    """Fetch at most three detail pages per requested city."""
    rows_by_city: dict[str, list[dict]] = {city: [] for city in requested}
    planned = _sample_plan(cards, hints, requested)
    urls = [card["url"] for card in planned if card["url"]]
    details = _fetch_details(urls)
    for card in planned:
        html = details.get(card["url"])
        if html is None:
            raise PortalDetailError(f"missing detail response for {card['url']}")
        detail = parse_detail(html, _card_code(card))
        if detail["operation"] == "sale":
            logger.warning("%s is a sale listing; excluded", card["id"])
            continue
        if detail["operation"] != "rent":
            raise PortalDetailError(
                f"{card['id']}: detail page is not identifiable as a rental listing"
            )
        city = detail["city_key"]
        if city not in rows_by_city:
            logger.info("%s is in %s; outside the requested scope", card["id"], city)
            continue
        if len(rows_by_city[city]) >= _SAMPLE_DETAILS_PER_CITY:
            continue
        rows_by_city[city].append(_finalize(card, detail, verbose))
    return rows_by_city


def _requested_cities(ciudades: list[str] | tuple[str, ...] | str) -> list[str]:
    """Resolve and deduplicate requested city scopes in caller order."""
    values = [ciudades] if isinstance(ciudades, str) else list(ciudades)
    requested: list[str] = []
    for value in values:
        key = resolve_city(value)
        if key not in requested:
            requested.append(key)
    if not requested:
        raise ValueError("at least one city is required")
    return requested


def _validate_max_pages(max_pages: int | None) -> None:
    """Reject non-positive or non-integer page bounds."""
    if max_pages is None:
        return
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError(f"max_pages must be a positive integer, got {max_pages!r}")


def scrape_cities(
    ciudades: list[str] | tuple[str, ...],
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> dict[str, list[dict]]:
    """Scrape every requested city from one discovery pass.

    Returns one list per requested canonical city key; a city with no matching
    inventory keeps an empty list.  Discovery runs once across the three typed
    routes and each property detail is fetched once, then grouped by its
    authoritative municipality.
    """
    requested = _requested_cities(ciudades)
    _validate_max_pages(max_pages)
    if max_pages is not None:
        batch_limit: int | None = max_pages
    elif sample_only:
        batch_limit = min(max(len(requested), 1), _SAMPLE_DISCOVERY_BATCHES)
    else:
        batch_limit = None
    cards, hints = _discover(batch_limit, verbose)
    if verbose:
        print(f"  LES: {len(cards)} unique card(s) discovered")
    if sample_only:
        rows_by_city = _collect_sample(cards, hints, requested, verbose)
    else:
        rows_by_city = _collect_all(cards, requested, verbose)
    if verbose:
        for city in requested:
            print(f"  LES {city}: {len(rows_by_city[city])} listing(s)")
    return rows_by_city


def scrape(
    ciudad: str = "medellin",
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> list[dict]:
    """Scrape one city through the shared multi-city engine."""
    key = resolve_city(ciudad)
    return scrape_cities(
        [key],
        sample_only=sample_only,
        max_pages=max_pages,
        verbose=verbose,
    )[key]


__all__ = [
    "ACCEPTED_TYPES",
    "COLUMNS",
    "PORTAL",
    "PREFIX",
    "SEARCH_URLS",
    "Detail",
    "Listing",
    "PortalDetailError",
    "PortalDiscoveryError",
    "parse_detail",
    "parse_search_html",
    "parse_search_report",
    "scrape",
    "scrape_cities",
]
