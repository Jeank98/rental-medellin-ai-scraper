# Alberto Alvarez (`AAL`)

- **URL**: `https://albertoalvarez.com/inmuebles/arrendamientos/{tipo}/medellin/` (redirects to the current `/en/` frontend route)
- **Type**: Server-rendered Next.js HTML
- **Listing card**: Visible-text `div` cards containing one `/inmuebles/detalle/arrendamientos/` link and a `Cod:` label
- **Listings per page**: 9
- **Current observed result**: 27 listings across the three residential routes (2026-08-14; volatile)
- **Pagination**: `?limit=9&pag=N`; stop when a page produces no new listing IDs because the site repeats its last page instead of returning an empty page
- **Key feature**: Current cards expose price, locality, area, bathrooms, and bedrooms as visible text; legacy hidden JSON parsing remains as a fallback for older responses

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `AAL-{code}` | Detail URL code → `AA-95022` |
| `portal` | `albertoalvarez` | Fixed |
| `tipo` | Residential route | `apartamento`, `casa`, or `apartaestudio` |
| `precio` | Visible `$...` value | `$4.500.000` → `4500000` |
| `area` | Value immediately before `Metros` | `53 Metros` → `53` |
| `habitaciones` | Value immediately before `Alcobas` | `1 Alcobas` → `1` |
| `banos` | Value immediately before `Baños` | `2 Baños` → `2` |
| `parqueaderos` | Current card source | Absent from current cards → `0` |
| `estrato` | Current card source | Absent from current cards → `0` |
| `barrio` | Visible locality heading before `, Medellín` | `laureles, medellín` → `Laureles` |
| `url` | Detail link in the card | Canonical absolute `/inmuebles/detalle/arrendamientos/...` URL |

**Legacy Estrato conversion**:
| Roman | Int |
|-------|-----|
| I | 1 |
| II | 2 |
| III | 3 |
| IV | 4 |
| V | 5 |
| VI | 6 |

**Notes**:
- Current cards do not expose parking or estrato; both remain source-absent defaults until the frontend exposes them again
- Older responses may still contain two hidden JSON textareas (`.field-property` and `.info-prop-mobilia`); `.field-property` remains supported
- The scraper deduplicates modern cards globally by `AAL-AA-{code}` and stops on a repeated page
- "casa vivienda" remains supported by the legacy JSON path and normalizes to `casa`
- Estrato 7 found in some listings — source data error (Colombia max is 6)
- Multiple neighborhoods observed across all listings
- Three tipos must be scraped separately (different URLs): apartamento, casa, apartaestudio
