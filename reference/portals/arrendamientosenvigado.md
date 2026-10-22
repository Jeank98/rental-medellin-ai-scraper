# Arrendamientos Envigado (`AEV`)

- **URL**: `https://arrendamientosenvigadosa.com.co/`
- **Type**: Next.js server-rendered detail pages (SSR labels + embedded Flight JSON)
- **Discovery**: `https://arrendamientosenvigadosa.com.co/sitemap.xml`
- **Detail URL**: `/inmueble/{tipo}-arriendo-{municipio}-{barrio}-{code}` (a cityless `/inmueble/{code}` redirects to this canonical form)
- **Listings per page**: not paginated; one detail page per inmueble
- **Key feature**: `robots.txt` disallows `/api/`, so discovery is sitemap-only and details are SSR-only. The verified sitemap held 1,633 `<loc>` entries and 952 rental detail candidates — evidence, not a guarantee of live completeness.

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | Detail label `Código` | `AEV-{code}` after confirming the sitemap and canonical codes match |
| `portal` | Fixed | `arrendamientosenvigado` |
| `tipo` | Canonical slug + H1 | Only `apartamento`/`apto`, `apartaestudio` and `casa` aliases; sale and explicit non-residential entries are rejected before `normalize_tipo` |
| `precio` | Primary SSR label `Precio de arriendo` | COP integer; first `COP`/`$` number; an empty required row raises instead of borrowing the next metric |
| `area` | Primary SSR label `Área construida` | First bounded number, decimal `m²` truncated; absent → `0` |
| `habitaciones` | Primary SSR label `Habitaciones` | First bounded integer; absent → `0` |
| `banos` | Primary SSR label `Baños` | First bounded integer; absent → `0` |
| `parqueaderos` | Primary SSR label `Parqueadero`/`Parqueaderos` | First bounded integer, **row omitted when 0**; never inferred from prose, amenity labels (`Parqueaderos visitantes`) or Flight JSON |
| `estrato` | Primary SSR label `Estrato` | `normalize_estrato`, only 1–6 kept |
| `barrio` | Canonical slug (or `og:image:alt`/H1 fallback) | Normalized title case |
| `url` | `<link rel="canonical">` (or `og:url`) | Absolute canonical detail URL |

**Data authority and guards**

- The canonical `/inmueble/` slug is authoritative for operation, residential type, municipality and barrio. Sitemap slugs are hints only.
- Unknown and cityless sitemap slugs are retained; code 80356 is a known cityless sitemap entry whose canonical detail resolves to Envigado / Primavera.
- The `Código` identity is validated against the sitemap and canonical codes **before** the sale/non-residential/out-of-scope municipality filters, so a mismatched response raises instead of being silently discarded.
- A detail is discarded when it is an explicit sale listing, an explicit non-residential type, or a municipality outside the requested cities. A named but unsupported municipality never leaks into another city scope.
- Code mismatches (sitemap vs canonical vs `Código`), canonical-vs-H1 operation disagreements and municipality conflicts (canonical vs H1 vs `og:image:alt`) raise `PortalParseError`; they never silently corrupt a row.
- `og:image:alt` states the verified bare `Municipio, Barrio` pair; only a first segment that is a supported municipality is used, and it is cross-checked against the canonical municipality.
- Each metric label is paired only with the value cell rendered immediately after it: the price card keeps `Precio de arriendo` and `$7.500.000` as adjacent `p` cells followed by the metrics `ul` (`Área construida`, `Habitaciones`, `Baños`…), and a metric row keeps its label and value `span`s inside one `li`. A metrics container, another label or an empty cell never supplies the value, so an empty row never borrows a following row, a sibling block or the rest of the parent container. Only whole structured labels match, so label-prefixed prose never supplies a value.
- Embedded Flight JSON and `<script>` blocks are removed before parsing, and recommendation blocks (class/id or `Otros resultados` heading) are excluded so their labels cannot contaminate the primary metrics.

**Dead pages vs failures**

- A detail is skipped only for the verified HTTP 200 soft-404: `robots noindex`, the site-root canonical **and** explicit text such as `Este inmueble ya no se encuentra disponible` all present.
- A `noindex` response without that complete evidence (challenge/interstitial, missing canonical, missing unavailable text) is a technical failure.
- An HTTP 200 alone is never treated as active. A page with missing required `Precio de arriendo`/`Código` labels, malformed sitemap XML, or a failed sitemap/detail fetch raises a portal error instead of publishing a partial dataset.

**Scrape model**

- Phase A: fetch the sitemap once (following sitemap-index children), classify and deduplicate detail candidates by stable `code`.
- Sitemap requests are read from the raw Scrapling `Response.body` (the server sends `application/xml`). Scrapling's `html_content` normalizes that document into `<html><body><urlset ...>`, so it is never used as the XML source. Only a document whose root is a correctly namespaced `urlset`/`sitemapindex` with absolute `http(s)` locs is accepted; an HTML wrapper, challenge page or malformed XML raises instead of producing an empty result.
- Phase B: fetch each selected detail once with the shared `bulk_fetch` (10 workers). Rows are grouped by the detail page's canonical municipality, so one call can serve all five southern cities without repeating the crawl.
- `max_pages` is a detail-batch budget: `100` details per batch for a normal run (`None` = all candidates). It is not a complete-snapshot switch.
- `sample_only` selects up to three hinted details per requested city plus a bounded unknown/cityless pool, so all requested cities are reached without fetching the whole sitemap. Details are processed in batches of at most 20 and at most three accepted listings are stored per city; `max_pages` further caps the sample budget at 20 details per batch. When an examined candidate is explicitly dead, a duplicate or a canonical municipality mismatch, the short city is replenished from its remaining hints and the unknown pool within that same budget, so the first few dead entries cannot produce a false empty city. Exhausting the budget while candidates remain logs that an empty city is unproven; only a fully examined candidate pool supports an empty sample. Sample output is not a complete snapshot.

**Notes**:

- No `/api/` endpoint, facets call or token is used; only `sitemap.xml` and `/inmueble/...` SSR pages are fetched.
- Read-only: the module never touches the database, CSV files or Google Sheets.
- The CLI canonicalizes `--ciudad` through the shared `resolve_city`, so `la estrella` stores under the existing `la-estrella` city scope.
