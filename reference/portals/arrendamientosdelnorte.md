# Arrendamientos del Norte (`ADN`)

- **URL**: `https://arrendamientosdelnorte.com/buscar/?concepto=Arriendo&tipo=apartamento`
- **Type**: WordPress + REST API
- **API endpoint**: `https://arrendamientosdelnorte.com/wp-json/anorte/v1/buscador`
- **Key feature**: **REST API — no browser, no selectors, no regex needed**

| Column | API field | Pattern |
|--------|-----------|---------|
| `id` | `ADN-{codigo}` | `codigo: "9112"` |
| `portal` | `arrendamientosdelnorte` | Fixed |
| `tipo` | `tipo` | `"Apartamento"` → `apartamento` |
| `precio` | `valor` | `"$550.000"` → `550000` (strip `$` and `.`) |
| `area` | `area` | `"60 m<sup>2</sup> aprox."` → `60` (strip HTML, take before ` m`) |
| `habitaciones` | `cuartos` | `"2"` → `2` |
| `banos` | **Not in search API** | → `0` |
| `parqueaderos` | **Not in search API** | → `0` |
| `estrato` | **Not in search API** | → `0` |
| `barrio` | `barrio` | As-is, trimmed |
| `url` | `link` | Already absolute URL |

**API Parameters**: `concepto=Arriendo`, `tipo=apartamento|casa|apartaestudio`, `page=N`, `per_page=30`

**Notes**:
- Cleanest portal — structured JSON, no parsing needed
- `tipo=casa` returns mixed tipos (Casa + Casa-Finca + Casa-local) — post-filter
- Banos, parking, estrato available in single-property detail endpoint (`/inmueble?codigo=xxx`) but not in search
- Three tipos must be scraped separately: apartamento, casa, apartaestudio

## Zero Genuineness

| Field | Default 0 | Status |
|-------|-----------|--------|
| `banos` | 0 | ✅ Genuine — Not in search API (detail endpoint has them but search doesn't) |
| `parqueaderos` | 0 | ✅ Genuine — Not in search API (detail endpoint has them but search doesn't) |
| `estrato` | 0 | ✅ Genuine — Not in search API (detail endpoint has them but search doesn't) |
