# Total Bienes SAS (`TB`)

- **Residential type URLs**:
  - `https://totalbienes.com/arriendo-apartamentos-medellin`
  - `https://totalbienes.com/arriendo-casas-medellin`
  - `https://totalbienes.com/arriendo-apartaestudios-medellin`
- **Completeness URLs**:
  - `https://totalbienes.com/properties/medellin`
  - `https://totalbienes.com/properties/medellin/pagina/2`
- **Type**: Single-phase rendered HTML cards
- **Listing cards**: Generic property anchors whose href contains `/property/{numeric}`
- **Canonical pagination**: the two completeness URLs above; the type URLs are single-page official landing sources with no pagination links.
- **Finite boundary**: fetch all three residential type URLs, then both numbered city pages. The baseline assessment had 8 apartment, 1 house, and 5 apartaestudio cards; current counts are inventory-dependent.
- **Permalink**: `https://totalbienes.com/property/{numeric}`
- **ID**: `TB-{numeric}`, matching the permalink suffix
- **Strategy**: one phase; type-source prefilter, numbered-page completeness union, first-seen ID deduplication, and final normalized-type guard; no detail requests

## Field Mapping

| Column | Source | Normalization |
|---|---|---|
| `id` | Visible `Código TB-{numeric}` or numeric property href | `TB-{numeric}` |
| `portal` | Constant | `totalbienes` |
| `tipo` | Card title before `en Arriendo` or `en Arriendo/Venta` | `normalize_tipo` |
| `precio` | Rental amount following `Arriendo` / `Valor arriendo` | COP integer; rental wins over sale |
| `area` | Number before `m²` / `m2` | Integer square metres |
| `habitaciones` | `habitaciones` / `habitación` / `alcobas` | Integer; non-residential source absence is `0` |
| `banos` | `baños` / `baño` | Integer; absent is `0` |
| `parqueaderos` | `parqueadero: Sí` or `No` | `Sí` = 1, `No` = 0 |
| `estrato` | `estrato N` | Integer 1-6 |
| `barrio` | Card location ending in `, Medellín` | Text before municipality |
| `url` | Card href | Absolute `https://totalbienes.com/property/{numeric}` |

## Residential Source Strategy

The three type URLs are the preferred source-level filters and currently
provide the residential set: `apartamento`, `casa`, and the accepted
residential subtype `apartaestudio`. The two numbered city URLs remain in the
crawl to retain canonical pagination coverage and catch records that move
between curated type pages and the city inventory.

Rows from all five sources are unioned by `TB-{numeric}` and keep the first
row seen. After normalization, only `apartamento`, `casa`, and
`apartaestudio` may enter output; `local`, `oficina`, `bodega`, and other
commercial types are discarded before final output. Cards marked `Casa
Comercial` or `Uso Comercial` are also discarded from card text or URL, even
when their normalized type is `casa`.

## Pagination Boundary

The baseline page-1 `Cargar más Propiedades` control appended page-2 repeats
and the observed `TB-1156` record, which was not present in that baseline's
numbered page-2 HTML. The scraper does not click or request that control. It
fetches only the two literal numbered routes and keeps the first row for each
ID as a defensive deduplication rule. If a load-more-only record later appears
on a numbered page, it is included once; otherwise it remains outside the
canonical boundary.

## Zero Genuineness

- `habitaciones` = `0` for `local`, `oficina`, `bodega`, `lote`, or `finca` when the card has no bedroom label. The verified Local sample omitted this field on both its card and the single permitted detail check.
- `parqueaderos` = `0` when the binary card label is `No` or is absent.
- No detail phase is required because the detail check added no contractual field.

## Risks

- Commercial `local` records are valid source records but must not be coerced into a residential type.
- Parking is binary; the site does not expose a count on the verified cards.
- Rental/sale coexistence requires selecting the rental amount.
