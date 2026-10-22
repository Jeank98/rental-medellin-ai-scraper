# Escala Inmobiliaria (`ESC`)

- **URL**: `https://escalainmobiliaria.com.co/propiedades`
- **API**: `https://escalainmobiliaria.com.co/api/v2/propiedades`
- **Catalog API**: `https://escalainmobiliaria.com.co/api/v2/catalogos`
- **Type**: One-phase JSON REST API consumed by the public SPA
- **Portal**: `escalainmobiliaria`
- **Detail page**: `/propiedad/{codigo}` (identity/URL only; never fetched)
- **Auth**: none; the endpoint needs no custom headers, cookies, or tokens
- **Page size**: `limite` 1–100 (100 used by the scraper)
- **Pagination**: zero-based `pagina`, `total` records reported per response

## Request Parameters

The SPA sends three numeric query parameters. The API ignores English names
(`page`, `limit`) and city names, so only these are sent:

```text
/api/v2/propiedades?ciudad={city_id}&limite=100&pagina={zero_based_page}
```

| Canonical city key | `ciudad` id |
|---|---|
| `medellin` | 496 |
| `envigado` | 291 |
| `itagui` | 389 |
| `la-estrella` | 416 |
| `sabaneta` | 698 |

Type ids from `/api/v2/catalogos` are `Apartamento` 2, `Casa` 1, and
`Apartaestudio` 14. They identify accepted source types; the scraper does not
send a type filter, so every residential type for the city arrives in the same
page stream.

## Why No `tipOper` Filter

A `tipOper` filter is unreliable: rental records that the portal stores in the
Venta bucket disappear when scoping by operation. The scraper therefore queries
**all operations for the city** and guards each returned record locally:

1. `codigo` is present and usable.
2. `ciudad` is the exact requested city (numeric id or name, accent-folded).
3. `operacion` folds to exactly `arriendo`; Venta and mixed records are dropped.
4. `tipo` is exactly `Apartamento`, `Casa`, or `Apartaestudio` after folding.
   Mixed source labels such as `Casa-Finca` or `Local` are rejected instead of
   being collapsed by the shared type normalizer.

`total` still counts raw records, including records filtered out above. Progress
therefore uses raw returned records, never the accepted-rental count.

## Pagination Semantics

Each response is validated as `{propiedades: list, total: int}` before use. A
payload that carries only `message`/`error`, a malformed record, or a missing or
invalid `total` is a technical failure (raise), never an empty inventory.

The crawl is complete when the number of unique raw records reaches `total`.
Every raw record must carry a usable `codigo`; a missing or unusable code is an
integrity error raised before any progress is counted, never a synthetic
pagination identity or a silently skipped property. The loop also fails loudly
on:

- an empty page while fewer than `total` unique records were seen (premature
  empty / truncated pagination);
- a page whose codes were all seen before (repeated pagination);
- more unique records than `total`, or a `total` that changes between pages
  (inconsistent metadata).

`max_pages` caps requested pages explicitly. `sample_only` caps the crawl to one
page per city. Both are bounded partial inspections; their results must never be
stored or reported as a complete snapshot.

Verified pagination evidence: La Estrella (`ciudad=416`) with `limite=3` returns
3, 3, 3, 0 records on `pagina` 0, 1, 7, 8 and reports `total=24` with no overlap.

## Field Mapping

| Column | Source | Normalization |
|---|---|---|
| `id` | `codigo` | `ESC-{codigo}` |
| `portal` | Constant | `escalainmobiliaria` |
| `tipo` | `tipo` | Exact source type: `apartamento`, `casa`, `apartaestudio` |
| `precio` | `precio` | COP integer; decimal float strings are not digit-joined |
| `area` | `area` | `int(float(...))`, so `92.5` becomes `92` |
| `habitaciones` | `habitaciones` | Integer |
| `banos` | `banos` | Integer |
| `parqueaderos` | `parqueadero` | Integer; absent stays `0`, never inferred |
| `estrato` | `estrato` | Shared estrato normalizer, integer 1–6 |
| `barrio` | `barrio` | Shared barrio normalizer |
| `url` | `codigo` | `https://escalainmobiliaria.com.co/propiedad/{codigo}` |

## Notes

- No detail request is made: all eleven columns are present in the listing
  record.
- Duplicate stable codes keep their first-seen row.
- The canonical storage key for La Estrella is `la-estrella`; `La Estrella`,
  `la_estrella`, and `LA-ESTRELLA` all resolve to it.
- Multi-city calls hit each requested city exactly once and return one list per
  canonical key, including legitimate empty lists.
