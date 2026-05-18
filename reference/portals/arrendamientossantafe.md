# Arrendamientos SantaFe (`ASF`)

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
