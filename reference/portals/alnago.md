# Alnago (`ALN`)

- **URL**: `https://alnago.com/es/categorias/arrendar/todos/medellin`
- **Type**: JS-rendered Next.js SPA + REST JSON API (`api.alnago.com`)
- **Listing card**: N/A — listings come from JSON API, not scraped HTML
- **Listings per page**: 30 (fixed, via `skip` parameter)
- **Total pages**: ~39 for all cities; fewer when filtered to Medellín (`id_city=496`)
- **Pagination**: `skip` parameter — `?for_rent=true&skip=0`, `skip=30`, `skip=60`, ...
- **Key feature**: **REST API returns all 11 fields as structured JSON — no HTML scraping required.** Even `estrato` is available (rare).

## Scraping Strategy

**API-first — no HTML scraping needed.** The frontend at `alnago.com` is a client-rendered Next.js app that shows "Cargando..." on initial load. However, a separate REST API at `api.alnago.com` returns all listing data as clean JSON.

**Approach:**
1. Query `https://api.alnago.com/property?for_rent=true&id_city=496` (Medellín)
2. Paginate via `skip=0`, `skip=30`, `skip=60`, etc.
3. Stop when response is `[]` (empty array) or < 30 items
4. Map JSON fields directly to the 11 output columns

No `scrapling_get`, no `scrapling_screenshot`, no button clicks needed. The API has no authentication or rate limiting.

## Field Mappings

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | API: `entry` | `ALN-{entry}` (e.g., `ALN-R17329`) |
| `portal` | Fixed | `alnago` |
| `tipo` | API: `id_property_type` | Map via lookup: `1→casa, 2→apartamento, 3→local, 4→oficina, 5→lote, 7→finca, 8→bodega, 14→apartaestudio, 15→oficina, 19→apartamento, 20→apartamento, 26→bodega, 28→casa` |
| `precio` | API: `rent_price` | Integer, already clean — no formatting to strip |
| `area` | API: `area` | Integer, M² |
| `habitaciones` | API: `bedrooms` | Integer |
| `banos` | API: `bathrooms` | Integer |
| `parqueaderos` | API: `garages` | Integer |
| `estrato` | API: `stratum` | Integer (1–6) — **available!** |
| `barrio` | API: `zone_label` | String, title-case (e.g., `Poblado`) |
| `url` | API: `id_property` | `https://alnago.com/es/inmueble/{id_property}` |

## Property Type Mapping (`id_property_type` → `tipo`)

| id_property_type | tipo | Notes |
|---|---|---|
| 1 | `casa` | Some titles say "Apartamento" — data entry issue, trust the ID |
| 2 | `apartamento` | Most common type |
| 3 | `local` | Commercial space |
| 4 | `oficina` | Office |
| 5 | `lote` | Land / lot |
| 7 | `finca` | Farm |
| 8 | `bodega` | Warehouse |
| 14 | `apartaestudio` | Studio apartment |
| 15 | `oficina` | Consultorio → oficina |
| 19 | `apartamento` | Condominio → apartamento |
| 20 | `apartamento` | Duplex → apartamento |
| 26 | `bodega` | Garaje comercial → bodega |
| 28 | `casa` | Cabaña → casa |

## Cities Reference

From `https://api.alnago.com/cities-sectors-zones`:

| City | id_city |
|------|---------|
| Medellín | 496 |
| Bello | 89 |
| Envigado | 291 |
| Itagui | 389 |
| Sabaneta | 698 |
| La Estrella | 416 |
| Copacabana | 219 |
| (and ~20 more) | ... |

**Notes**:
- API has no auth, no rate limiting observed during discovery
- Pagination uses `skip=N`, 30 items per page (fixed — `limit` param ignored)
- `entry` field is the portal's reference code (e.g., "R17329") — use for `id` column
- `id_property` is numeric (e.g., 9993580) — use only for constructing detail URL
- Detail page URL: `https://alnago.com/es/inmueble/{id_property}` (verified working)
- Frontend uses "Cargar Más" infinite scroll, but API `skip` pagination makes click automation unnecessary
- `id_property_type=1` has occasional title mismatches ("Apartamento" titles on casa type) — prefer `id_property_type` as authoritative
- Estrato (`stratum`) is available for nearly all listings — **no need to default to 0**
- Area always in M² (`unit_area_label: "M2"`) — no conversion needed
