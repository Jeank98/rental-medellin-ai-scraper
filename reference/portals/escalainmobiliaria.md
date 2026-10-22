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

The reported `total` is **advisory**, not a loop bound: the API recomputes it on
every request and Vercel caches each `pagina` URL independently
(`x-vercel-cache: HIT`/`STALE`, `age` up to ~316 s observed). Two pages of one
crawl therefore report different totals for the same inventory. Verified on
2026-10-22 for Medellín (`ciudad=496`, `limite=100`, fresh requests): `pagina`
0 reported `total=569`, page 1 reported 570, pages 2–6 reported 571; pages 1
and 2 each repeated the previous page's last code (one insertion shifts every
record down one slot), page 5 returned 71 records and page 6 returned 0.

Termination is the first **empty** `propiedades` array, which is authoritative:
the endpoint is a zero-based sequential window, so an empty page means the
offset is past the end of the result set. A full crawl must additionally have
seen at least the smallest `total` any page reported; otherwise records were
lost (repeated, skipped, truncated or inconsistent pages) and the crawl raises
instead of storing a partial inventory. The loop fails loudly on:

- an empty page while fewer than the smallest reported total were seen
  (premature empty / truncated pagination); totals carried by empty pages are
  ignored so a stale cached empty page cannot lower that floor;
- an empty first page whose total is non-zero (contradictory metadata);
- a page whose codes were all seen before (repeated pagination);
- more unique records than the largest reported total (contradictory metadata);
- a record without a usable `codigo` (integrity error raised before any
  progress is counted, never a synthetic pagination identity).

A transient upstream failure is retried: the API answers HTTP 200 with
`{"error": "No se pudieron cargar las propiedades", "detail": "The operation was
aborted due to timeout"}` and no `propiedades` key. Each page gets three
attempts (0.5 s apart) before the crawl names the failing city and page.

`max_pages` caps requested pages explicitly. `sample_only` caps the crawl to one
page per city. Both are bounded partial inspections; their results must never be
stored or reported as a complete snapshot.

`limite` is clamped server-side to 100: `limite=200`, `300`, `600` and `1000`
all returned exactly 100 records, so a single large page cannot replace paging.

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
