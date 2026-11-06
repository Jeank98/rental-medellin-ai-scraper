# Arrendamientos Las Vegas (`LVG`)

- **API**: `https://arrendamientoslasvegas.com/api/properties?perpage=50&status=1&page={N}&biz=1,3&city={CODE}`
- **Type**: REST JSON (one phase, no detail pages needed)
- **Listings per page**: 50 — the server caps `perpage` at 50 even if you ask for 100
- **Total pages**: `last_page` in the response (`total` carries the count)
- **Traps**:
  - The body is wrapped as `<html><body>{…json…}</body></html>`; unwrap before `json.loads`.
  - The public site is a Next.js SPA and its menu links `/inmuebles/undefined`; the API above is the reachable source and answers plain HTTP (no Turnstile).
  - `biz=1,3` returns only `ARRIENDO` records today, but `LOCAL`, `BODEGA` and similar still appear and must be filtered.
  - Detail pages (`/inmuebles/{codpro}`) answer 200 but render the price client-side, so link checks cannot assert on price text.

| Column | Source | Notes |
|--------|--------|-------|
| `id` | `LVG-{codpro}` | `codpro` |
| `portal` | `arrendamientoslasvegas` | Fixed |
| `tipo` | `type` | `APARTAMENTO`/`CASA`/`APARTAESTUDIO`; others dropped |
| `precio` | `rent` (fallback `price`) | 0 or out of range drops the record |
| `area` | `area_cons` | Always published |
| `habitaciones` | `bedrooms` | 0 if absent |
| `banos` | `bathrooms` | 0 if absent |
| `parqueaderos` | `parking` | 0 if absent |
| `estrato` | `stratum` | 1–6 |
| `barrio` | `neighborhood` | As published |
| `url` | `/inmuebles/{codpro}` | Prefixed with the domain |

**City codes** (`/api/cities`): Medellín `5001` · Envigado `5266` · Itagüí `5360` · Sabaneta `5631` · La Estrella `5380`. Any other city raises `UnsupportedCityError`.

**Volume** (2026-11-06, rentals before the residential filter): Medellín 143 · Sabaneta 85 · La Estrella 53 · Envigado 50 · Itagüí 14.
