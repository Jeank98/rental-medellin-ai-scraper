"""Detail-page field extraction for Proser's two-phase scraper."""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TypeAlias
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from scrape.normalize import normalize_barrio, normalize_estrato, normalize_tipo

logger = logging.getLogger(__name__)
BASE_URL = "https://proserinmobiliaria.com"
PREFIX = "PRO"
Listing: TypeAlias = dict[str, str | int]


def _detail_url(raw: str) -> str:
    """Return an absolute Proser detail URL only when its path ends in a code."""
    url = raw if raw.startswith("http") else f"{BASE_URL}/{raw.lstrip('/')}"
    parsed = urlparse(url)
    code = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if parsed.netloc != urlparse(BASE_URL).netloc or not code.isdecimal():
        return ""
    return url


def _number_fragment(raw: str) -> str:
    """Read the first decimal-like number from a labeled value."""
    fragment: list[str] = []
    started = False
    for char in raw.replace(",", ""):
        if char.isdecimal() or (char == "." and started):
            fragment.append(char)
            started = True
        elif started:
            break
    return "".join(fragment)


def _contract_number(raw: str, field: str) -> int:
    """Apply Proser's documented explicit half-up integer policy."""
    fragment = _number_fragment(raw)
    if not fragment:
        return 0
    if fragment.count(".") > 1:
        fragment = fragment.replace(".", "")
    try:
        value = Decimal(fragment)
    except InvalidOperation:
        return 0
    rounded = value.to_integral_value(rounding=ROUND_HALF_UP)
    if value != rounded:
        logger.warning(
            "Proser %s=%s is fractional; normalized with ROUND_HALF_UP to %s",
            field, fragment, rounded,
        )
    return int(rounded)


def parse_detail_page(html: str, requested_url: str = "") -> Listing:
    """Extract labeled detail fields, including explicit barrio and estrato."""
    soup = BeautifulSoup(html, "html.parser")
    detail: Listing = {
        "id": "", "portal": "proserinmobiliaria", "tipo": "", "precio": 0,
        "area": 0, "habitaciones": 0, "banos": 0, "parqueaderos": 0,
        "estrato": 0, "barrio": "", "url": "",
    }
    canonical = soup.find("meta", attrs={"property": "og:url"})
    detail_url = str(canonical.get("content", "")) if canonical else requested_url
    detail["url"] = _detail_url(detail_url) or requested_url
    for item in soup.find_all("li"):
        text = item.get_text(" ", strip=True)
        if ":" not in text:
            continue
        label, value = (part.strip() for part in text.split(":", 1))
        lowered = label.casefold()
        if lowered in ("código", "codigo") and value.isdecimal():
            detail["id"] = f"{PREFIX}-{value}"
        elif lowered == "zona / barrio":
            detail["barrio"] = normalize_barrio(value)
        elif lowered.startswith(("área", "area")):
            detail["area"] = _contract_number(value, "area")
        elif lowered in ("alcoba", "alcobas"):
            detail["habitaciones"] = _contract_number(value, "habitaciones")
        elif lowered in ("baño", "baños"):
            detail["banos"] = _contract_number(value, "banos")
        elif lowered == "estrato":
            detail["estrato"] = normalize_estrato(value)
        elif lowered == "tipo de inmueble":
            detail["tipo"] = normalize_tipo(value)
    return detail


def merge_detail(row: Listing, detail: Listing) -> bool:
    """Merge a matching detail row without replacing the stable card identity."""
    if not detail.get("id") or detail["id"] != row["id"]:
        logger.warning("Ignoring detail identity mismatch for %s", row["id"])
        return False
    for field in ("tipo", "area", "habitaciones", "banos", "parqueaderos", "estrato", "barrio"):
        value = detail.get(field)
        if isinstance(value, str) and value or isinstance(value, int) and value > 0:
            row[field] = value
    return True
