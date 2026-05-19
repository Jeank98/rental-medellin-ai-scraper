# Arrendamientos Monserrate (`MNS`)

- **URL**: `https://www.arrendamientosmonserrate.com/inmuebles/?swoof=1&product_cat=arrendamiento`
- **Type**: WordPress + WooCommerce + BeTheme
- **Listing card**: `<li>` with CSS classes containing field slugs
- **Listings per page**: 12
- **Total pages**: 5 — discovered from `<div class="pages">` pagination links
- **Pagination**: `/inmuebles/page/{N}/?swoof=1&product_cat=arrendamiento`
- **Key feature**: **Two-tier data model** — cards show only barrio+precio; ALL other fields on detail pages

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `MNS-{code}` | Detail page `Código: NNNN` — fallback: image filename `NNNNN-N.jpeg` |
| `portal` | `arrendamientosmonserrate` | Fixed |
| `tipo` | Detail `Tipo de inmueble: X` | Normalize lowercase |
| `precio` | Card `$N.NNN` | Strip `$` and `.` |
| `area` | Detail `Área: Nm2` | Strip unit |
| `habitaciones` | Detail `Alcobas: N` | Integer |
| `banos` | Detail `Baños: N` | Integer |
| `parqueaderos` | Detail `Garaje: X` — **TEXTUAL, never numeric** | "si"/"Cubierto"/"Zona de parqueo"→1, "Doble"→2, "No"/"Sin"→0 |
| `estrato` | Detail `Estrato: N` | "Comercial"→0, absent→0 |
| `barrio` | Detail `Sector: X` | String |
| `url` | Card `<a href>` | Absolute URL |

**Garaje text→number mapping:**
| Text | Value |
|------|:---:|
| si, Si., Cubierto, semicubierto, Zona de parqueo, Descubierto | 1 |
| Doble, Doble en paralelo, Doble lineal | 2 |
| No., Sin garaje, absent | 0 |

**Notes**:
- **Two-phase scrape required**: Phase A gets URLs from 5 listing pages. Phase B fetches each detail page for full fields.
- Detail fields are in label-value format without colons: `Alcobas\n3` (label on one line, value on next)
- Código not visible on all detail pages — fallback to image filename or skip
- 32 of 55 listings fully extracted (2026-05-18) — some detail pages missing Código
