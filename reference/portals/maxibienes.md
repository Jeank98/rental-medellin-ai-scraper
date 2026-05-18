# Maxibienes (`MXB`)

- **URL**: `https://www.maxibienes.com/resultados-de-la-busqueda-de-inmueble/?gestion=1&ciudad=5001`
- **Type**: Server-rendered PHP
- **Listing card**: `.grid-style1 .item`
- **Listings per page**: 12
- **Total pages**: 73 (870 properties, all tipos — no filter; 2026-05-18)
- **Pagination**: `/pagina/N?query` (no trailing slash before `?`)
- **Pagination values**: discovered dynamically from `var totalInmuebles` and `var totalpagina` in page HTML

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `MXB-{code}` | Code from first `<li>` in `.amenities` |
| `portal` | `maxibienes` | Fixed |
| `tipo` | `<h3>` text before `<br>` | `APARTAMENTO` → `apartamento` |
| `precio` | `.price span` | `$ 1.450.000` → `1450000` |
| `area` | `.amenities li` with `fa-compress` icon | `50 m²` → `50` |
| `habitaciones` | `.amenities li` with `fa-bed` icon | `2` → `2` |
| `banos` | `.amenities li` with `fa-bath` icon | `1` → `1` |
| `parqueaderos` | `.amenities li` with `fa-warehouse` icon | `0` → `0` |
| `estrato` | `<h3>` text | `Estrato: 3` → `3` |
| `barrio` | `.image .location` | `Barrio: Loreto` → `Loreto` |
| `url` | `.image a[href]` | Full absolute URL |

**Notes**:
- All fields available in listing cards
- Icons use FontAwesome classes: `fa-compress` (area), `fa-bath` (bathrooms), `fa-bed` (bedrooms), `fa-warehouse` (parking)
- 6 listings had anomalous parking values: (11, 35, 11, 141, 2611, 1061) — source data errors
- `ARRIENDO/VENTA` listings have `$ $ X / $Y` format — split on `/`, take first for rental
- 69 listings have `estrato=7` (Colombia max is 6) — source data errors
- Property types (2026-05-18): apartamento (415), local (203), apartaestudio (99), casa (84), oficina (50), bodega (17), lote (1), finca (1)
