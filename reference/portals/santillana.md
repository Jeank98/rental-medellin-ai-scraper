# Santillana (`STL`)

- **URL**: `https://santillanasas.com/search?simple=1-2-496&business_type%5B0%5D=for_rent&id_country=1&id_region=2&id_city=496&order_by=created_at&order=desc&for_sale=0&for_rent=1&for_temporary_rent=0&for_transfer=0&lax_business_type=1`
- **Type**: Server-rendered (Django-like)
- **Listing card**: `div.item`
- **Listings per page**: 12
- **Total pages**: 6 (72 properties; 2026-05-18)
- **Pagination**: `/search?&page=N` (must use search endpoint, `/s/alquiler/.../page/N/` doesn't paginate)
- **Key feature**: **Card fields incomplete — requires two-phase scrape**

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `STL-{code}` | Code from URL last path segment (card) or `Código:` field (detail) |
| `portal` | `santillana` | Fixed |
| `tipo` | `.body p` with `Tipo:` (card) or `Tipo de inmueble:` (detail) | `APARTAMENTO` → `apartamento` |
| `precio` | `.areaPrecio span` (card) or `[class*="precio"]` (detail) | `$2.500.000` → `2500000` |
| `area` | **Detail only** — `Área Construida:` in `ul.list-li li` | `50 m²` → `50` |
| `habitaciones` | **Detail only** — `Alcobas:` in `ul.list-li li` | `3` → `3` (absent → 0) |
| `banos` | **Detail only** — `Baño:` / `Baños:` in `ul.list-li li` | `1` → `1` (absent → 0) |
| `parqueaderos` | **Detail only** — `Garaje:` in `ul.list-li li` | `1` → `1` (only when > 0 → 0) |
| `estrato` | **Detail only** — `Estrato:` in `ul.list-li li` | `3` → `3` (non-numeric "Comercial" → 0) |
| `barrio` | **Detail only** — `Zona / barrio:` in `ul.list-li li` | `Robledo` → `Robledo` (absent → "") |
| `url` | `div.title h2 a[href]` (card) | Already absolute |

**Notes**:
- **TWO-PHASE STRATEGY**: Cards have id, portal, tipo, precio, url. Everything else from individual detail pages
- Detail fields are CONDITIONAL in `ul.list-li li` — absent means 0/""
- `Estrato` can be "Comercial" (non-numeric) → convert to 0
- Barrio absent for metro-area properties (Itagüí, Sabaneta, Envigado, Bello)
- Listing card `.ubicacion` always shows "Colombia" — useless
- Uses `scrapling.find_all("div.item")` for cards and `scrapling.find_all("ul.list-li li")` for details
- 72 listings across 7 property types: apartamento (31), casa (18), local (10), apartaestudio (10), bodega (1), oficina (1), lote (1)
