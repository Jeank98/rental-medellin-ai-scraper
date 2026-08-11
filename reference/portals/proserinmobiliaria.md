# Proser Inmobiliaria

- **Portal**: `proserinmobiliaria`
- **Prefix**: `PRO`
- **Official search**: `https://proserinmobiliaria.com/s/alquiler`
- **Canonical Medellín rental route**: `/search?id_city=496&business_type%5B0%5D=for_rent&order_by=created_at&order=desc&page=N&for_sale=0&for_rent=1&for_temporary_rent=0&for_transfer=0&lax_business_type=1`
- **Strategy**: Two-phase server-rendered HTML

## Pagination

The canonical route uses the `page` query parameter and 12 cards per page. It
must be walked until a page contains fewer than 12 raw cards. The verified
Medellín sample had 47 cards over four pages (`12 + 12 + 12 + 11`).

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
- Fractional measurements are normalized with `Decimal` and explicit
  `ROUND_HALF_UP` rounding because the shared contract requires integers. The
  scraper logs every fractional value; it never silently truncates it. For
  example, `2.5` bathrooms becomes `3` with an anomaly warning.
- Card titles and URL slugs can disagree about the neighborhood. Detail
  `Zona / barrio` wins; the title is only a Phase A fallback.
- Commercial records may explicitly display `0` for bedrooms, bathrooms, or
  garages. Those zeros are accepted because the source displays them. Missing
  area or estrato is not defaulted from a card alone.
