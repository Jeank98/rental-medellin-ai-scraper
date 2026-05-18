"""Adaptive field extractor — no hardcoded selectors.

Works with Scrapling card objects. Uses strategies from docs/variable-detection.md
for each field: icon detection, keyword proximity, pattern matching.

Usage:
    from adaptive_extractor import extract_card
    listing = extract_card(card, portal, prefix)
"""

import re
from typing import Optional


def _text(el) -> str:
    """Get clean text from a Scrapling element."""
    try:
        return el.get_all_text() if el else ""
    except Exception:
        return ""


def _html(el) -> str:
    """Get raw HTML from a Scrapling element."""
    try:
        return el.html_content if el else ""
    except Exception:
        return ""


def _number_in_text(text: str) -> Optional[int]:
    """Extract first integer from text."""
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


def _find_labeled_number(card, keywords: list[str]) -> Optional[int]:
    """Find a number near any of the given keyword labels.

    Scans card HTML for patterns like:
      <span class="KEYWORD">N</span>
      <div>KEYWORD: N</div>
      <img src="KEYWORD-icon...">N
      <i class="fa-ICON"></i> N
    """
    html = _html(card)
    text = _text(card)

    # Strategy 1: CSS class contains keyword → get text number
    # Deduplicate case variants before running CSS queries
    seen = set()
    for kw in keywords:
        k = kw.lower()
        if k in seen:
            continue
        seen.add(k)
        els = card.find_all(f"[class*='{k}']")
        for el in els:
            num = _number_in_text(_text(el))
            if num is not None and 0 <= num <= 50:
                return num

    # Strategy 2: Icon + adjacent number — find icon in HTML, extract nearest number.
    # Common patterns:
    #   Maxibienes: <li><i class="fa fa-bed"></i> 2</li>
    #   SantaFe:    <span class="alcobas"><img src="bed-icon">0</span>
    icon_patterns = {
        "bed": r"fa[\s-]bed|bed[\s_-]icon|bed\.svg|bed\.png|bedroom",
        "bath": r"fa[\s-]bath|bath[\s_-]icon|bath\.svg|bath\.png|shower|toilet",
        "car": r"fa[\s-]car|fa[\s-]warehouse|car[\s_-]icon|car\.svg|car\.png|garage[\s_-]icon",
        "area": r"fa[\s-]compress|fa[\s-]arrows|area[\s_-]icon|compress",
    }

    icon_kw_map = {
        "bed": ["bed", "alcoba", "habitacion", "dormitorio", "cuarto"],
        "bath": ["bath", "bano", "baño", "wc", "toilet"],
        "car": ["car", "garage", "garaje", "parqueadero", "parking", "warehouse", "parq"],
        "area": ["area", "compress", "superficie", "metros"],
    }

    for icon_type, pattern in icon_patterns.items():
        for kw in icon_kw_map.get(icon_type, []):
            if kw in keywords:
                # Find an element containing the icon (i, img, span), then grab
                # the nearest number from the parent element's full text
                m = re.search(
                    rf'<(?:i|img|span)[^>]*({pattern})[^>]*>.*?(\d+)',
                    html, re.IGNORECASE | re.DOTALL
                )
                if m:
                    num = int(m.group(2))
                    if 0 <= num <= 50:
                        return num

    # Strategy 3: Keyword in text near a number
    for kw in keywords:
        m = re.search(rf"{kw}[:\s]*(\d+)", text, re.IGNORECASE)
        if m:
            num = int(m.group(1))
            if 0 <= num <= 50:
                return num

    return None


def extract_precio(card) -> int:
    """Extract price — currency pattern, keyword proximity."""
    html = _html(card)
    text = _text(card)

    # Strategy 1: Look for price-related class
    for cls in ["price", "precio", "canon", "valor", "rent", "alquiler"]:
        els = card.find_all(f"[class*='{cls}']")
        for el in els:
            price_text = _text(el)
            # Handle ARRIENDO/VENTA dual prices
            if "/" in price_text and any(kw in price_text.upper() for kw in ["ARRIENDO", "VENTA"]):
                price_text = price_text.split("/")[0]
            clean = re.sub(r"[^\d]", "", price_text)
            if clean:
                return int(clean)

    # Strategy 2: Find $ + number in full text
    for line in text.split("\n"):
        line = line.strip()
        if "$" in line or "COP" in line.upper():
            if "/" in line:
                line = line.split("/")[0]
            clean = re.sub(r"[^\d]", "", line)
            if clean and len(clean) >= 5:  # at least tens of thousands
                return int(clean)

    # Strategy 3: Largest number near a $ symbol in the text
    # Find lines with $ and extract the largest number from each
    candidates = []
    for line in text.split("\n"):
        if "$" in line:
            clean = re.sub(r"[^\d]", "", line)
            if clean and len(clean) >= 5:
                candidates.append(int(clean))
    if candidates:
        return max(candidates)

    return 0


def extract_area(card) -> int:
    """Extract area — Scrapling-based: find elements near 'Área' or 'area' labels + unit pattern."""
    text = _text(card)
    html = _html(card)

    # Strategy 1: Find element containing 'Área' or 'area' label, get sibling number
    for label in ['Área', 'Area', 'área', 'area']:
        # Find any element whose all-text contains the label exactly
        for el in card.find_all("*"):
            t = _text(el).strip()
            if label in t and len(t) < 30:
                # Check siblings or parent for number + m2
                parent = el.parent if hasattr(el, 'parent') else None
                if parent:
                    ptext = _text(parent)
                    m = re.search(r'(\d+)\s*m\s*2', ptext, re.IGNORECASE)
                    if m:
                        return int(m.group(1))
                    m = re.search(r'(\d+)\s*m[²2]', ptext, re.IGNORECASE)
                    if m:
                        return int(m.group(1))

    # Strategy 2: Direct unit pattern in text  
    m = re.search(r'(\d+)\s*m[²2]', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*m\s*2', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*m\s*<sup>2</sup>', html, re.IGNORECASE)
    if m:
        return int(m.group(1))

    return 0


def extract_habitaciones(card) -> int:
    """Extract bedrooms — icon, class name, keyword."""
    num = _find_labeled_number(card, [
        "alcoba", "alcobas", "habitacion", "habitaciones",
        "dormitorio", "dormitorios", "bedroom", "bedrooms",
        "cuarto", "cuartos", "bed", "hab", "dorm"
    ])
    return num if num is not None else 0


def extract_banos(card) -> int:
    """Extract bathrooms — icon, class name, keyword."""
    num = _find_labeled_number(card, [
        "bano", "baño", "banos", "baños",
        "bath", "bathroom", "bathrooms", "wc", "toilet", "shower"
    ])
    return num if num is not None else 0


def extract_parqueaderos(card) -> int:
    """Extract parking — icon, class name, keyword."""
    num = _find_labeled_number(card, [
        "garaje", "garajes", "parqueadero", "parqueaderos",
        "parking", "garage", "parq", "car", "estacionamiento",
        "warehouse"
    ])
    return num if num is not None else 0


def extract_tipo(card) -> str:
    """Extract property type — heading, label, normalize."""
    text = _text(card)
    html = _html(card)

    # Strategy 1: Heading element (h2, h3, h4)
    for tag in ["h2", "h3", "h4"]:
        el = card.find(tag)
        if el:
            tipo_text = _text(el).strip().split("\n")[0].lower()
            if tipo_text:
                return _normalize_tipo(tipo_text)

    # Strategy 2: 'Tipo:' label
    m = re.search(r"Tipo:\s*(\S+)", text, re.IGNORECASE)
    if m:
        return _normalize_tipo(m.group(1).lower())

    # Strategy 3: Element with class containing 'tipo', 'type', 'title'
    for cls in ["tipo", "type", "title", "heading"]:
        els = card.find_all(f"[class*='{cls}']")
        for el in els:
            t = _text(el).strip().lower()
            if t and len(t) < 30:
                return _normalize_tipo(t)

    return ""


def extract_barrio(card) -> str:
    """Extract neighborhood — label, location icon, or parsed from title."""
    text = _text(card)
    html = _html(card)

    # Strategy 0: Parse barrio from heading "TIPO en BARRIO" pattern
    for tag in ["h2", "h3", "h4"]:
        el = card.find(tag)
        if el:
            htext = _text(el).strip()
            m = re.search(r'(?:Apartaestudio|Apartamento|Casa|Oficina|Local|Bodega|Finca|Lote)\s+(?:en\s+|es\s+)?(.+)', htext, re.IGNORECASE)
            if m:
                barrio = m.group(1).strip()
                if barrio and len(barrio) < 80:
                    return barrio

    # Strategy 1: Label patterns
    for label in ["Ubicación:", "Ubicacion:", "Ubicado en:", "Barrio:", "Zona:", "Sector:", "Location:", "Neighborhood:"]:
        m = re.search(rf"{re.escape(label)}\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val and not any(kw in val.lower() for kw in ["$", "cop", "tipo", "estrato"]):
                return val

    # Strategy 2: Element with class containing location keywords
    for cls in ["ubicacion", "barrio", "sector", "location", "zona", "neighborhood", "address"]:
        els = card.find_all(f"[class*='{cls}']")
        for el in els:
            el_text = _text(el).strip()
            # Remove label prefix
            for prefix in ["Ubicación:", "Ubicacion:", "Barrio:", "Zona:", "Sector:"]:
                el_text = re.sub(rf"^{re.escape(prefix)}\s*", "", el_text, flags=re.IGNORECASE)
            if el_text and len(el_text) < 80:
                return el_text.strip()

    # Strategy 3: After location pin icon
    m = re.search(r'location-icon[^>]*>\s*(?:</[^>]+>\s*)*<p[^>]*>\s*(.+?)\s*</p>', html, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        val = re.sub(r"^Ubicación:\s*", "", val, flags=re.IGNORECASE)
        if val:
            return val

    return ""


def extract_estrato(card) -> int:
    """Extract socioeconomic level — Colombia-specific, keyword + number 1-6."""
    html = _html(card)
    text = _text(card)

    m = re.search(r"Estrato:\s*(\d)", html, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 6:
            return val

    m = re.search(r"Estrato\s*(\d)", text, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 6:
            return val

    return 0


def extract_url(card, domain: str = "") -> str:
    """Extract property detail URL — prefer .image a, fall back to first anchor."""
    # Try the link that wraps the card image (most likely the detail page)
    for selector in [".image a", "a"]:
        link = card.find(selector)
        if link:
            href = link.attrib.get("href", "")
            if href.startswith("/"):
                return domain.rstrip("/") + href
            if href.startswith("http"):
                return href
            # If selector is specific (.image a) and href is junk, fall through
            if selector != "a":
                continue
    return ""


def extract_id(card, prefix: str) -> str:
    """Extract property code — label, URL path, data attribute."""
    text = _text(card)
    html = _html(card)

    # Strategy 1: Label patterns
    for label in ["REF:", "Código:", "Code:", "ID:", "#", "Cod:", "Cód:"]:
        m = re.search(rf"{re.escape(label)}\s*(\S+)", text)
        if m:
            code = m.group(1)
            code = re.sub(r"[^\w\-]", "", code)
            if code:
                return f"{prefix}-{code}"

    # Strategy 2: From URL path
    url = extract_url(card)
    if url:
        # /propiedad/A11636/, /codigo/69007, /inmueble/abc-123
        m = re.search(r"/(?:propiedad|codigo|inmueble|property|code)/([^/\?]+)", url)
        if m:
            code = m.group(1)
            code = re.sub(r"[^\w\-]", "", code)
            if code:
                return f"{prefix}-{code}"

    # Strategy 3: Data attributes
    for attr in ["data-id", "data-code", "data-property-id", "data-ref"]:
        m = re.search(rf'{attr}=["\']?([^"\'\s>]+)', html, re.IGNORECASE)
        if m:
            return f"{prefix}-{m.group(1)}"

    # Strategy 4: First <li> in amenities-style list (common pattern)
    first_li = card.find("li")
    if first_li:
        num = _number_in_text(_text(first_li))
        if num and not re.search(r"m[²2]", _html(first_li), re.IGNORECASE):
            return f"{prefix}-{num}"

    return ""


TYPE_MAP = {
    "apartamento": "apartamento", "apto": "apartamento", "apartment": "apartamento",
    "departamento": "apartamento", "department": "apartamento",
    "casa": "casa", "house": "casa",
    "apartaestudio": "apartaestudio", "studio": "apartaestudio",
    "local": "local", "comercial": "local", "commercial": "local",
    "oficina": "oficina", "office": "oficina",
    "bodega": "bodega", "warehouse": "bodega",
    "lote": "lote", "lot": "lote", "terreno": "lote",
    "finca": "finca", "farm": "finca", "hacienda": "finca",
}


def _normalize_tipo(raw: str) -> str:
    raw = raw.strip().lower()
    # Direct match
    if raw in TYPE_MAP:
        return TYPE_MAP[raw]
    # Partial match
    for key, val in TYPE_MAP.items():
        if key in raw:
            return val
    return raw


def extract_card(card, portal: str, prefix: str) -> dict:
    """Extract all 11 fields from a Scrapling card element.

    Args:
        card: Scrapling Selector element (from resp.find_all)
        portal: portal name (e.g. 'maxibienes')
        prefix: portal prefix (e.g. 'MXB')

    Returns dict with all 11 standard columns.
    """
    domain = ""
    # Derive domain from the first link in the card
    link = card.find("a")
    if link:
        href = link.attrib.get("href", "")
        if href.startswith("http"):
            from urllib.parse import urlparse
            parsed = urlparse(href)
            domain = f"{parsed.scheme}://{parsed.netloc}"

    return {
        "id": extract_id(card, prefix),
        "portal": portal,
        "tipo": extract_tipo(card),
        "precio": extract_precio(card),
        "area": extract_area(card),
        "habitaciones": extract_habitaciones(card),
        "banos": extract_banos(card),
        "parqueaderos": extract_parqueaderos(card),
        "estrato": extract_estrato(card),
        "barrio": extract_barrio(card),
        "url": extract_url(card, domain),
    }
