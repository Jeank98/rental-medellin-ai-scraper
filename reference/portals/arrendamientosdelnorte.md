# Arrendamientos del Norte (`ADN`)

- **URL**: `https://arrendamientosdelnorte.com/buscar/?concepto=Arriendo&tipo=apartamento`
- **Type**: WordPress + REST API
- **API endpoint**: `https://arrendamientosdelnorte.com/wp-json/anorte/v1/buscador`
- **Key feature**: **REST API — no browser, no selectors, no regex needed**
- **Permalink strategy**: **5-segment URL built from API fields** (see below)

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
| `url` | **Construct from API** (see Permalink) | 5-segment path |

**API Parameters**: `concepto=Arriendo`, `tipo=apartamento|casa|apartaestudio`, `page=N`, `per_page=30`

## Permalink — the URL that ACTUALLY shows a property

The API's `link` field returns a **broken** URL (`/arriendo/arriendoNNNN` → 404). Do not use it.

Instead, **build a 5-segment permalink** from the API fields:

```
/propiedades/arriendo/{tipo-slug}/{barrio-slug}/{municipio-slug}/{id}/
```

Where the slugs are lowercased with spaces → hyphens (accents preserved):

| API field | Slug rule | Example |
|---|---|---|
| `tipo` | `s.lower().replace(" ", "-")` | `"Casa"` → `casa` |
| `barrio` | same | `"TRAPICHE"` → `trapiche`, `"LA GABRIELA"` → `la-gabriela`, `"EL DIAMANTE"` → `el-diamante` |
| `sector` | same | `"Bello"` → `bello`, `"Medellín"` → `medellín` |
| `codigo` | as-is | `"5653"` |

Examples (verified live):
- `5653` (Casa, TRAPICHE, Bello) → `/propiedades/arriendo/casa/trapiche/bello/5653/` ✅
- `10894` (Local, LA GABRIELA, Bello) → `/propiedades/arriendo/local/la-gabriela/bello/10894/` ✅
- `5247` (Apartaestudio, PARIS, Bello) → `/propiedades/arriendo/apartaestudio/paris/bello/5247/` ✅

The slug segments are **not validated server-side** — wrong slugs still return 200 and render the property. The slugs are for human-readable URLs only; lookup is by `id`. So if a barrio slug has a special character or typo, the URL still works.

### Detecting stale / inactive codigos (active vs. inactive render the SAME HTTP 200)

| Codigo | URL | HTTP | Body marker |
|---|---|---|---|
| Active (e.g. 5653) | `/propiedades/arriendo/casa/trapiche/bello/5653/` | 200 | `CASA EN BELLO`, `Código\n5653`, `$1.600.000` |
| Inactive (e.g. 11117) | `/propiedades/arriendo/casa/foo/bello/11117/` | **200** ⚠️ | `TIPO SECTOR`, `Código\n—-`, `$33.000.000`, `COMERCIAL` |

**Both return 200.** The body is dramatically different, though:

- **Active property page** has: `LOCAL EN BELLO` / `CASA EN BELLO` / `APARTAESTUDIO EN BELLO` heading, `Código` followed by the actual codigo, and the actual price in `Codigo\nNNNN` and `$X.XXX.000` patterns.
- **Inactive / unknown id** shows the **category archive fallback** with placeholders: `TIPO SECTOR` heading, `Código\n—-`, `$33.000.000`, `Capacidad de energía: COMERCIAL`.

**Active vs inactive detection** (when scraping):
- `re.search(r"Código\s*\n?\s*(\d+)", body)` — returns the codigo if active, `None` if inactive
- OR check for the literal "TIPO SECTOR" string in the body — present only on inactive
- OR check whether the heading "CASA EN BELLO" / "LOCAL EN BELLO" / "APARTAESTUDIO EN BELLO" / etc. matches the expected `{TIPO} EN {MUNICIPIO}` for that record

The most robust single check: **look for `Código\nNNNN` where NNNN matches the requested codigo**. If it's `—-` or the number doesn't match → inactive.

## Search URL gotcha (do NOT use for permalinks)

`/buscar/?concepto=Arriendo&codigo=NNNN` returns 200 with an empty result section — the codigo filter is server-side, but the listings only render after a JS click on "Buscar". The "Buscar" button **resets the codigo** in the form post (it strips `codigo` from the resulting URL — see TEST 1B log: `&codigo=` is empty in the post-Buscar URL). So this URL never shows the codigo's property.

## What about the API `link` field?

```json
"link": "https://arrendamientosdelnorte.com/arriendo/arriendo5653"
```

`/arriendo/arriendo5653` → 404. Don't use it.

## Other endpoints observed

| Endpoint | Behavior |
|---|---|
| `/wp-json/anorte/v1/buscador?concepto=Arriendo&codigo=N` | The search API. Returns JSON with the property or empty `data[]`. |
| `/wp-json/anorte/v1/inmueble?codigo=N` | Single-property detail. Returns full JSON if active, 404 + `{"message":"Inmueble no encontrado","codigo_buscado":"N"}` if inactive. |
| `/wp-json/anorte/v1/municipios?concepto=Arriendo` | List of municipalities (Bello, Copacabana, Guarne, Girardota, Barbosa, …). |
| `/wp-json/anorte/v1/destacados` | Featured listings (for the archive page's sidebar). |

## Notes

- Cleanest portal — structured JSON, no parsing needed
- `tipo=casa` returns mixed tipos (Casa + Casa-Finca + Casa-local) — post-filter
- Banos, parking, estrato available in single-property detail endpoint (`/inmueble?codigo=xxx`) but not in search
- Three tipos must be scraped separately: apartamento, casa, apartaestudio
- The `link` field in the API response is **broken**; build the permalink from the 5-segment pattern

## Zero Genuineness

| Field | Default 0 | Status |
|-------|-----------|--------|
| `banos` | 0 | ✅ Genuine — Not in search API (detail endpoint has them but search doesn't) |
| `parqueaderos` | 0 | ✅ Genuine — Not in search API (detail endpoint has them but search doesn't) |
| `estrato` | 0 | ✅ Genuine — Not in search API (detail endpoint has them but search doesn't) |
