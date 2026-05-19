# Coninsa (`CON`)

- **URL**: `https://www.coninsa.co/arrendamientos/vivienda/?text=Medellin`
- **Type**: JS-rendered SPA (Gatsby + Drupal)
- **Listing card**: No CSS selector — listings load via client-side JS
- **Listings per page**: 12 (infinite scroll via "Cargar más" button)
- **Total pages**: Infinite scroll — "Cargar más inmuebles" button, ~14 clicks to exhaust
- **Pagination**: "Cargar más inmuebles" button — React state update, no URL parameter
- **Key feature**: **Needs Python API fallback for click automation** (MCP doesn't expose `page_action`)

## Scraping Strategy

**MCP alone insufficient** — `scrapling_fetch` renders initial 12 listings but can't click "Cargar más".

**Required approach:**
1. Use Python API `StealthyFetcher.fetch()` with `page_action` callback
2. In `page_action`, click "Cargar más inmuebles" repeatedly until button disappears
3. Extract all rendered text

```python
from scrapling import StealthyFetcher
from playwright.sync_api import Page

def click_load_more(page: Page):
    last = page.locator('text=Código:').count()
    while True:
        btn = page.locator('text=Cargar más inmuebles')
        if btn.count() == 0 or not btn.first.is_visible():
            break  # button gone
        btn.first.click()
        page.wait_for_timeout(2000)
        current = page.locator('text=Código:').count()
        if current == last: break  # count stabilized — no new listings
        last = current

resp = StealthyFetcher.fetch(url, page_action=click_load_more, headless=True)
text = resp.get_all_text()
```
Stops when button disappears OR listing count stops growing. Never hardcodes a click limit.

**Why Python API:** Scrapling's MCP server does not expose `page_action`. For portals requiring button clicks, use the Python API directly. This is the documented fallback when MCP tool limitations are hit.

## Field Mappings

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `CON-{code}` | `Código: 60565` in text |
| `portal` | `coninsa` | Fixed |
| `tipo` | Title line before `en arriendo` | `Apartamento` → `apartamento` |
| `precio` | `$` line | `$5.400.000` → `5400000` |
| `area` | `m²` line | `133 m²` → `133` |
| `habitaciones` | Numeric line before code (pos 0) | Reversed order: ba, hab, pq |
| `banos` | Numeric line before code (pos 1) | |
| `parqueaderos` | Numeric line before code (pos 2) | |
| `estrato` | **Not in listing** | → `0` |
| `barrio` | Last segment of title after commas | `EL POBLADO` → `El Poblado` |
| `url` | Constructed from code | `https://www.coninsa.co/arrendamientos/vivienda/inmueble/{code}/` |

**Notes**:
- Full scrape requires browser + click automation (repeated clicks on "Cargar más")
- `scrapling_fetch` (MCP browser) renders initial batch — use for discovery only
- Property types: apartamento, casa, finca
- Listings span multiple cities — filter by barrio for Medellín-specific
