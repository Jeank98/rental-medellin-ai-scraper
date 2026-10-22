# Lonja Inmobiliaria del Sur (`LJS`)

- **URL**: `https://www.lonjainmobiliariadelsur.com/inmuebles/Arriendo/clases_Apartamento_Apartaestudio_Casa/municipios_Itag%C3%BC%C3%AD_Envigado_La-Estrella_Sabaneta_Medell%C3%ADn`
- **Type**: Server-rendered HTML (static two-phase: results cards → detail table)
- **Portal**: `lonjainmobiliariadelsur`
- **Prefix**: `LJS`
- **Strategy**: One combined discovery route for every requested municipality, then one detail fetch per unique source code
- **Card selector**: `.property_item`
- **Detail page**: same host, numeric source code in the slug (for example `/inmueble/4009-...`)
- **Pagination**: page 1 is the route root; later pages append `/2`, `/3`, ...
- **Observed inventory**: 16 cards per page; the combined five-city/three-class route returned 16 + 16 + 9 = 41 cards, and page 4 was empty.

## Search Filters

The portal expresses filters in the URL path, not in query parameters:

`/inmuebles/Arriendo/clases_Apartamento_Apartaestudio_Casa/municipios_{city tokens}/`

- `clases_` accepts `Apartamento`, `Apartaestudio`, `Casa` joined by `_`.
- `municipios_` accepts source municipality names joined by `_`.
- Municipality names keep their source accents and must be percent-encoded:
  `Itag%C3%BC%C3%AD` (Itagüí), `Medell%C3%ADn` (Medellín).
- Multi-word names use a hyphen: `La-Estrella`. `La Estrella`, `la_estrella`,
  spaces and underscores are all normalized to the storage key `la-estrella`
  by `scrape.cities`.
- The published route lists municipalities as Itagüí, Envigado, La-Estrella,
  Sabaneta, Medellín; the scraper reuses that order so the all-cities URL is
  byte-for-byte the verified one.
- The root URL and `/1` return the same page; only the root is fetched.

An earlier guessed route (`/Arriendo/Apartamento/Itagui`) is not a filter at
all: it returned 73 mixed source classes and municipalities. Use only the
`clases_`/`municipios_` grammar above.

## Phase A: Search Cards

Deduplicate cards by their leading numeric source code, which is also the
identity used for `LJS-{code}`. Card fields:

| Column | Source | Handling |
|---|---|---|
| `id` | Numeric token in the detail slug | Compose `LJS-{code}` |
| `portal` | Fixed | `lonjainmobiliariadelsur` |
| `tipo` | Card `h3` source class | Accept only `Apartamento`, `Casa`, `Apartaestudio` |
| `precio` | `.favroute2 p` | Rental side of a combined price (see below) |
| `area` | `.property_meta` metric containing `m2` | Integer |
| `habitaciones` | `.property_meta` metric containing `Alcobas` | Integer |
| `banos` | `.property_meta` metric containing `Baños` | Integer |
| `parqueaderos` | Absent from cards | `0` until Phase B |
| `estrato` | Absent from cards | `0` until Phase B |
| `barrio` | Not taken from cards | Filled from the detail table only |
| `url` | Detail anchor | Absolute same-host URL, query/fragment removed |

`Casa-Finca` and `Casa-Local` are different products from `Casa`. The source
class is compared before `normalize_tipo` can split on the hyphen and collapse
them into `casa`; unsupported classes are dropped from the published rows while
their raw source codes still count toward page size and the declared total. A
page whose cards expose no source code at all aborts the crawl instead of
reporting an empty inventory.

The operation is a separate gate. The detail slug spells it as hyphen-delimited
tokens (`...-arriendo-...`, `...-arriendo-o-venta-...`, `...-venta-...`), so a
card whose slug declares sale-only is rejected before parsing. The route being
`/Arriendo/` is not sufficient evidence: the slug, and then the detail heading,
must both agree that the record is for rent or for rent and sale.

The card location heading (`.proerty_text h4`) often ends with the municipality
and is **not** a barrio. It is never published; the detail table is the only
barrio source. It is only used as a municipality *hint* to schedule a bounded
detail sample.

## Phase B: Detail Pages

Every discovered card is fetched once with `bulk_fetch`, or only the bounded
scheduled subset in sample mode. The detail page is a server-rendered table plus
labelled blocks:

| Column | Detail source |
|---|---|
| Identity check | Table row `Código` must equal the card's numeric code |
| City scope | Table row `Municipio` (authoritative) |
| Operation | Heading `<h1>`: `{Tipo} para Arriendo`, `{Tipo} para Arriendo o Venta`, `{Tipo} para Venta` |
| `barrio` | Table row `Barrio` |
| `estrato` | Table row `Estrato` |
| `precio` | Table row `Precio`, only when the card price is missing |
| `area`, `habitaciones`, `banos` | Card values win; detail fills zeros |
| `parqueaderos` | `ul.bloques li` explicitly labelled `Parqueadero`/`Garaje` only |

A detail whose heading states `Venta` without `Arriendo` is a sale-only record
leaked into the rental route: it is dropped, never published. A heading that
states no operation cannot verify the record and aborts the crawl.

Detail failure semantics are strict: a missing response, an anti-bot
interstitial, a missing `Código`, a code mismatch, a missing `Municipio`, or an
operation-less heading raises instead of publishing card defaults. Partial
datasets are never returned as snapshots.

## City Grouping

One discovery stream serves every requested city. Each listing is grouped by
its **detail** `Municipio`, normalized with `scrape.cities.normalize_city`:

- `Itagüí` → `itagui`
- `La Estrella` → `la-estrella` (existing database key; never `la estrella`)
- `Medellín` → `medellin`

A detail whose municipality is outside the requested set is logged and
skipped, so a wrong-source record can never leak into another database scope.
Canonical listing rows never contain a `ciudad` field; the runner owns city
scoping.

## Sample Mode and Page Caps

- `max_pages` limits listing pages only and must be at least 1.
- `sample_only` without `max_pages` reads one listing page for a single city
  and up to three pages when several cities are requested, so every requested
  city can contribute cards.
- The detail sample is scheduled **before** any detail request: at most three
  cards per requested city, chosen by the card location's municipality hint.
  Slots a city cannot fill from hinted cards are filled from a bounded pool of
  cards whose location names no supported municipality, so the schedule never
  exceeds three requests per requested city.
- Hints are not authority. The detail `Municipio` decides the published city,
  so a hinted candidate may end up skipped (another municipality) and no city's
  published sample exceeds three rows.
- Sample output keeps at most three listings per city; it is a probe, never a
  complete snapshot.

## Pagination and the Declared Total

- Every results page states its count as `N Encontrados`. That header is parsed
  on every page, not only the first.
- Page size, repeat detection and progress are measured on the raw source codes
  carried by the cards, before type/operation acceptance and with duplicate
  codes removed. Rejected classes still consume a page slot and still count
  toward the declared total, so they never cause a false page end or a false
  incompleteness failure.
- A page that renders cards and declares a different total from an earlier page
  aborts the crawl.
- When the declared total is reached, pagination stops; the full snapshot
  requirement compares it against the raw source codes collected, not against
  the accepted rows.

## Failure Versus Legitimate Empty

- Page 1 with zero cards is a legitimate empty city only when it explicitly
  states `0 Encontrados` (or another explicit no-results phrase). `0
  encontrados` must not be matched as a substring of `40 encontrados`.
- Page 1 with zero cards and no explicit zero (including a challenge or unknown
  HTML page) is a technical failure.
- A cardless page that still declares a nonzero result total aborts discovery,
  even if earlier pages did not declare their total.
- A cardless later page must explicitly show zero results or a no-results phrase;
  generic HTML is a technical failure, not proof of pagination completion.
- A repeated page (no new raw source codes) → technical failure; pagination is
  not advancing.
- A page with fewer than 16 raw cards ends pagination when the portal does not
  declare a total.
- When the page declares a total and pagination stops before collecting it, the
  crawl raises instead of returning a partial snapshot.
- A Cloudflare interstitial (`Just a moment`, `challenge-platform`, ...) →
  technical failure.

## Zero-Genuineness and Risks

- `parqueaderos = 0` is genuine when no structured parking block exists;
  narrative mentions of parking and building amenities are ignored, and blocks
  labelled for visitor or communal parking never count as private parking.
- `estrato = 0` remains possible when the detail omits its table row.
- Listings offered for rent and sale print the rental price first:
  `$1,500,000 - $260,000,000` must yield `1500000`. Digit-joining the whole
  string would overflow the integer column.
- The card class label is read from `h3`; if the portal renames its classes the
  scraper raises rather than dropping inventory silently. Re-verify the
  `clases_` tokens before changing the allowlist.
- The result total is read from the page's own `N Encontrados` header. When a
  page carries no header, pagination falls back to the observed
  16-cards-per-page rule and the crawl never claims completeness.
- The site is Cloudflare-fronted; the shared retrying fetcher is used and no
  browser is needed.
