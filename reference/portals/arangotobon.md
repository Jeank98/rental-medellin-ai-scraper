# Arango Tobón Inmobiliaria (`ATB`)

- **URL**: `https://www.arangotobon.com/inmuebles/Arriendo/clases_Apartamento_Apto-Loft_Apartaestudio_Casa/municipios_Medell%C3%ADn/`
- **Type**: Server-rendered HTML (ASP.NET MVC)
- **Portal**: `arangotobon`
- **Strategy**: Two-phase HTML with detail enrichment
- **Card selector**: `.property_item`
- **Detail page**: `/inmueble/{code}-{slug}`
- **Pagination**: Page 1 is the search URL; later pages append `/2`, `/3`, etc.
- **Observed inventory**: 52 results across four pages (16, 16, 16, 4); page 5 is empty.

## Search Filters

The confirmed rental route combines four residential source classes with `_`:

`clases_Apartamento_Apto-Loft_Apartaestudio_Casa`

The current observed class counts are 33 `Apartamento`, 2 `Apto-Loft`, 9
`Apartaestudio`, and 8 `Casa`. The root URL and `/1` return the same page;
do not scrape both.

The portal JavaScript also builds route segments for price, bedrooms,
bathrooms, and features such as `Garaje`, `Ascensor`, `Piscina`, and
`amoblado`. A source bug omits a slash after `banos_N`, so a combined
`banos_1Garaje` route is not reliable. The scraper uses the confirmed
residential route and does not synthesize additional filter combinations.

## Phase A: Search Cards

Deduplicate the title/image anchors inside each `.property_item` by their
canonical detail URL. The first slug token is the stable numeric source code;
compose `ATB-{code}`. Card fields are:

| Column | Source | Handling |
|---|---|---|
| `id` | Numeric token after `/inmueble/` | Compose `ATB-{code}` |
| `portal` | Fixed | `arangotobon` |
| `tipo` | Card `h3` | Normalize; `Apto-Loft` becomes `apartaestudio` |
| `precio` | `.favroute2 p` | Shared price normalizer |
| `area` | `.property_meta` metric containing `m2` | Integer |
| `habitaciones` | `.property_meta` metric containing `Alcobas` | Integer |
| `banos` | `.property_meta` metric containing `Baños` | Integer; `1.0` becomes `1` |
| `parqueaderos` | Absent from sampled cards | Keep `0` |
| `estrato` | Absent from cards | Keep `0` until Phase B |
| `barrio` | Card location heading | Provisional only; replace with detail value |
| `url` | Detail anchor | Absolute official URL |

`Apto-Loft` is a distinct portal class, but the two sampled details call it
`Apartaestudio tipo loft`; normalize it to `apartaestudio` for the contract.

## Phase B: Detail Pages

Fetch every accepted card URL with `bulk_fetch`. Merge only detail fields
whose `Código` matches the card code:

| Column | Detail source |
|---|---|
| `estrato` | Table row `Estrato` |
| `barrio` | Table row `Barrio` |
| `parqueaderos` | `ul.bloques li` explicitly labelled `Parqueadero`/`Garaje` only |

The detail parser also reads the labelled `Baños` and `Alcobas` blocks for
verification, but card values remain authoritative for those fields. Narrative
mentions such as `parqueadero privado` are ignored. A successful detail without
a structured parking label proves the source absence and keeps
`parqueaderos = 0`.

Detail failures retain card values and defaults. Code mismatches are ignored
without changing the card identity.

## Zero-Genuineness and Risks

- `parqueaderos = 0` is genuine when the detail has no structured parking label.
- `estrato = 0` remains possible when a detail omits the table row.
- Root versus `/1` and duplicate title/image anchors require ID/URL deduplication.
- Slugs may change; the numeric code is the identity.
- The site is Cloudflare-fronted and should use the shared retrying fetcher.
- Detail narrative can disagree with structured data; structured labels win.
