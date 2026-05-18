# Variable Detection Strategies

When encountering an unfamiliar real estate portal, the agent must dynamically discover which HTML elements map to the 11 target columns. This document defines detection strategies for each field.

## Detection priority order

For each field, try strategies in order. Stop at first match.

### Price (`precio`)

1. **Currency symbol pattern**: find `$`, `COP`, `USD` with a number nearby. Prefer numbers with thousands separators (`.` in Colombia, `,` in US).
2. **Keyword proximity**: `precio`, `canon`, `valor`, `arriendo`, `rent`, `price`, `alquiler` near a number.
3. **Largest number in card**: if multiple prices exist (e.g., arriendo + venta), prefer the one near "Arriendo" or similar rental keyword.
4. **Text-only fallback**: look for the most prominent currency-formatted number in the card.

Edge cases:
- `ARRIENDO/VENTA`: two prices separated by `/`. Take the first (rental).
- Daily/weekly rates: prefer monthly if available. Flag non-monthly in report.
- Multi-currency: prefer COP for Colombian portals.

### Area (`area`)

1. **Unit pattern**: find `m²`, `m2`, `mt2`, `mts²`, `metros` with a number immediately before.
2. **Keyword proximity**: `área`, `area`, `superficie`, `metros` near a number + unit.
3. **sqft conversion**: if only sqft available, note in report but set to `0` (don't convert; risk of wrong factor).

Edge cases:
- `0m²` or `0m2`: likely a data entry error. Set to `0`, flag in report.
- Area in hectares (parcelas/fincas): flag but set to `0`.

### Bedrooms (`habitaciones`)

1. **Labeled element**: element with class/id containing `alcoba`, `habitacion`, `dormitorio`, `bedroom`, `bed`, `room`.
2. **Icon detection**: bed icon (FontAwesome `fa-bed`, bed SVG, 🛏️). Take the sibling text number.
3. **Keyword in text**: find `alcoba`, `habitación`, `dormitorio`, `cuarto` followed by or near a single-digit number.
4. **Positional heuristics**: usually the first amenity listed after price/area. Often paired with bathrooms.

Critical rule: when icons are used without labels, verify by examining the icon filename/CSS class (e.g., `bed-icon-xs.png` = bedrooms, `bath-icon.png` = bathrooms). Never assume position alone.

### Bathrooms (`banos`)

1. **Labeled element**: element with class/id containing `bano`, `baño`, `bath`, `wc`, `toilet`.
2. **Icon detection**: bath/shower icon (`fa-bath`, shower SVG, 🛁🚽). Take the sibling text number.
3. **Keyword in text**: find `baño`, `bathroom`, `wc` near a single-digit number.
4. **Absence**: many portals don't show bathrooms in listing cards. `0` is valid and common.

### Parking (`parqueaderos`)

1. **Labeled element**: element with class/id containing `garaje`, `parqueadero`, `parking`, `garage`, `parq`.
2. **Icon detection**: car icon (`fa-car`, `fa-warehouse`, car SVG, 🚗). Take the sibling text number.
3. **Keyword in text**: find `parqueadero`, `garaje`, `estacionamiento`, `parking` near a number.
4. **Typically the last amenity** in row-based layouts.

Outlier detection: values > 10 are likely source data errors (property codes leaking into parking field). Flag in report.

### Property type (`tipo`)

1. **Heading/title text**: usually in an `<h2>`, `<h3>`, or `.title` element.
2. **Labeled element**: text after `Tipo:`, `Type:`, `Property type:`.
3. **URL path segment**: some portals include type in URL: `/apartamento/`, `/casa/`.
4. **Image alt text**: sometimes "Foto de apartamento en arriendo".
5. **Normalize** to lowercase using the mapping table in `columns-spec.md`.

### Neighborhood (`barrio`)

1. **Labeled element**: text after `Ubicación:`, `Barrio:`, `Zona:`, `Sector:`, `Location:`.
2. **Location icon nearby**: map pin icon with adjacent text.
3. **Address block**: first line of address, neighborhood portion.
4. **Filter match**: if the portal has a "barrio" filter dropdown, match listing text against filter options.

### Socioeconomic level (`estrato`)

1. **Keyword with number**: `Estrato:` or `Estrato` followed by `1`-`6`.
2. **Embedded in title**: some portals show "Apartamento Estrato 4" in the listing title.
3. **Absence**: most non-Colombian portals and many listing cards don't show estrato. `0` is valid.

### URL

1. **Anchor wrapping the card/image**: `<a href="...">` that wraps the entire card or its image.
2. **Anchor with property code**: `<a href="/propiedad/A11248/">`.
3. **Make absolute**: if relative (`/propiedad/A11248/`), prepend `https://{domain}`.
4. **URL of the search page** as last resort.

### ID/Code

1. **Labeled element**: text after `REF:`, `Código:`, `Code:`, `ID:`, `#`.
2. **URL path extraction**: `/codigo/69007` → `69007`, `/propiedad/A11248/` → `A11248`.
3. **Data attribute**: `data-id`, `data-code`, `data-property-id`.
4. **Generate**: if no code found, use `{PREFIX}-{row_index}`.

## Validation signals

When you think you've mapped a field, validate:
- **Count**: do all cards have the same number of fields in the same positions?
- **Range**: are the values plausible? (price > 0, area 20-10000, rooms 0-20)
- **Consistency**: same CSS class across all cards for the same field?
- **Icons**: when using icons, verify the icon filename contains the right word (`bed`, `bath`, `car`, `area`)
