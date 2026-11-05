# Arrendamientos SantaFe (`ASF`)

- **Search API**: `https://arrendamientossantafe.com/apisf/properties?page={N}&oferta=Arriendo&ciudad={CIUDAD}`
- **Detail API**: `https://arrendamientossantafe.com/apisf/property/{CODE}`
- **Type**: JSON API (two phases: list + detail enrichment)
- **Listings per page**: 12 (`per_page` in the response)
- **Total pages**: `ceil(total / per_page)`; the response also carries `has_more`
- **Traps**:
  - Both responses are wrapped as `<html><body>{…json…}</body></html>`; unwrap before `json.loads`.
  - `ciudad` filters on the accented label the API prints (`Medellín`, `Itagüí`, `La Estrella`).
  - The public site (`/propiedades`) is now a Next.js shell with no cards and `/propiedad/{CODE}` renders client-side. The two `/apisf` endpoints are the reachable source.

### Phase A — search records

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `ASF-{codigo}` | `codigo` (e.g. `A64311`) |
| `portal` | `arrendamientossantafe` | Fixed |
| `tipo` | `type` | `Apartamento`→`apartamento`, `Casa`→`casa`; `Casa Local`, `Finca`, `Local`, `Oficina`, `Bodega` are skipped |
| `precio` | `price_raw` | Integer; `price` is the padded string (`"$9'000'000"`) |
| `area` | `size` | `"253 M²"` → `253` (detail record is authoritative) |
| `habitaciones` | `bedrooms` | 0 if absent |
| `banos` | `bathrooms` | Replaced by the detail value |
| `parqueaderos` | — | Always 0 in the list; comes from detail |
| `estrato` | — | Comes from detail |
| `barrio` | `location` | Detail's `sector` wins when present |
| `url` | `/propiedad/{codigo}` | Prefixed with the domain |

### Phase B — detail records (`/apisf/property/{code}`)

Publishes `area`, `habitaciones`, `banos`, `parqueaderos`, `garajes`, `estrato`, `sector`, `price_raw` and `description`. Phase B is capped at 8 workers and honours `--reuse-unchanged-details`: a listing whose `id` and rent price match the active snapshot keeps its detail fields and is not re-fetched.

**Municipalities verified** (2026-11-05): Medellín 934 · Envigado 83 · Sabaneta 50 · Itagüí 25 · La Estrella 9 rental offers, before the residential filter. Any other city raises `UnsupportedCityError`.

## Zero Genuineness

| Field | Default 0 | Status |
|-------|-----------|--------|
| `estrato` | 0 | Genuine only when the detail record omits it |
| `parqueaderos` | 0 | Genuine — the property has no parking |
