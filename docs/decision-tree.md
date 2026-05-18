# Decision Tree — Missing and Ambiguous Fields

When a target field cannot be found or is ambiguous, follow this decision tree. Never guess.

## Precio (price) missing

1. **Search broader**: expand regex to the full card HTML, not just the price container
2. **Contact price**: some portals only show price on the detail page, not the listing card → set to `0`, flag
3. **Multi-currency confusion**: if both COP and USD appear, prefer COP for Colombian portals
4. **Zero price**: if the portal shows "Consultar precio" or "A convenir" → set to `0`, flag

## Area missing

1. **Check description text**: some portals embed area in a text description, not a labeled field
2. **Check detail page**: if area is only on the detail page, set to `0` (bulk scrape can't fetch detail pages)
3. **Alternative units**: if area is in "hectáreas" or "fanegadas" (farms/lots), set to `0` and flag

## Habitaciones (bedrooms) vs Banos (bathrooms) confusion

When numbers appear without labels or with ambiguous icons:

1. **Inspect CSS classes**: `<span class="alcobas">` = bedrooms, `<span class="banos">` = bathrooms
2. **Inspect icon filenames**: `bed-icon.png` = bedrooms, `bath-icon.png` or `shower-icon.png` = bathrooms
3. **Inspect icon FontAwesome classes**: `fa-bed` = bedrooms, `fa-bath` = bathrooms
4. **Use Playwright for visual inspection** (last resort): navigate to page, take a screenshot, verify icon meaning from context
5. **If still ambiguous after all checks**: set both to `0`, flag in report

Common order in Colombian portals:
```
habitaciones → baños → parqueaderos → área
     OR
área → habitaciones → baños → parqueaderos
```

But NEVER rely on position alone. Always verify.

## Parqueaderos (parking) confusion with other fields

The car icon (`fa-car`, `fa-warehouse`) can be confused with:
- **Garage door icon vs car icon**: both mean parking
- **Number after car icon**: this IS parking
- **Number before car icon**: likely a different field

Outlier detection: if parqueaderos > 10, inspect the source HTML. Common causes:
- Property code leaked into parking field (`<li>141</li>` where 141 is a code, not parking)
- The portal merged two fields without a separator
- Solution: flag in report, do NOT silently change

## Barrio (neighborhood) extraction

1. **"Ubicación: X"**: X is the neighborhood
2. **"Barrio: X"**: X is the neighborhood
3. **Only an address**: extract the neighborhood portion (usually the last proper noun before city name)
4. **Map marker text**: some portals put neighborhood in map markers only — unavailable in listing cards → empty string
5. **Multiple locations**: some portals show both barrio and municipality → prefer barrio, note municipality in report

## Estrato missing (Colombia-specific)

1. **Not in listing card**: check page text for "Estrato" keyword
2. **Only in filters sidebar**: estrato may appear in filter options but not per-property → set to `0`
3. **Non-Colombian portal**: always `0`
4. **Always 0 without the explicit keyword "estrato"** — never infer from price or neighborhood

## Tipo (property type) normalization

| Portal value | Normalize to |
|---|---|
| Apartamento, Apto, Departamento, Apartment, Department, Depto | `apartamento` |
| Casa, House, Vivienda | `casa` |
| Apartaestudio, ApartaEstudio, Studio, Studio flat | `apartaestudio` |
| Local, Comercial, Commercial, Local comercial | `local` |
| Oficina, Office | `oficina` |
| Bodega, Warehouse, Depósito | `bodega` |
| Lote, Lot, Terreno, Land | `lote` |
| Finca, Farm, Hacienda, Parcela | `finca` |
| CasaLocal (mixed) | Keep as `casalocal` (don't force into casa or local) |
| Unknown/other | Keep raw text, lowercase, trimmed |

## URL missing or relative

1. **Relative URL**: prepend portal domain (`https://{domain}`)
2. **No link wrapping the card**: check if the card has `onclick` or `data-href` attributes
3. **Image-only link**: some portals link only the image, not the title → use `<a>` wrapping the image
4. **No URL at all**: empty string

## General decision rules

- **When in doubt, set to `0` or empty string** — never fabricate data
- **Flag anomalies**, don't fix them silently
- **Report missing fields** so the user knows the data's completeness
- **Document portal-specific quirks** in `reference/portal-field-mappings.md` for future scrapes
