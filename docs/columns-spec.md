# Column Specification

Every listing record (CSV row or database row) must have exactly these 11 columns in this order. All numeric fields are plain integers (no formatting, no symbols, no decimals). Missing fields are `0` for numeric, empty string for text.

## Column definitions

### 1. `id` — string
**Composite identifier. Globally unique across portals.**

Format: `{PREFIX}-{CODE}`

- `PREFIX`: 2-4 uppercase letters derived from portal name. Maxibienes → `MXB`, FincaRaiz → `FNR`, Arrendamientos SantaFe → `ASF`, MetroCuadrado → `MTC`
- `CODE`: internal property code from the portal (numeric or alphanumeric). Extract from URL path, data attribute, or visible label
- If no code exists, generate: `{PREFIX}-{ROW_INDEX}`

Examples: `MXB-69007`, `ASF-A11248`, `FNR-ABC123`

### 2. `portal` — string
**Portal identifier.** Domain without TLD, lowercase.

- `www.maxibienes.com` → `maxibienes`
- `arrendamientossantafe.com` → `arrendamientossantafe`
- `www.fincaraiz.com.co` → `fincaraiz`

### 3. `tipo` — string (normalized lowercase)
**Property type.** Normalize to one of:

| Raw value | Normalized |
|---|---|
| Apartamento, Apto, Departamento, Apartment, Department | `apartamento` |
| Casa, House | `casa` |
| Apartaestudio, ApartaEstudio, Studio | `apartaestudio` |
| Local, Comercial, Commercial | `local` |
| Oficina, Office | `oficina` |
| Bodega, Warehouse | `bodega` |
| Lote, Lot, Terreno | `lote` |
| Finca, Farm, Hacienda | `finca` |

If the type cannot be determined, use the raw text as-is, lowercased.

### 4. `precio` — integer
**Monthly rental price in local currency (COP for Colombia).** Digits only.

- `$ 1.450.000` → `1450000`
- `$1,600,000` → `1600000`
- `$ 3.156.000` → `3156000`
- For `ARRIENDO/VENTA` listings, extract the rental price (first number before `/`)
- If no price found: `0` (flag as anomaly in report)

### 5. `area` — integer
**Area in square meters.** Extract the number before `m²`, `m2`, `mt2`, `mts²`.

- `50 m²` → `50`
- `180m2` → `180`
- If area is in another unit (sqft, hectares), note in report but set to `0`
- If no area found: `0`

### 6. `habitaciones` — integer
**Number of bedrooms.**

Keywords: `habitación`, `habitaciones`, `alcoba`, `alcobas`, `dormitorio`, `cuarto`, `cuartos`, `bedroom`, `bedrooms`, `hab`
Icons: bed icon (`fa-bed`, bed SVG, bed emoji)

- Range validation: 0-30 (flag > 15 as possible error)
- If `apartaestudio`, 1 is expected; 0 is acceptable
- If no value found: `0`

### 7. `banos` — integer
**Number of bathrooms.**

Keywords: `baño`, `baños`, `bathroom`, `bathrooms`, `banos`, `bath`, `wc`
Icons: bath/shower icon (`fa-bath`, shower SVG), toilet icon

- Range validation: 0-20 (flag > 10 as possible error)
- Many portals don't show bathrooms in listing cards. `0` is acceptable
- If no value found: `0`

### 8. `parqueaderos` — integer
**Number of parking spots.**

Keywords: `parqueadero`, `parqueaderos`, `garaje`, `garajes`, `estacionamiento`, `parking`, `garage`, `parq`
Icons: car icon (`fa-car`, `fa-warehouse`, car SVG)

- Range validation: 0-10 (flag > 5 as possible error)
- Common source error: property code leaked into parking field (e.g., `141` instead of `1`)
- Flag outliers > 10 in report
- If no value found: `0`

### 9. `estrato` — integer
**Socioeconomic level (Colombia-specific).** Values 1-6.

Keyword: `estrato` followed by a number
- Colombian portals often show this
- Non-Colombian portals: set to `0`
- If not displayed in listing cards: `0`
- Range validation: 0-6

### 10. `barrio` — string
**Neighborhood name.**

Keywords: `barrio`, `zona`, `sector`, `neighborhood`, `ubicación`, `location`, `address`
- Take the proper noun value, not the label
- `"Ubicación: Cristo Rey"` → `Cristo Rey`
- `"Barrio: Laureles"` → `Laureles`
- Trim whitespace, preserve case (proper nouns)
- If no neighborhood found: empty string

### 11. `url` — string
**Full absolute URL to the property detail page.**

- From the `<a href="...">` wrapping the listing card/image/title
- If relative URL (e.g., `/propiedad/A11248/`), prepend the portal domain
- Must be absolute: `https://arrendamientossantafe.com/propiedad/A11248/`
- If no detail page exists, use the search results URL
- If no URL found: empty string

## Type validation checklist

Before writing output (CSV or DB), verify:
- [ ] `precio`, `area`, `habitaciones`, `banos`, `parqueaderos`, `estrato` are all integers
- [ ] No `$`, `.`, `,`, spaces in numeric fields
- [ ] No `N/A`, `null`, `None`, `-1` as placeholder values
- [ ] `tipo` is one of the normalized values or raw lowercase text
- [ ] `id` values are unique
- [ ] `url` values are absolute URLs
- [ ] `barrio` is trimmed, no label prefix like "Barrio:"
