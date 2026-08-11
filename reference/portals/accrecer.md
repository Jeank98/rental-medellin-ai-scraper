# Acrecer (`AC`)

- **URL**: `https://www.acrecer.com/inmuebles/arriendo/Apartamento/Medell%C3%ADn?page={N}` and `https://www.acrecer.com/inmuebles/arriendo/Casa/Medell%C3%ADn?page={N}`
- **Type**: Single-phase RSC (Next.js embedded search payload, no detail pages)
- **Listing card**: Not applicable (data extracted from RSC `searchResults` payload, not rendered DOM)
- **Listings per page**: 12 (`recordsPerPage`)
- **Total pages**: Bounds computed from `totalRecords` / `recordsPerPage`
- **Pagination**: Direct `?page=N`; a zero-record page stops that type
- **Permalink**: `https://www.acrecer.com/inmueble/{code}` where code = `AC-{digits}`

| Column | Source field | Pattern |
|--------|-------------|---------|
| id | `code` | `AC-{digits}` |
| portal | constant | `accrecer` |
| tipo | `propertyType` | lowercase (Apartamento→apartamento, Casa→casa) |
| precio | `rentValue` | plain integer |
| area | `builtArea` | `round()` |
| habitaciones | `numberOfRooms` | integer, 0 when absent |
| banos | `rooms.baths` | integer, 0 when absent |
| parqueaderos | `householdFeatures.garages` | private parking only; 0 when absent; NO visitor/condominium sum |
| estrato | `stratum` | Roman numeral (III-VI) → integer via `normalize_estrato` |
| barrio | `sectorName` → `zoneName` fallback | sectorName first, then zoneName, then empty |
| url | `https://www.acrecer.com/inmueble/{code}` | absolute URL |

**Notes**:
- Detail pages intentionally excluded; compared detail payloads preserved source absences. Conditional icon rendering on cards reflects source-data gaps.
- `estrato` raw format is Roman numeral.
- `numberOfRooms` equals bedroom count per property descriptions.
- RSC payload extraction uses `self.__next_f.push(` token + `json.JSONDecoder.raw_decode`.

**Zero Genuineness**:
- `banos` → 0 when `rooms.baths` absent
- `parqueaderos` → 0 when `householdFeatures.garages` absent
- `habitaciones` → 0 in extreme case
- These are source-data absences, not extraction failures.

## Recent fixes
