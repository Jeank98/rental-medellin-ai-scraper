# Metrocasas (`MTC`)

- **URL**: `https://metrocasas.co/new/property-search/?status=para-alquiler&type[]=apartaestudio&type[]=apartamento&type[]=casa&location[]=medellin`
- **Type**: JS-rendered WordPress (RealHomes theme)
- **Listing card**: No reliable CSS selector (server HTML has `data-property-title` attrs)
- **Listings per page**: 6
- **Total pages**: 12 (71 properties; 2026-05-18)
- **Pagination**: `/page/N/?query...` (WordPress URL structure)

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `MTC-{property_id}` | `data-property-id="118397"` in HTML |
| `portal` | `metrocasas` | Fixed |
| `tipo` | `data-property-title` | `"Apartaestudio en Barrio Cristobal"` → split on "en" |
| `precio` | Rendered text near "Para alquiler" | `$1,600,000` → `1600000` |
| `area` | Rendered text: `Área: N m2` | `280 m2` → `280` |
| `habitaciones` | Rendered text: `Habitaciones: N` | `2` → `2` |
| `banos` | Rendered text: `Cuartos de baño: N` | `1` → `1` |
| `parqueaderos` | **Not in card** | → `0` |
| `estrato` | **Not in card** (available as filter) | → `0` |
| `barrio` | `data-property-title` | `"Apartamento en Laureles"` → `Laureles` |
| `url` | `data-property-url` | Full absolute URL |

**Notes**:
- JS-rendered: fields only visible with browser rendering (webfetch/scrapling_fetch)
- Titles from `data-property-title` HTML attributes are reliable
- Field text (Habitaciones, Cuartos de baño, Área) requires rendered text extraction
- Barrio embedded in title: "TIPO en BARRIO" — needs parsing
- Area sometimes missing (apartaestudios without area)
- "Para alquiler, Para Venta" = dual listing — take first price (rental)
- "Oficina" type appears but was not in the filtered search
- 52 listings extracted (some pages had extraction issues due to JS rendering)
