# Arrendamientos Villa Cruz (`AVC`)

- **URL**: `https://www.arrendamientosvillacruz.com.co/resultados?gestion=Arriendo&tipo=Apartamentos-y-Apartaestudios-y-Casas-y-Casas+Locales-y-Casas+Fincas`
- **Type**: JS-rendered (Laravel + Livewire)
- **Listing card**: Marked by `COD: NNNN` pattern
- **Listings per load**: ~36 (scroll-based lazy loading)
- **Pagination**: Scroll-based — needs Python API `page_action` for full extraction
- **Key feature**: **Needs scroll automation via Python API**

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `AVC-{code}` | `COD: 8696` |
| `portal` | `arrendamientosvillacruz` | Fixed |
| `tipo` | Line after "Arriendo" | `Apartamento` → `apartamento` |
| `precio` | `$` line | `$ 1.800.000` → `1800000` |
| `area` | Line before `m²` | `70` → `70` |
| `habitaciones` | `N Alcobas` | `3 Alcobas` → `3` |
| `banos` | `N Baños` | `2 Baños` → `2` |
| `parqueaderos` | `N parq.` | `0 parq.` → `0` |
| `estrato` | **Not in card** | → `0` |
| `barrio` | Title after ` - ` | `Casa en Arriendo - BUENOS AIRES` → `BUENOS AIRES` |
| `url` | Fixed search URL | |

**Scraping strategy:**
- MCP `scrapling_fetch` renders initial batch — use for discovery
- Full extraction requires Python API scroll: `StealthyFetcher.fetch()` + `page_action` with `page.mouse.wheel()`
- "También te puede interesar" section has duplicates — deduplicate by `id`

**Dynamic scroll pattern:**
```python
def scroll_to_load_all(page: Page):
    last_count = 0
    while True:
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1500)
        current = page.locator('text=COD:').count()
        if current == last_count:
            page.mouse.wheel(0, 5000)  # one more attempt
            page.wait_for_timeout(2000)
            if page.locator('text=COD:').count() == last_count:
                break  # stops when no new listings load
        last_count = current
```
Never hardcode scroll count — stops when listing count stabilizes.
