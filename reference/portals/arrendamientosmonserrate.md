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
| `tipo` | Detail `table.shop_attributes` row (`<th>` `Tipo de inmueble`, `<td>` value) | Normalize lowercase |
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
