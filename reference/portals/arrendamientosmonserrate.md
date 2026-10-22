# Arrendamientos Monserrate (`MNS`)

- **URL**: `https://www.arrendamientosmonserrate.com/inmuebles/?swoof=1&product_cat=arrendamiento`
- **Type**: WordPress + WooCommerce + BeTheme
- **Listing card**: `<li>` with CSS classes containing field slugs
- **Listings per page**: 12
- **Total pages**: 5 — discovered from `<div class="pages">` pagination links
- **Pagination**: `/inmuebles/page/{N}/?swoof=1&product_cat=arrendamiento`
| **Key feature** | **Two-tier data model** — cards show only barrio+precio; all other fields are on detail pages |

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `MNS-{code}` | Detail `span.sku_wrapper span.sku`; fallback `MNS-URL-{sha256(url)[:12]}` |
| `portal` | `arrendamientosmonserrate` | Fixed |
| `tipo` | Detail `table.shop_attributes` row (`<th>` `Tipo de inmueble`, `<td>` value) | Trim source punctuation, map `casa unifamiliar`→`casa`, normalize lowercase |
| `precio` | Card `$N.NNN` | Strip `$` and `.` |
| `area` | Detail attributes row `<th>` `Área`/`Area` | First bounded integer, max 10,000; absent→0 |
| `habitaciones` | Detail attributes row `<th>` `Alcobas`/`Habitaciones` | First valid integer in 0–20; absent→0 |
| `banos` | Detail attributes row `<th>` `Baños`/`Banos` | First valid integer in 0–20; absent→0 |
| `parqueaderos` | Detail attributes row `<th>` `Garaje` | Existing textual mapping: "si"/"Cubierto"/"Zona de parqueo"→1, "Doble"→2, "No"/"Sin"→0 |
| `estrato` | Detail attributes row `<th>` `Estrato` | Normalize 1–6; "Comercial"→0; absent→0 |
| `barrio` | Detail attributes row `<th>` `Sector` | Clean and title-case value |
| `url` | Card `<a href>` | Absolute URL |

**Detail parsing scope:** only `table.shop_attributes` rows with an exact label in the table header and `span.sku_wrapper`/`span.sku` are read. Sidebar `<select>/<option>` values and page prose are ignored.

**Garaje text→number mapping:**
| Text | Value |
|------|:---:|
| si, Si., Cubierto, semicubierto, Zona de parqueo, Descubierto | 1 |
| Doble, Doble en paralelo, Doble lineal | 2 |
| No., Sin garaje, absent | 0 |

**Notes**:
- **Two-phase scrape required**: Phase A gets URLs from 5 listing pages. Phase B fetches each detail page for full fields.
- Detail attributes use `<tr><th>label</th><td>value</td>` rows; missing rows remain `0`.
- Some detail pages lack a SKU; fallback IDs are deterministic hashes of each detail URL.
- 32 of 55 listings fully extracted (2026-05-18) — some detail pages missing Código

## Rate limiting (`HTTP 429`)

The host (LiteSpeed) throttles by IP and answers `429` **without** a
`Retry-After` header, then keeps the IP in a cooldown that outlasts the shared
fetcher's 1-2-4 s retry budget.

Measured on 2026-10-20:

| Pattern | Result |
|---|---|
| 5 listing pages, 1 s apart | all `200` |
| 8 detail pages, 1 s apart | all `200` |
| 8 detail pages, 4 concurrent | all `200` |
| 56 detail pages, 4 concurrent | 42 × `429`, block persisted for minutes |
| 12 detail pages, 5 req/s | 12 × `429` |

Consequences baked into the adapter:

- Listing pages are fetched with a 1 s pause between them.
- Detail pages are fetched **one at a time, ~1 req/s** (`_DETAIL_BATCH_SIZE = 1`,
  `_DETAIL_MAX_WORKERS = 1`, `_DETAIL_BATCH_PAUSE_SECONDS = 1.0`).
- Unresolved details get one retry after 60 s. If more than 20 % of the detail
  pages still fail, the scraper raises and the portal keeps its previous
  snapshot instead of writing card-only rows with `MNS-URL-…` ids.
- `--reuse-unchanged-details` (enabled by `run_all.py`) is the main lever: rows
  whose price did not change need no detail fetch at all.

Do not raise the detail concurrency or add proxy/IP rotation to get around the
site's throttle; slow down, run less often, or ask the portal for API access.

