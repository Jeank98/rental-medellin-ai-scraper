"""Arrendamientos Envigado (AEV) — sitemap + server-rendered detail scraper.

Discovery reads ``sitemap.xml`` because robots.txt disallows ``/api/``.  Every
detail URL is fetched once, and the page's canonical ``/inmueble/...`` slug
and primary SSR labels are authoritative for operation, residential type,
municipality, barrio, code and the 11 canonical listing fields.

Sitemap slug hints are only used to discard explicit sale/non-residential
entries and to bound sample work per city.  Unknown and cityless entries are
retained: Arrendamientos Envigado publishes cityless sitemap URLs whose detail
page redirects to a canonical municipality (for example code 80356).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import deque
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree

import scrapling
from bs4 import BeautifulSoup, Comment, NavigableString

from scrape.cities import CITY_LABELS, normalize_city, resolve_city
from scrape.fetcher import bulk_fetch
from scrape.normalize import normalize_barrio, normalize_estrato

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

PORTAL = "arrendamientosenvigado"
PREFIX = "AEV"

_BASE = "https://arrendamientosenvigadosa.com.co"
_SITEMAP_URL = f"{_BASE}/sitemap.xml"
_SITEMAP_TIMEOUT = 30
_SITEMAP_RETRIES = 3
_SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
_MAX_SITEMAP_DEPTH = 2
_DETAIL_BATCH_SIZE = 100
_SAMPLE_BATCH_SIZE = 20
_SAMPLE_MIN_BATCHES = 3
_SAMPLE_ROWS_PER_CITY = 3
_BULK_WORKERS = 10

_ROW_FIELDS = (
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

_RESIDENTIAL_TIPOS = {
    "apartamento": "apartamento",
    "apto": "apartamento",
    "apartaestudio": "apartaestudio",
    "aparta-estudio": "apartaestudio",
    "casa": "casa",
}

_NON_RESIDENTIAL_TIPOS = frozenset(
    {
        "oficina",
        "oficinas",
        "local",
        "locales",
        "bodega",
        "bodegas",
        "lote",
        "lotes",
        "finca",
        "fincas",
        "casa-finca",
        "casas-fincas",
        "consultorio",
        "parqueadero",
        "parqueaderos",
        "hotel",
        "hoteles",
        "edificio",
    }
)

_OPERATION_WORDS = {
    "arriendo": "arriendo",
    "arriendos": "arriendo",
    "venta": "venta",
    "ventas": "venta",
}

_CITY_KEYS = tuple(CITY_LABELS)
_CITY_KEYS_BY_WORDS = tuple(
    sorted(_CITY_KEYS, key=lambda key: len(key.split("-")), reverse=True)
)

_DEAD_MARKERS = (
    "ya no se encuentra disponible",
    "inmueble no disponible",
    "no se encuentra disponible",
)

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

_RELATED_ATTR_MARKERS = (
    "otros-resultados",
    "otrosresultados",
    "relacionad",
    "similar",
    "recomend",
    "tambien-te-puede",
    "te-puede-interesar",
)

_RELATED_HEADING_MARKERS = (
    "otros resultados",
    "resultados similares",
    "inmuebles similares",
    "propiedades similares",
    "tambien te puede interesar",
    "recomendados para ti",
)

_LABEL_FIELDS = {
    "precio de arriendo": ("precio", 0),
    "precio": ("precio", 1),
    "area construida": ("area", 0),
    "area": ("area", 1),
    "habitaciones": ("habitaciones", 0),
    "banos": ("banos", 0),
    "parqueadero": ("parqueaderos", 0),
    "parqueaderos": ("parqueaderos", 0),
    "estrato": ("estrato", 0),
    "codigo": ("codigo", 0),
}

_LABELS_BY_LENGTH = tuple(sorted(_LABEL_FIELDS, key=len, reverse=True))


class PortalError(RuntimeError):
    """Base error for a portal-level technical failure."""


class PortalFetchError(PortalError):
    """The sitemap or a required detail page could not be fetched."""


class PortalParseError(PortalError):
    """The response structure or identity did not match the portal."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    url: str
    code: str
    tipo: str
    operacion: str
    municipio: str
    barrio: str


def _fold(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.casefold().split())


def _clean_ws(value) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _clean_text(node) -> str:
    return " ".join(node.stripped_strings).strip()


def _local_name(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].casefold()


def _known_city(value: str) -> str:
    key = normalize_city(value or "")
    # The portal also uses this Medellín corregimiento as a locality label.
    if key == "san-antonio-de-prado":
        return "medellin"
    return key if key in CITY_LABELS else ""


def _operation_from_text(text: str) -> str:
    folded = _fold(text)
    for word, operation in _OPERATION_WORDS.items():
        if re.search(rf"\b{word}\b", folded):
            return operation
    return ""


def _tipo_from_text(text: str) -> str:
    folded = _fold(text).strip(" .,:;")
    if re.match(r"^casa(?:\s+|-)(finca|local|lote|bodega|oficina)\b", folded):
        return ""
    match = re.match(
        r"^(aparta\s*estudio|apartaestudio|apartamento|apto|casa)\b", folded
    )
    if not match:
        return ""
    return _RESIDENTIAL_TIPOS.get(match.group(1).replace(" ", "-"), "")


def _residential_tipo(raw: str) -> str:
    key = _fold(raw).replace(" ", "-")
    return _RESIDENTIAL_TIPOS.get(key, "")


def _is_explicit_non_residential(raw: str) -> bool:
    key = _fold(raw).replace(" ", "-")
    if key in _NON_RESIDENTIAL_TIPOS:
        return True
    return any(token in _NON_RESIDENTIAL_TIPOS for token in key.split("-"))


def _match_municipality_tokens(tokens: list[str]) -> tuple[str, int, int]:
    for size in (4, 3, 2, 1):
        for start in range(0, len(tokens) - size + 1):
            city = _known_city("-".join(tokens[start : start + size]))
            if city:
                return city, start, size
    return "", 0, 0


def _parse_detail_slug(url: str) -> dict | None:
    """Split a canonical ``/inmueble/{tipo}-{operacion}-{city}-{barrio}-{code}`` URL."""
    parsed = urlsplit(str(url or ""))
    parts = [part for part in unquote(parsed.path).split("/") if part]
    if len(parts) < 2 or parts[-2].casefold() != "inmueble":
        return None

    slug = parts[-1]
    code_match = re.search(r"(\d+)$", slug)
    code = code_match.group(1) if code_match else ""
    body = slug[: code_match.start()].rstrip("-") if code_match else slug
    tokens = [token for token in re.split(r"-+", body) if token]

    operation_index = next(
        (
            index
            for index, token in enumerate(tokens)
            if _fold(token) in _OPERATION_WORDS
        ),
        None,
    )
    operation = ""
    tipo_raw = ""
    remainder: list[str] = []
    if operation_index is None:
        tipo_raw = "-".join(tokens)
    else:
        operation = _OPERATION_WORDS[_fold(tokens[operation_index])]
        tipo_tokens = tokens[:operation_index]
        if tipo_tokens and _fold(tipo_tokens[-1]) == "en":
            tipo_tokens = tipo_tokens[:-1]
        tipo_raw = "-".join(tipo_tokens)
        remainder = tokens[operation_index + 1 :]
        if remainder and _fold(remainder[0]) in ("en", "de"):
            remainder = remainder[1:]

    city, city_start, city_size = _match_municipality_tokens(remainder)
    if city:
        barrio_tokens = remainder[city_start + city_size :]
        if city_start:
            tipo_raw = "-".join(filter(None, [tipo_raw, *remainder[:city_start]]))
    else:
        barrio_tokens = remainder

    return {
        "url": url,
        "code": code,
        "tipo": tipo_raw,
        "operacion": operation,
        "municipio": city,
        "barrio": " ".join(barrio_tokens).strip(),
    }


def _candidate_from_loc(loc: str) -> _Candidate | None:
    url = urljoin(_BASE, str(loc or "").strip())
    info = _parse_detail_slug(url)
    if info is None:
        return None
    if info["operacion"] == "venta":
        return None
    if info["tipo"] and _is_explicit_non_residential(info["tipo"]):
        return None
    return _Candidate(
        url=url,
        code=info["code"],
        tipo=_residential_tipo(info["tipo"]),
        operacion=info["operacion"],
        municipio=info["municipio"],
        barrio=info["barrio"],
    )


def _fetch_sitemap_xml(url: str) -> str:
    """Fetch a sitemap as the original XML document.

    ``fetch_page`` returns Scrapling's HTML-normalized ``html_content``, which
    re-serializes an ``application/xml`` sitemap as
    ``<html><body><urlset ...>``.  Sitemaps are read from ``Response.body`` so
    the document reaches the XML parser unmodified; an HTML error or challenge
    page therefore still fails as malformed/non-sitemap XML.
    """
    try:
        response = scrapling.Fetcher.get(
            url, timeout=_SITEMAP_TIMEOUT, retries=_SITEMAP_RETRIES
        )
    except Exception as error:
        raise PortalFetchError(f"sitemap fetch failed: {url}: {error}") from error

    if response.status >= 400:
        raise PortalFetchError(f"sitemap fetch failed: {url} (HTTP {response.status})")

    body = response.body
    if isinstance(body, bytes):
        try:
            body = body.decode(response.encoding or "utf-8")
        except UnicodeDecodeError as error:
            raise PortalParseError(f"undecodable sitemap response: {url}") from error
        body = body.lstrip("\ufeff")
    if not body or not body.strip():
        raise PortalFetchError(f"sitemap fetch failed: {url} (empty body)")
    return body


def _sitemap_kind_and_locs(xml_text: str) -> tuple[str, list[str]]:
    """Return (kind, locs) for a namespaced sitemap or sitemap index."""
    if not xml_text or not xml_text.strip():
        raise PortalParseError("empty sitemap response")
    try:
        root = ElementTree.fromstring(xml_text.strip())
    except ElementTree.ParseError as error:
        raise PortalParseError(f"malformed sitemap XML: {error}") from error

    kind = _local_name(root.tag)
    if kind not in ("urlset", "sitemapindex"):
        raise PortalParseError(f"unexpected sitemap root: {kind or root.tag!r}")
    namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    if namespace != _SITEMAP_NAMESPACE:
        raise PortalParseError(
            f"unexpected sitemap namespace: {namespace or root.tag!r}"
        )

    entry_name = "url" if kind == "urlset" else "sitemap"
    locs: list[str] = []
    for entry in root:
        if _local_name(entry.tag) != entry_name:
            continue
        for node in entry.iter():
            if _local_name(node.tag) != "loc":
                continue
            value = (node.text or "").strip()
            if value:
                parts = urlsplit(value)
                if parts.scheme not in ("http", "https") or not parts.netloc:
                    raise PortalParseError(f"invalid sitemap loc: {value!r}")
                locs.append(value)
            break
    return kind, locs


def _discover_detail_locs() -> list[str]:
    queue: deque[tuple[str, int]] = deque([(_SITEMAP_URL, 0)])
    visited: set[str] = set()
    locs: list[str] = []

    while queue:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        kind, found = _sitemap_kind_and_locs(_fetch_sitemap_xml(url))
        if kind == "sitemapindex":
            if depth >= _MAX_SITEMAP_DEPTH:
                raise PortalParseError(f"sitemap nesting too deep at {url}")
            for child in found:
                if child not in visited:
                    queue.append((child, depth + 1))
        else:
            locs.extend(found)

    return locs


def _discover_candidates() -> list[_Candidate]:
    locs = _discover_detail_locs()
    candidates: list[_Candidate] = []
    seen: set[str] = set()
    dropped = 0

    for loc in locs:
        candidate = _candidate_from_loc(loc)
        if candidate is None:
            dropped += 1
            continue
        identity = candidate.code or candidate.url
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(candidate)

    if not candidates:
        raise PortalParseError("sitemap contained no rental detail candidates")

    logger.info(
        "AEV discovery: %d sitemap loc(s), %d candidate detail(s), %d explicit non-rental",
        len(locs),
        len(candidates),
        dropped,
    )
    return candidates


def _canonical_href(soup: BeautifulSoup) -> str:
    for link in soup.find_all("link", href=True):
        rel = link.get("rel") or []
        if isinstance(rel, str):
            rel = [rel]
        if any(str(value).casefold() == "canonical" for value in rel):
            return urljoin(_BASE, link["href"].strip())

    meta = soup.find("meta", attrs={"property": "og:url"})
    if meta and meta.get("content"):
        return urljoin(_BASE, meta["content"].strip())
    return ""


def _robots_noindex(soup: BeautifulSoup) -> bool:
    for meta in soup.find_all("meta"):
        name = str(meta.get("name") or meta.get("property") or "").casefold()
        content = str(meta.get("content") or "").casefold()
        if name == "robots" and "noindex" in content:
            return True
    return False


def _is_soft_404(soup: BeautifulSoup) -> bool:
    """Classify the verified HTTP-200 soft-404 page only.

    All three observed signals must agree: ``robots noindex``, the site-root
    canonical and the explicit unavailable text.  A challenge/error response
    without any one of them is a technical failure, never a dead listing.
    """
    if not _robots_noindex(soup):
        return False
    canonical = _canonical_href(soup).rstrip("/")
    if canonical != _BASE.rstrip("/"):
        return False
    title = _fold(_clean_text(soup.title)) if soup.title else ""
    visible = _fold(soup.get_text(" ", strip=True))
    return any(text in title or text in visible for text in _DEAD_MARKERS)


def _contains_primary_label(node) -> bool:
    for child in node.find_all(True):
        text = _fold(_clean_text(child))
        if text in ("precio de arriendo", "codigo"):
            return True
        if text.startswith("precio de arriendo:") or text.startswith("codigo:"):
            return True
    return False


def _primary_scope(soup: BeautifulSoup):
    """Return the detail region with scripts and recommendation blocks removed."""
    for tag in ("script", "style", "noscript", "template", "iframe", "svg"):
        for node in soup.find_all(tag):
            node.decompose()

    scope = soup.find("main") or soup.find("article") or soup.body or soup

    for node in list(scope.find_all(True)):
        if node.parent is None:
            continue
        if node is scope:
            continue
        attrs = " ".join(
            [str(value) for value in (node.get("class") or [])]
            + [str(node.get("id") or "")]
        )
        folded_attrs = _fold(attrs)
        if any(marker in folded_attrs for marker in _RELATED_ATTR_MARKERS):
            node.decompose()

    for node in list(scope.find_all(_HEADING_TAGS)):
        if node.parent is None:
            continue
        heading = _fold(_clean_text(node))
        if not any(marker in heading for marker in _RELATED_HEADING_MARKERS):
            continue
        sibling = node.next_sibling
        while sibling is not None:
            next_sibling = sibling.next_sibling
            if getattr(sibling, "name", None) in _HEADING_TAGS:
                break
            if getattr(sibling, "name", None) is not None:
                if _contains_primary_label(sibling):
                    break
                sibling.decompose()
            elif str(sibling).strip():
                sibling.extract()
            sibling = next_sibling
        node.decompose()

    return scope


def _match_label(text: str) -> tuple[str, str]:
    """Match one exact structured metric label, optionally with its value.

    Only a whole label (or a label followed by a separator and a bounded value
    token) is accepted.  Label-prefixed prose such as ``Parqueaderos
    visitantes: 2`` is not a structured metric row and never matches.
    """
    folded = _fold(text).strip()
    for label in _LABELS_BY_LENGTH:
        if folded == label or folded == f"{label}:":
            return label, ""
        if not folded.startswith(label):
            continue
        inline = folded[len(label) :].lstrip(" :-\u2013")
        if not inline or len(inline) > 24:
            continue
        if not re.match(r"(?:\$|cop\b|\d)", inline, re.IGNORECASE):
            continue
        return label, inline
    return "", ""


_VALUE_CONTAINER_TAGS = frozenset(
    {"ul", "ol", "dl", "table", "thead", "tbody", "tfoot", "tr", "section", "article"}
)


def _is_value_cell(node) -> bool:
    """Return whether ``node`` is a scalar value cell, not a metrics block.

    A price card renders the label and its value as adjacent cells and then a
    ``ul`` with the remaining metrics (``Área construida``, ``Habitaciones``…).
    Only a node that carries its own scalar text qualifies; a metrics container,
    an empty cell and another structured label never do.
    """
    if node is None or getattr(node, "name", None) is None:
        return False
    if node.name in _VALUE_CONTAINER_TAGS:
        return False
    text = _clean_text(node)
    if not text:
        return False
    if _match_label(text)[0]:
        return False
    for child in node.find_all(True):
        child_text = _clean_text(child)
        if child_text and _match_label(child_text)[0]:
            return False
    return True


def _extract_value(node) -> str:
    """Return the value cell rendered immediately after ``node``'s label.

    The value must be the next sibling cell of the label itself: the price card
    keeps ``Precio de arriendo`` and ``$7.500.000`` as adjacent ``p`` elements
    followed by the metrics ``ul``, while a metric row keeps the label and value
    ``span`` siblings inside its ``li``.  An empty, missing or non-scalar
    adjacent sibling never borrows a following row, a metrics container or the
    rest of the parent.
    """
    for sibling in node.next_siblings:
        if isinstance(sibling, Comment):
            continue
        if isinstance(sibling, NavigableString):
            text = _clean_ws(sibling)
            if not text:
                continue
            return "" if _match_label(text)[0] else text
        if getattr(sibling, "name", None) is None:
            continue
        if not _is_value_cell(sibling):
            return ""
        return _clean_ws(_clean_text(sibling))
    return ""


def _collect_labels(scope) -> dict[str, str]:
    matches: list[tuple[object, str, str]] = []

    for node in scope.find_all(True):
        if node.parent is None and node is not scope:
            continue
        text = _clean_text(node)
        if not text or len(text) > 80:
            continue
        label, remainder = _match_label(text)
        if not label:
            continue
        matches.append((node, label, remainder))

    matched_ids = {id(node) for node, _, _ in matches}
    found: dict[str, tuple[int, str]] = {}
    for node, label, remainder in matches:
        if any(id(child) in matched_ids for child in node.find_all(True)):
            continue
        folded_text = _fold(_clean_text(node))
        if label == "precio" and "administracion" in folded_text:
            continue
        field, priority = _LABEL_FIELDS[label]
        value = _clean_ws(remainder or _extract_value(node))
        if not value:
            continue
        previous = found.get(field)
        if previous is None or priority < previous[0]:
            found[field] = (priority, value)

    return {field: value for field, (_, value) in found.items()}


def _og_location_text(soup: BeautifulSoup) -> str:
    for meta in soup.find_all("meta"):
        prop = str(meta.get("property") or meta.get("name") or "").casefold()
        if prop in ("og:image:alt", "og:location", "place:location:locality"):
            content = _clean_ws(meta.get("content"))
            if content:
                return content
    return ""


def _listing_title_text(soup: BeautifulSoup) -> str:
    """Return the listing headline from ``og:title``, falling back to ``<title>``.

    The portal renders ``{tipo} en {operacion} en {Municipio}, {Barrio} · Cód.
    {code}`` in both places, so either one names the municipality of a listing
    whose H1 is the bare ``Apartamento en arriendo`` heading.
    """
    for meta in soup.find_all("meta"):
        prop = str(meta.get("property") or meta.get("name") or "").casefold()
        if prop == "og:title":
            content = _clean_ws(meta.get("content"))
            if content:
                return content
    node = soup.find("title")
    return _clean_text(node) if node else ""


def _municipality_from_text(text: str) -> str:
    folded = _fold(text)
    for key in _CITY_KEYS_BY_WORDS:
        phrase = _fold(CITY_LABELS[key]).replace("-", " ")
        if re.search(rf"\ben\s+{re.escape(phrase)}\b", folded):
            return key
        if re.search(rf"\bmunicipio\s+(?:de\s+)?{re.escape(phrase)}\b", folded):
            return key
    return ""


def _location_city_barrio(text: str) -> tuple[str, str]:
    """Split the verified ``Municipio, Barrio`` metadata shape.

    ``og:image:alt`` states the location as a bare ``Municipio, Barrio`` pair,
    not as an ``en Municipio`` phrase.  The first segment must be a supported
    municipality; otherwise the metadata is ignored instead of guessed.
    """
    segments = [
        segment.strip()
        for segment in re.split(r"[,|]", str(text or ""))
        if segment.strip()
    ]
    if not segments:
        return "", ""
    city = _known_city(segments[0])
    if not city:
        return "", ""
    return city, (segments[1] if len(segments) > 1 else "")


def _municipality_phrase(text: str) -> str:
    """Return the trailing location phrase of a heading such as ``... en Bello``.

    A listing title ends the location with ``· Cód. N``, so the middle dot is a
    boundary too; without it the code suffix would be glued to the municipality.
    """
    chunks = re.split(r"\ben\s+", str(text or ""), flags=re.IGNORECASE)
    for chunk in reversed(chunks[1:]):
        phrase = _clean_ws(re.split(r"[,|.;·\n]", chunk)[0])
        folded = _fold(phrase)
        if not folded:
            continue
        if folded in _OPERATION_WORDS or folded.startswith(("arriendo", "venta")):
            continue
        return phrase
    return ""


def _segment_mentions_city(segment: str, city: str) -> bool:
    parts = normalize_city(segment).split("-")
    city_parts = city.split("-")
    return len(parts) >= len(city_parts) and parts[-len(city_parts) :] == city_parts


def _barrio_from_text(text: str, city: str) -> str:
    segments = [
        segment.strip()
        for segment in re.split(r"[,|]", str(text or ""))
        if segment.strip()
    ]
    for index, segment in enumerate(segments):
        if _segment_mentions_city(segment, city) and index + 1 < len(segments):
            return normalize_barrio(segments[index + 1])
    return ""


def _number_value(token: str) -> int:
    token = token.strip()
    if not token:
        return 0
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
        return int(re.sub(r"[.,]", "", token))
    if re.fullmatch(r"\d+", token):
        return int(token)
    if re.fullmatch(r"\d+[.,]\d+", token):
        return int(float(token.replace(",", ".")))
    digits = re.sub(r"[.,]", "", token)
    return int(digits) if digits.isdigit() else 0


def _parse_cop(text: str) -> int:
    if not text:
        return 0
    match = re.search(r"(?:COP|\$)\s*([\d.,]+)", text, re.IGNORECASE)
    token = match.group(1) if match else ""
    if not token:
        match = re.search(r"\d+(?:[.,]\d+)*", text)
        token = match.group(0) if match else ""
    return _number_value(token)


def _first_int(text: str, maximum: int) -> int:
    for match in re.finditer(r"\d+(?:[.,]\d+)?", text or ""):
        value = _number_value(match.group(0))
        if 0 <= value <= maximum:
            return value
    return 0


def _first_digits(text: str) -> str:
    match = re.search(r"\d+", text or "")
    return match.group(0) if match else ""


def _parse_detail_page(html: str, expected_code: str | None = None) -> dict | None:
    """Parse one detail page.

    Returns ``None`` for explicit dead pages, sale listings, non-residential
    types and listings whose explicitly stated municipality is outside the
    supported city list.  Raises ``PortalParseError`` when the page is malformed
    or its identity (code, operation, type, municipality) conflicts with the
    sitemap, and when no municipality is stated at all.
    """
    if not html or not str(html).strip():
        raise PortalParseError("empty detail response")

    soup = BeautifulSoup(html, "html.parser")
    for tag in ("script", "style", "noscript", "template", "iframe", "svg"):
        for node in soup.find_all(tag):
            node.decompose()

    if _is_soft_404(soup):
        return None
    if _robots_noindex(soup):
        raise PortalParseError(
            "noindex detail response without explicit unavailable evidence"
        )

    scope = _primary_scope(soup)
    labels = _collect_labels(scope)
    canonical_url = _canonical_href(soup)
    canonical = _parse_detail_slug(canonical_url) if canonical_url else None
    if canonical is None:
        raise PortalParseError("detail page has no canonical /inmueble/ URL")

    h1_text = _clean_text(scope.find("h1")) if scope.find("h1") else ""
    title_text = _listing_title_text(soup)
    location_text = _og_location_text(soup)
    location_city, location_barrio = _location_city_barrio(location_text)

    # The code identity is verified before any operation, type or municipality
    # filter: a response belonging to another property must fail loudly instead
    # of being silently discarded as a sale or out-of-scope listing.
    codigo_text = labels.get("codigo", "")
    if not codigo_text:
        raise PortalParseError("primary SSR code label missing")
    code = _first_digits(codigo_text)
    if not code:
        raise PortalParseError(f"invalid primary SSR code: {codigo_text!r}")
    expected = str(expected_code or "").strip()
    if expected and code != expected:
        raise PortalParseError(f"detail code {code} does not match sitemap {expected}")
    canonical_code = canonical["code"]
    if canonical_code and code != canonical_code:
        raise PortalParseError(
            f"detail code {code} does not match canonical {canonical_code}"
        )
    if expected and canonical_code and expected != canonical_code:
        raise PortalParseError(
            f"sitemap code {expected} does not match canonical {canonical_code}"
        )

    operation = canonical["operacion"]
    h1_operation = _operation_from_text(h1_text)
    if operation and h1_operation and operation != h1_operation:
        raise PortalParseError(
            f"canonical operation {operation!r} conflicts with H1 {h1_operation!r}"
        )
    if operation == "venta":
        return None
    if not operation:
        if h1_operation == "venta":
            return None
        if h1_operation == "arriendo":
            operation = "arriendo"
        else:
            raise PortalParseError("detail operation is neither arriendo nor venta")

    tipo_raw = canonical["tipo"]
    if tipo_raw and _is_explicit_non_residential(tipo_raw):
        return None
    tipo = _residential_tipo(tipo_raw)
    if not tipo:
        tipo = _tipo_from_text(h1_text)
    if not tipo:
        raise PortalParseError(f"unsupported residential type: {tipo_raw!r}")
    h1_tipo = _tipo_from_text(h1_text)
    if h1_tipo and h1_tipo != tipo:
        raise PortalParseError(
            f"detail type conflict: canonical {tipo!r} vs H1 {h1_tipo!r}"
        )

    canonical_city = canonical["municipio"]
    observed_cities = {
        city for city in (_municipality_from_text(h1_text), location_city) if city
    }
    if canonical_city:
        for city in observed_cities:
            if city != canonical_city:
                raise PortalParseError(
                    f"detail municipality conflict: {canonical_city} vs {city}"
                )
        municipality = canonical_city
    elif len(observed_cities) == 1:
        municipality = observed_cities.pop()
    elif len(observed_cities) > 1:
        raise PortalParseError(
            f"detail municipality is ambiguous: {sorted(observed_cities)} "
            f"at {canonical_url}"
        )
    else:
        # No supported municipality is stated and the canonical slug carries no
        # city token this portal supports.  Detail pages whose H1 is the bare
        # "Apartamento en arriendo" heading name their municipality only in the
        # listing title, so that text decides between an explicitly
        # out-of-scope listing and a page that states no location at all.
        phrase = (
            _municipality_phrase(h1_text)
            or _municipality_phrase(location_text)
            or _municipality_phrase(title_text)
        )
        if not phrase:
            raise PortalParseError(
                f"detail municipality is missing at {canonical_url} (code {code})"
            )
        municipality = _known_city(phrase)
        if not municipality:
            # A named but unsupported municipality is out of scope, not a failure.
            return None

    barrio = canonical["barrio"]
    if not barrio and location_city == municipality and location_barrio:
        barrio = location_barrio
    if not barrio:
        barrio = _barrio_from_text(h1_text or location_text, municipality)

    precio_text = labels.get("precio", "")
    if not precio_text:
        raise PortalParseError("primary SSR price label missing")
    precio = _parse_cop(precio_text)
    if precio <= 0:
        raise PortalParseError(f"invalid primary SSR price: {precio_text!r}")

    estrato_text = labels.get("estrato", "")
    estrato_value = _first_int(estrato_text, 9)
    estrato = normalize_estrato(estrato_value if estrato_value else estrato_text)
    if not 1 <= estrato <= 6:
        estrato = 0

    return {
        "id": f"{PREFIX}-{code}",
        "portal": PORTAL,
        "tipo": tipo,
        "precio": precio,
        "area": _first_int(labels.get("area", ""), 10_000),
        "habitaciones": _first_int(labels.get("habitaciones", ""), 30),
        "banos": _first_int(labels.get("banos", ""), 20),
        "parqueaderos": _first_int(labels.get("parqueaderos", ""), 10),
        "estrato": estrato,
        "barrio": normalize_barrio(barrio),
        "url": canonical_url,
        "codigo": code,
        "operacion": operation,
        "municipio": municipality,
    }


def _to_row(detail: dict) -> dict:
    return {field: detail[field] for field in _ROW_FIELDS}


def _validate_max_pages(max_pages) -> None:
    if max_pages is None:
        return
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages <= 0:
        raise ValueError("max_pages must be a positive integer or None")


def _resolve_cities(ciudades) -> list[str]:
    if isinstance(ciudades, str):
        values = [ciudades]
    else:
        try:
            values = list(ciudades)
        except TypeError as error:
            raise ValueError(
                "ciudades must be a city name or an iterable of names"
            ) from error

    resolved: list[str] = []
    for value in values:
        city = resolve_city(value)
        if city not in resolved:
            resolved.append(city)
    return resolved


def _detail_budget(max_pages) -> int | None:
    if max_pages is None:
        return None
    return _DETAIL_BATCH_SIZE * max_pages


def _sample_pools(
    candidates: list[_Candidate], requested: list[str]
) -> tuple[dict[str, deque[_Candidate]], deque[_Candidate]]:
    """Bucket candidates into per-city hint pools plus an unknown/cityless pool."""
    by_city: dict[str, deque[_Candidate]] = {city: deque() for city in requested}
    unknown: deque[_Candidate] = deque()
    for candidate in candidates:
        if candidate.municipio in by_city:
            by_city[candidate.municipio].append(candidate)
        elif not candidate.municipio:
            unknown.append(candidate)
    return by_city, unknown


def _run_sample_details(
    candidates: list[_Candidate],
    requested: list[str],
    max_pages,
    verbose: bool,
) -> dict[str, list[dict]]:
    """Examine a bounded sample, replenishing dead/skipped candidates.

    The initial wave takes three hinted candidates per requested city.  When a
    city is still short after a wave (an explicitly dead detail, a duplicate or
    a canonical municipality mismatch), further candidates are drawn from that
    city's hint pool and the unknown pool until the rows are filled or the
    sample budget is exhausted, so the first few dead entries cannot fake an
    empty city.
    """
    batches = max_pages if max_pages is not None else _SAMPLE_MIN_BATCHES
    budget = _SAMPLE_BATCH_SIZE * batches

    by_city, unknown = _sample_pools(candidates, requested)
    rows: dict[str, list[dict]] = {city: [] for city in requested}
    seen_ids: set[str] = set()
    examined = 0
    skipped = 0

    def take(city: str) -> _Candidate | None:
        if by_city[city]:
            return by_city[city].popleft()
        return unknown.popleft() if unknown else None

    pending: list[_Candidate] = []
    for city in requested:
        for _ in range(_SAMPLE_ROWS_PER_CITY):
            candidate = take(city)
            if candidate is None:
                break
            pending.append(candidate)

    while pending and examined < budget:
        batch = pending[: min(_SAMPLE_BATCH_SIZE, budget - examined)]
        pending = pending[len(batch) :]
        examined += len(batch)
        results = bulk_fetch(
            [candidate.url for candidate in batch], max_workers=_BULK_WORKERS
        )
        if len(results) != len(batch):
            raise PortalFetchError("bulk detail fetch returned an incomplete batch")

        for candidate, (url, html) in zip(batch, results):
            if not html:
                raise PortalFetchError(f"detail fetch failed: {url}")
            detail = _parse_detail_page(html, expected_code=candidate.code or None)
            if detail is None:
                skipped += 1
                continue
            city = detail["municipio"]
            if city not in rows:
                skipped += 1
                continue
            if detail["id"] in seen_ids:
                continue
            if len(rows[city]) >= _SAMPLE_ROWS_PER_CITY:
                continue
            seen_ids.add(detail["id"])
            rows[city].append(_to_row(detail))

        for city in requested:
            shortfall = _SAMPLE_ROWS_PER_CITY - len(rows[city])
            if shortfall <= 0:
                continue
            for _ in range(shortfall):
                candidate = take(city)
                if candidate is None:
                    break
                pending.append(candidate)

    for city in requested:
        if rows[city]:
            continue
        remaining = len(by_city[city]) + sum(
            1
            for candidate in pending
            if candidate.municipio == city or not candidate.municipio
        )
        if remaining:
            logger.warning(
                "AEV sample budget exhausted for %s with %d candidate(s) unexamined; "
                "empty inventory is unproven",
                city,
                remaining,
            )

    if verbose:
        logger.info(
            "AEV sample details: %d examined, %d skipped, %d stored",
            examined,
            skipped,
            sum(len(value) for value in rows.values()),
        )
    return rows


def _run_details(
    candidates: list[_Candidate],
    requested: list[str],
    sample_only: bool,
    max_pages,
    verbose: bool,
) -> dict[str, list[dict]]:
    if sample_only:
        return _run_sample_details(candidates, requested, max_pages, verbose)

    budget = _detail_budget(max_pages)
    selected = candidates if budget is None else candidates[:budget]

    rows: dict[str, list[dict]] = {city: [] for city in requested}
    seen_ids: set[str] = set()
    skipped = 0

    for start in range(0, len(selected), _DETAIL_BATCH_SIZE):
        batch = selected[start : start + _DETAIL_BATCH_SIZE]
        results = bulk_fetch(
            [candidate.url for candidate in batch], max_workers=_BULK_WORKERS
        )
        if len(results) != len(batch):
            raise PortalFetchError("bulk detail fetch returned an incomplete batch")

        for candidate, (url, html) in zip(batch, results):
            if not html:
                raise PortalFetchError(f"detail fetch failed: {url}")
            detail = _parse_detail_page(html, expected_code=candidate.code or None)
            if detail is None:
                skipped += 1
                continue
            city = detail["municipio"]
            if city not in rows:
                skipped += 1
                continue
            if detail["id"] in seen_ids:
                continue
            seen_ids.add(detail["id"])
            rows[city].append(_to_row(detail))

    if verbose:
        logger.info(
            "AEV details: %d examined, %d skipped, %d stored",
            len(selected),
            skipped,
            sum(len(value) for value in rows.values()),
        )
    return rows


def scrape_cities(
    ciudades,
    sample_only: bool = False,
    max_pages=None,
    verbose: bool = False,
) -> dict[str, list[dict]]:
    """Scrape rental listings for the requested canonical cities in one pass.

    Discovery fetches the sitemap once and every detail page once; rows are
    grouped by the municipality stated on the detail page's canonical URL.
    ``max_pages`` bounds detail batches (it is not a complete snapshot for
    multi-page portals).  Sample mode examines at most a bounded budget, stores
    at most three accepted details per requested city and replenishes explicit
    dead/skipped candidates before a city's sample is treated as empty.
    """
    _validate_max_pages(max_pages)
    requested = _resolve_cities(ciudades)
    if not requested:
        return {}

    candidates = _discover_candidates()
    rows = _run_details(candidates, requested, sample_only, max_pages, verbose)
    return {city: rows[city] for city in requested}


def scrape(
    ciudad: str = "medellin",
    sample_only: bool = False,
    max_pages=None,
    verbose: bool = False,
) -> list[dict]:
    """Scrape one canonical city through the shared multi-city engine."""
    city = resolve_city(ciudad)
    return scrape_cities(
        [city], sample_only=sample_only, max_pages=max_pages, verbose=verbose
    )[city]
