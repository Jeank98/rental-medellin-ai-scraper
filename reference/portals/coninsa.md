# Coninsa (`CON`)

- **URL**: `https://www.coninsa.co/arrendamientos/vivienda/?text=Medellin`
- **Type**: JS-rendered SPA (Gatsby + Drupal)
- **Listing card**: No CSS selector — listings load via client-side JS
- **Listings per page**: 12 (infinite scroll via "Cargar más" button)
- **Total pages**: 14 loads (161 listings; 2026-05-18)
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
    while True:
        btn = page.locator('text=Cargar más inmuebles')
        if btn.count() == 0 or not btn.first.is_visible():
            break
        btn.first.click()
        page.wait_for_timeout(2000)

resp = StealthyFetcher.fetch(url, page_action=click_load_more, headless=True)
text = resp.get_all_text()
```

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
| `url` | Fixed search URL | `https://www.coninsa.co/arrendamientos/vivienda/?text=Medellin` |

**Notes**:
- Full scrape requires browser + click automation (14 clicks for Medellín)
- `scrapling_fetch` (MCP browser) renders initial 12 — use for discovery only
- 161 listings extracted (7 missed in boundary parsing)
- Property types: apartamento, casa, finca
- Listings span multiple cities — filter by barrio for Medellín-specific
