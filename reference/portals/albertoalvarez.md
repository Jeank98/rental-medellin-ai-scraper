# Alberto Alvarez (`AAL`)

- **URL**: `https://albertoalvarez.com/inmuebles/arrendamientos/{tipo}/medellin/`
- **Type**: Server-rendered WordPress + Elementor
- **Listing card**: `<article>`
- **Listings per page**: 9
- **Total pages**: 56 apartamentos, 7 casas, 11 apartaestudios (650 total; 2026-05-18)
- **Pagination**: `?limit=9&pag=N`
- **Key feature**: **Hidden JSON in every card** — `<textarea class="field-property">` contains complete structured data

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `AAL-{code}` | JSON `code` → `AA-92927` |
| `portal` | `albertoalvarez` | Fixed |
| `tipo` | JSON `propertyType` | `Apartamento` → `apartamento` ("casa vivienda" → `casa`) |
| `precio` | JSON `rentValue` | Raw integer, no formatting |
| `area` | JSON `builtArea` | Raw integer |
| `habitaciones` | JSON `numberOfRooms` | Raw integer |
| `banos` | JSON `householdFeatures.baths` | Nested, raw integer |
| `parqueaderos` | JSON `householdFeatures.AASimpleparking` | Nested, raw integer |
| `estrato` | JSON `stratum` | **Roman numeral** → `V`=5, `IV`=4, `III`=3, `VI`=6 |
| `barrio` | JSON `sectorName` | Trimmed string |
| `url` | Constructed or from `data-url` | `/inmuebles/detalle/arrendamientos/{tipo}/{code}/{barrio}-medellin/` |

**Estrato conversion**:
| Roman | Int |
|-------|-----|
| I | 1 |
| II | 2 |
| III | 3 |
| IV | 4 |
| V | 5 |
| VI | 6 |

**Notes**:
- Easiest portal to scrape — no CSS selectors, no icon detection, no regex
- Two hidden JSON textareas per card (`.field-property` and `.info-prop-mobilia`) — use `.field-property`
- Parking only available via JSON (not visible in listing card HTML)
- "casa vivienda" is the raw propertyType for houses — normalize to `casa`
- Estrato 7 found in 5 listings — source data error (Colombia max is 6)
- 85 unique neighborhoods across 650 listings
- Three tipos must be scraped separately (different URLs): apartamento, casa, apartaestudio
