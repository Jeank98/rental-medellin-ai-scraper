# Portal Field Mappings

Discovered field-to-column mappings for each scraped portal. Extend this file each time a new portal is analyzed.

## Maxibienes (`MXB`)

- **URL**: `https://www.maxibienes.com/resultados-de-la-busqueda-de-inmueble/?gestion=1&ciudad=5001`
- **Type**: Server-rendered PHP
- **Listing card**: `.grid-style1 .item`
- **Listings per page**: 12
- **Total pages**: 73 (870 properties, all tipos — no filter; 2026-05-18)
- **Pagination**: `/pagina/N?query` (no trailing slash before `?`)
- **Pagination values**: discovered dynamically from `var totalInmuebles` and `var totalpagina` in page HTML

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `MXB-{code}` | Code from first `<li>` in `.amenities` |
| `portal` | `maxibienes` | Fixed |
| `tipo` | `<h3>` text before `<br>` | `APARTAMENTO` → `apartamento` |
| `precio` | `.price span` | `$ 1.450.000` → `1450000` |
| `area` | `.amenities li` with `fa-compress` icon | `50 m²` → `50` |
| `habitaciones` | `.amenities li` with `fa-bed` icon | `2` → `2` |
| `banos` | `.amenities li` with `fa-bath` icon | `1` → `1` |
| `parqueaderos` | `.amenities li` with `fa-warehouse` icon | `0` → `0` |
| `estrato` | `<h3>` text | `Estrato: 3` → `3` |
| `barrio` | `.image .location` | `Barrio: Loreto` → `Loreto` |
| `url` | `.image a[href]` | Full absolute URL |

**Notes**:
- All fields available in listing cards
- Icons use FontAwesome classes: `fa-compress` (area), `fa-bath` (bathrooms), `fa-bed` (bedrooms), `fa-warehouse` (parking)
- 6 listings had anomalous parking values: (11, 35, 11, 141, 2611, 1061) — source data errors
- `ARRIENDO/VENTA` listings have `$ $ X / $Y` format — `$ $` prefix, split on `/`, take first for rental
- 69 listings have `estrato=7` (Colombia max is 6) — source data errors
- Property types (2026-05-18): apartamento (415), local (203), apartaestudio (99), casa (84), oficina (50), bodega (17), lote (1), finca (1)

## Arrendamientos SantaFe (`ASF`)

- **URL**: `https://arrendamientossantafe.com/propiedades/?bussines_type=Arrendar`
- **Type**: Server-rendered (Django or similar)
- **Listing card**: `.property-card`
- **Listings per page**: 12
- **Total pages**: 94 (1,128 properties; 2026-05-18)
- **Pagination**: `?page=N&bussines_type=Arrendar`
- **Pagination discovery**: binary search with stale-card detection — pages beyond 94 serve placeholder listing (REF: A9692)

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `ASF-{code}` | `span.id` → `REF: A11248` |
| `portal` | `arrendamientossantafe` | Fixed |
| `tipo` | `p.tipo-inmueble` | `Tipo: Apartamento` → `apartamento` |
| `precio` | `div.precio p` | `$1,600,000` → `1600000` |
| `area` | `span.area` | `55m²` → `55` |
| `habitaciones` | `span.alcobas` (bed icon) | `2` → `2` |
| `banos` | **Not in card** | → `0` |
| `parqueaderos` | `span.garaje` (car icon) | `0` → `0` |
| `estrato` | **Not in card** | → `0` |
| `barrio` | `.sector p.d-inline` | `Ubicación: Cristo Rey` → `Cristo Rey` |
| `url` | `.inner-card a[href]` | `/propiedad/A11248/` → prepend domain |

**Notes**:
- No bathrooms (baños) in listing cards
- No estrato in listing cards (exists as filter but not per-property)
- Icons are PNG images: `bed-icon-xs.png` (bedrooms), `car-icon-xs.png` (parking), `location-icon-xs.png` (location)
- Property types (2026-05-18): apartamento (455), local (286), casa (137), apartaestudio (121), oficina (68), finca (41), bodega (20)
- 83 unique neighborhoods
- `ApartaEstudio` needs normalization to `apartaestudio`
- URL is relative → must prepend `https://arrendamientossantafe.com`
- Page 95+ serves stale placeholder listing (REF: A9692) — binary search with code-comparison detects the true last page
- Field detection works via CSS class names (`.alcobas`, `.garaje`, `.area`, `.id`, `.tipo-inmueble`, `.sector`) but adaptive extractor handles these generically

---

## Template — New Portal

When discovering a new portal, fill this template:

```markdown
## {Portal Name} (`{PREFIX}`)

- **URL**: {search_results_url}
- **Type**: {server-rendered | JS-rendered | hybrid}
- **Listing card**: {css_selector}
- **Listings per page**: {N}
- **Total pages**: {N}
- **Pagination**: {url_pattern}

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | {source} | {pattern} |
| `portal` | {portal_name} | Fixed |
| `tipo` | {source} | {pattern} |
| `precio` | {source} | {pattern} |
| `area` | {source} | {pattern} |
| `habitaciones` | {source} | {pattern} |
| `banos` | {source} | {pattern} |
| `parqueaderos` | {source} | {pattern} |
| `estrato` | {source} | {pattern} |
| `barrio` | {source} | {pattern} |
| `url` | {source} | {pattern} |

**Notes**:
- {observations, quirks, gotchas}
```
