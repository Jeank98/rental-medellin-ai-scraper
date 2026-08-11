# Proser Inmobiliaria

- **Portal**: `proserinmobiliaria`
- **Prefix**: `PRO`
- **Official discovery search**: `https://proserinmobiliaria.com/s/alquiler`
- **Production scope**: Medellín residential rentals only
- **Strategy**: Two-phase server-rendered HTML

## Residential Sources

Use all three official type/rental sources. Each source carries the city,
property type, and rental business parameters before any card is fetched:

| Normalized type | Official source URL | `id_property_type` |
|---|---|---:|
| `apartamento` | `/s/apartamento/alquiler?id_city=496&id_property_type=2&business_type%5B0%5D=for_rent` | 2 |
| `casa` | `/s/casa/alquiler?id_city=496&id_property_type=1&business_type%5B0%5D=for_rent` | 1 |
| `apartaestudio` | `/s/apartaestudio/alquiler?id_city=496&id_property_type=14&business_type%5B0%5D=for_rent` | 14 |

The source landing pages link to the canonical paginated form:

`/search?id_city=496&id_property_type={TYPE_ID}&business_type%5B0%5D=for_rent&order_by=created_at&order=desc&page=N&for_sale=0&for_rent=1&for_temporary_rent=0&for_transfer=0&lax_business_type=1`

`Casa Campestre` is an accepted residential subtype normalized to `casa`.
`Loft` cards are accepted as `apartaestudio` only when the portal card tag is
`APARTAESTUDIO`.

## Pagination and Dedupe

Each typed source uses the `page` query parameter and 12 raw cards per page.
Walk a source until a page contains fewer than 12 raw cards. Deduplicate the
three source streams globally by the stable numeric detail code before Phase B.

## Phase A: Search Cards

Find absolute links whose path ends in a numeric code. The numeric suffix is
stable and becomes `PRO-{code}`. The card text supplies:

| Contract field | Mapping |
|---|---|
| `id` | Numeric detail URL suffix |
| `portal` | Fixed `proserinmobiliaria` |
| `tipo` | First recognized property-type text |
| `precio` | Amount immediately after the `Alquiler` label |
| `area` | Number before `Área`/`Area` |
| `habitaciones` | Number before `Alcoba`/`Alcobas` |
| `banos` | Number before `Baño`/`Baños` |
| `parqueaderos` | Number before `Garaje`/`Garajes` |
| `estrato` | Deferred to detail |
| `barrio` | Temporary title inference, replaced by detail |
| `url` | Absolute card detail link |

Some records expose both `Venta` and `Alquiler`; always select the amount
labeled `Alquiler`, never the sale amount.

Before queuing a detail URL, require all of the following:

- normalized `tipo` is `apartamento`, `casa`, or `apartaestudio`;
- the card has a non-zero amount labeled `Alquiler`;
- the card is not labeled `MARKETPLACE`.
- the card text and URL do not contain `CASA COMERCIAL` or `USO COMERCIAL`.

Sale-only cards are rejected even if their URL contains a numeric code. A
mixed `Venta`/`Alquiler` card with a sale slug is retained only because its
card explicitly supplies a rental offer, and its rental amount is selected.

## Phase B: Detail Pages

Fetch every accepted card URL with `bulk_fetch`. Merge only matching detail
codes. The labeled detail fields are:

- `Zona / barrio` → `barrio`
- `Estrato` → `estrato`
- `Área Construida` or `Área Privada` → `area` when the card omitted it
- `Alcoba`, `Baños`, and `Tipo de inmueble` as authoritative fallbacks

If the detail response is missing, the row is dropped rather than emitting
unresolved zeroes. A detail page without a particular label is the evidence
required before emitting numeric zero for that field.

## Data-quality guards

- Cards labeled `MARKETPLACE` are skipped by default. The official site marks
  these records separately, but first-party ownership cannot be established
  from the Proser page alone.
- Cards explicitly marked `CASA COMERCIAL` or `USO COMERCIAL` are skipped
  before detail fetching, even when the generic type normalizes to `casa`.
- The normalized-type guard runs again after detail merge, so a commercial
  detail cannot enter the final contract even if a source card is malformed.
- Fractional measurements are normalized with `Decimal` and explicit
  `ROUND_HALF_UP` rounding because the shared contract requires integers. The
  scraper logs every fractional value; it never silently truncates it. For
  example, `2.5` bathrooms becomes `3` with an anomaly warning.
- Card titles and URL slugs can disagree about the neighborhood. Detail
  `Zona / barrio` wins; the title is only a Phase A fallback.
- Commercial records may explicitly display `0` for bedrooms, bathrooms, or
  garages. Those zeros are accepted because the source displays them. Missing
  area or estrato is not defaulted from a card alone.
