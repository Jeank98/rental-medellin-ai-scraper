"""DOM and Livewire parsing helpers for Arrendamientos El Castillo."""

from typing import Final, TypedDict

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page

from scrape.normalize import (
    normalize_barrio,
    normalize_estrato,
    normalize_price,
    normalize_tipo,
    normalize_url,
)

_BASE_URL: Final = "https://www.arrendamientoselcastillo.com.co"
_DETAIL_MARKER: Final = "/detalle-propiedad/"
_PORTAL: Final = "arrendamientoselcastillo"
_PREFIX: Final = "AEC"
_TYPE_NAMES: Final = {
    "apartamento",
    "casa",
    "apartaestudio",
    "local",
    "oficina",
    "bodega",
    "lote",
    "finca",
}


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


def _empty_listing(code: str, url: str) -> Listing:
    """Create a row with the repository's numeric zero defaults."""
    return {
        "id": f"{_PREFIX}-{code}",
        "portal": _PORTAL,
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


def _digits(raw: str) -> int:
    """Return the decimal digits in a source value as an integer."""
    value = "".join(character for character in raw if character.isdecimal())
    return int(value) if value else 0


def _lines(element: Tag) -> list[str]:
    """Return non-empty rendered text lines from a DOM element."""
    return [
        line.strip() for line in element.get_text("\n").splitlines() if line.strip()
    ]


def _detail_links(element: Tag) -> list[str]:
    """Return unique absolute detail links contained by an element."""
    links: list[str] = []
    for anchor in element.find_all("a", href=True):
        href = normalize_url(str(anchor.get("href", "")), _BASE_URL)
        if _DETAIL_MARKER in href and href not in links:
            links.append(href)
    return links


def _code_from_lines(lines: list[str]) -> str:
    """Read the numeric code from a visible COD/Código label."""
    for line in lines:
        lower = line.lower()
        if lower.startswith(("cod:", "código:", "codigo:")):
            value = line.split(":", 1)[1].strip()
            for token in value.split():
                if token.isdecimal():
                    return token
    return ""


def _price_from_card(card: Tag) -> int:
    """Choose the current visible price, excluding struck-through values."""
    candidates: list[int] = []
    for element in card.find_all():
        text = element.get_text(" ", strip=True)
        if "$" not in text:
            continue
        if any("$" in child.get_text(" ", strip=True) for child in element.find_all()):
            continue
        parent = element
        old_price = False
        while isinstance(parent, Tag):
            if parent.name in {"del", "s", "strike"}:
                old_price = True
                break
            parent = parent.parent
        if not old_price:
            candidates.append(normalize_price(text))
    return next((price for price in candidates if price), 0)


def _number_for_label(lines: list[str], labels: tuple[str, ...]) -> int:
    """Extract the number from a line containing one of the source labels."""
    for line in lines:
        lower = line.lower()
        for label in labels:
            if label in lower:
                label_start = lower.index(label)
                value = line[label_start + len(label) :]
                number = _digits(value)
                if not number and line[:label_start].strip():
                    number = _digits(line[:label_start])
                if number or "0" in value:
                    return number
    return 0


def _area_from_lines(lines: list[str]) -> int:
    """Read the number immediately before the square-metre unit."""
    for index, line in enumerate(lines):
        lower = line.lower()
        for unit in ("m²", "m2", "mt2"):
            if lower == unit and index:
                return _digits(lines[index - 1])
            if unit in lower:
                return _digits(line[: lower.index(unit)])
    return 0


def _type_from_lines(lines: list[str]) -> str:
    """Normalize the standalone property type line in a card."""
    for line in lines:
        normalized = normalize_tipo(line)
        if normalized in _TYPE_NAMES:
            return normalized
    return ""


def _barrio_from_lines(lines: list[str]) -> str:
    """Read the neighborhood from the card title after its final dash."""
    for line in lines:
        if " - " in line and "arriendo" in line.lower():
            return normalize_barrio(line.rsplit(" - ", 1)[-1])
    return ""


def _card_candidates(soup: BeautifulSoup) -> list[Tag]:
    """Find card-sized elements without relying on portal CSS class names."""
    candidates: dict[str, tuple[int, int, int, Tag]] = {}
    for position, element in enumerate(soup.find_all()):
        links = _detail_links(element)
        if len(links) != 1:
            continue
        lines = _lines(element)
        code = _code_from_lines(lines)
        if not code:
            continue
        text = " ".join(lines).lower()
        score = sum(
            token in text for token in ("arriendo", "m²", "alcobas", "baños", "parq")
        )
        if score < 3:
            continue
        current = candidates.get(code)
        candidate = (score, len(text), position, element)
        if current is None or candidate[:2] > current[:2]:
            candidates[code] = candidate
    return [
        candidate[3]
        for candidate in sorted(candidates.values(), key=lambda item: item[2])
    ]


def _parse_card(card: Tag) -> Listing | None:
    """Parse one search card into the canonical row shape."""
    lines = _lines(card)
    code = _code_from_lines(lines)
    links = _detail_links(card)
    if not code or not links:
        return None

    listing = _empty_listing(code, links[0])
    listing["tipo"] = _type_from_lines(lines)
    listing["precio"] = _price_from_card(card)
    listing["area"] = _area_from_lines(lines)
    listing["habitaciones"] = _number_for_label(lines, ("alcobas", "alcoba"))
    listing["banos"] = _number_for_label(lines, ("baños", "baño", "banos"))
    listing["parqueaderos"] = _number_for_label(
        lines, ("parq.", "parq", "parqueaderos")
    )
    listing["barrio"] = _barrio_from_lines(lines)
    return listing if listing["precio"] and listing["tipo"] else None


def parse_search_html(html: str) -> list[Listing]:
    """Parse all unique valid cards from a fully rendered search page."""
    soup = BeautifulSoup(html, "html.parser")
    listings: list[Listing] = []
    seen_ids: set[str] = set()
    for card in _card_candidates(soup):
        listing = _parse_card(card)
        if listing is None or listing["id"] in seen_ids:
            continue
        seen_ids.add(listing["id"])
        listings.append(listing)
    return listings


def parse_detail_estrato(html: str) -> int:
    """Extract the labeled Estrato value; a missing label is a genuine zero."""
    soup = BeautifulSoup(html, "html.parser")
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    for index, line in enumerate(lines):
        lower = line.lower()
        if not lower.startswith("estrato"):
            continue
        value = line.split(":", 1)[1].strip() if ":" in line else ""
        number = _digits(value)
        if number:
            return normalize_estrato(number)
        if index + 1 < len(lines):
            return normalize_estrato(_digits(lines[index + 1]))
    return 0


def _codes_from_text(text: str) -> set[str]:
    """Collect visible COD values used by the Livewire stop condition."""
    return {
        code
        for code in (_code_from_lines([line.strip()]) for line in text.splitlines())
        if code
    }


def scroll_to_load_all(page: Page, max_batches: int | None = None) -> None:
    """Scroll until Livewire produces no new COD values."""
    previous = _codes_from_text(page.locator("body").inner_text())
    batches = 0
    while max_batches is None or batches < max_batches:
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(3000)
        current = _codes_from_text(page.locator("body").inner_text())
        batches += 1
        if current == previous:
            break
        previous = current
