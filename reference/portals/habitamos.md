# Habitamos (`HBM`)

- **URL**: `https://habitamos.com.co/api/propiedades/buscar?comercio=arriendo&pagina={N}&por_pagina=12&municipio={MUNICIPIO}`
- **Type**: REST JSON (one phase, no detail pages)
- **Listings per page**: 12 — the API caps `por_pagina` at 12 and ignores larger values
- **Total pages**: `total_paginas` on every response (`total` carries the grand total)
- **Pagination**: `pagina` query parameter, 1-based
- **Traps**:
  - The body is wrapped as `<html><body>{…json…}</body></html>`; unwrap before `json.loads`.
  - `municipio` filters on the accented label the API prints (`Medellín`, `Itagüí`, `La Estrella`).
  - The public listing page is now a client-side shell: `/propiedades?comercio=arriendo` answers 200 with no cards, and the legacy `en.habitamos.com.co` host answers 403. The API above is the only reachable source.

| Column | Source | Notes |
|--------|--------|-------|
| `id` | `HBM-{codigo}` | `codigo` in the record |
| `portal` | `habitamos` | Fixed |
| `tipo` | `tipo` | `Apartamento` / `Casa` / `Apartaestudio`; Local, Bodega, Oficina and Lote are skipped |
| `precio` | `precio_arriendo` | `precio_venta` ignored; 0 or out-of-range drops the record |
| `area` | `area_numero` (fallback `area`) | Always published |
| `habitaciones` | `alcobas` | 0 if absent |
| `banos` | `banos` | 0 if absent |
| `parqueaderos` | `parqueaderos` | 0 if absent |
| `estrato` | — | Genuinely absent → `0` |
| `barrio` | `barrio` | As published |
| `url` | `https://www.habitamos.com.co/propiedades/{codigo}` | SSR detail page resolves |

**Municipalities verified** (2026-10-30): Medellín 162 rentals · Envigado 55 · Sabaneta 11 · Itagüí 3 · La Estrella 1. Any other city raises `UnsupportedCityError`.

## Zero Genuineness

| Field | Default 0 | Status |
|-------|-----------|--------|
| `estrato` | 0 | ✅ Genuine — absent from the API |
| `area` | — | Now published (`area_numero`), no longer genuine 0 |

**Field caveat**: records without a rent price are dropped instead of stored as `precio = 0`; the older card parser stored the 0 and polluted the sheet.
