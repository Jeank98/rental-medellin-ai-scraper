# La Palma Inmobiliaria (`LPI`)

- **URL**: `https://lapalmainmobiliaria.com.co/s/arriendo`
- **Type**: Server-rendered HTML (Wasi)
- **Portal**: `lapalmainmobiliaria`
- **Listing cards**: Generic card ancestors around numeric detail links; the parser uses visible labels rather than fixed CSS field selectors
- **Listings per page**: 12 on sampled pages
- **Pagination**: `/search` with the complete rental query and `page=N`
- **Verified bound**: Page 11 had 7 cards and no `Siguiente`; page 12 was empty. Stop on an empty page or a page containing only already-seen source IDs.
- **City filter**: Medellin is `id_city=496`
- **Rental query**: Preserve `id_city=496`, `business_type[0]=for_rent`, `order_by=created_at`, `order=desc`, `page=N`, `for_sale=0`, `for_rent=1`, `for_temporary_rent=0`, `for_transfer=0`, and `lax_business_type=1`.
- **Residential type sources**: Add `id_property_type=2` for apartamento, `id_property_type=1` for casa, and `id_property_type=14` for apartaestudio to the same `/search` query.
- **Accepted residential types**: `apartamento`, `casa`, `apartaestudio`; no additional subtypes are accepted.
- **Availability**: Exclude cards visibly marked `Alquilado` or `Arrendado`.
- **Key feature**: **Two-phase scrape**. Cards provide all fields except explicit estrato and barrio/zone.

## Phase A: Search cards

Iterate the three residential type sources independently, page by page. Union the results by the numeric URL suffix before Phase B. The normalized-type guard runs again immediately before detail enrichment so a commercial source leak cannot trigger a detail request.

| Column | Source | Handling |
|--------|--------|----------|
| `id` | Final numeric URL segment | Compose `LPI-{code}` and deduplicate by code |
| `portal` | Fixed | `lapalmainmobiliaria` |
| `tipo` | Visible property type text | Normalize with shared mapping |
| `precio` | `$` rental line | Shared price normalizer |
| `area` | Visible `Area m2`/`Area m²` label | Integer before the unit |
| `habitaciones` | `Alcobas`/`Habitaciones` label | Explicit card value |
| `banos` | `Bano`/`Baños` label | Explicit card value, including zero |
| `parqueaderos` | `Parqueadero`/`Garaje` label | Explicit card value, including zero |
| `estrato` | Absent from sampled cards | Keep `0` until Phase B |
| `barrio` | City-level card location only | Keep empty until Phase B |
| `url` | Absolute detail anchor | Preserve official permalink |

## Phase B: Detail pages

Fetch each active card URL and extract only:

| Column | Detail label |
|--------|--------------|
| `estrato` | `Estrato:`; absent means proven source absence and remains `0` |
| `barrio` | `Zona:`, `Barrio:`, or `Sector:`; absent remains empty |

The tested detail URL retained the exact numeric ID and added `Estrato: 3` and `Zona: Villa hermosa`. Detail pages did not add parking, so card parking values remain authoritative.

## Operational notes

- `sample_only` limits Phase A to three pages when no explicit limit is supplied.
- Each residential type source is fetched sequentially so it can stop safely at an empty or stale page without probing an unbounded page range.
- `max_pages` applies independently to each residential type source.
- Detail failures retain card defaults and are reported by the shared validator when applicable.
- The search inventory can include `Alquilado` records; availability filtering is mandatory.
