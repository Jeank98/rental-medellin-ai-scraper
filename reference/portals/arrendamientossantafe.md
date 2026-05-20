# Arrendamientos SantaFe (`ASF`)

- **URL**: `https://arrendamientossantafe.com/propiedades/?bussines_type=Arrendar`
- **Type**: Server-rendered (Django or similar)
- **Listing card**: `.property-card`
- **Detail page**: `/propiedad/{CODE}/` — server-rendered, no JS required
- **Listings per page**: 12
- **Total pages**: Discovered via `?page=9999` trick — server redirects to last real page (94). Pagination element `.current` shows the number.
- **Pagination**: `?page=N&bussines_type=Arrendar`
- **Pagination discovery**: Request page=9999, extract last page number from `.current` element. Then parallel `bulk_fetch` all pages with 20 workers.
- **Key feature**: **Card fields incomplete — requires two-phase scrape** (verified 2026-05-19)

### Phase A — Listing cards (search pages)

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `ASF-{code}` | `span.id` → `REF: A11248` |
| `portal` | `arrendamientossantafe` | Fixed |
| `tipo` | `p.tipo-inmueble` | `Tipo: Apartamento` → `apartamento` |
| `precio` | `div.precio p` | `$1,600,000` → `1600000` |
| `area` | `span.area` | `55m²` → `55` |
| `habitaciones` | `span.alcobas` (bed icon) | `2` → `2` |
| `parqueaderos` | `span.garaje` (car icon) | `0` → `0` |
| `barrio` | `.sector p.d-inline` | `Ubicación: Cristo Rey` → `Cristo Rey` |
| `url` | `.inner-card a[href]` | `/propiedad/A11248/` → prepend domain |

### Phase B — Detail pages (`scrapling_bulk_get`)

Each card's `url` points to a server-rendered detail page. Use `scrapling_bulk_get` in parallel (no JS/Playwright needed). Extract ONLY these missing fields:

| Column | Source | Pattern |
|--------|--------|---------|
| `banos` | `Baños:` in Características section | `2` → `2` |
| `estrato` | `Estrato:` in Interior section | `4` → `4` |

Detail page field locations:
- **Características section** (`div.titulo-box-caracteristicas`): `Habitaciones`, `Baños`, `Garaje`, etc. — label on one line, value on next
- **Interior section** (`div.titulo-box-caracteristicas` followed by detail rows): `Estrato:`, `Sector:`, `Referencia:`, etc.
- Do NOT re-extract fields already available from cards (tipo, precio, area, habitaciones, parqueaderos, barrio)
- If a field is absent from the detail page → keep card value (0 for numeric, "" for string)

### Two-phase workflow

1. **Phase A**: Scrape all search result pages — get 9 fields from cards + detail page URL
2. **Phase B**: `scrapling_bulk_get` all detail page URLs → extract `banos` and `estrato` from each
3. **Merge**: Update banos and estrato from phase B results into phase A listings
4. Output CSV or insert to DB with all 11 columns populated

**Notes**:
- Cards have 4 detail spans: `span.id`, `span.alcobas`, `span.garaje`, `span.area` — no bathrooms or estrato
- Detail pages are server-rendered HTML — fast parallel fetch with `scrapling_bulk_get`
- Icons are PNG images: `bed-icon-xs.png` (bedrooms), `car-icon-xs.png` (parking), `location-icon-xs.png` (location)
- Property types (2026-05-18): apartamento (455), local (286), casa (137), apartaestudio (121), oficina (68), finca (41), bodega (20)
- 83 unique neighborhoods
- `ApartaEstudio` needs normalization to `apartaestudio`
- URL is relative → must prepend `https://arrendamientossantafe.com`
- Page 95+ serves stale placeholder listing (REF: A9692) — binary search with code-comparison detects the true last page
