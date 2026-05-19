# Metrocasas (`MTC`)

- **URL**: `https://metrocasas.co/new/property-search/?status=para-alquiler&type[]=apartaestudio&type[]=apartamento&type[]=casa&location[]=medellin`
- **Type**: JS-rendered WordPress (RealHomes theme)
- **Listing card**: No reliable CSS selector (use `data-property-title` attrs)
- **Listings per page**: 6
- **Total pages**: 12 (71 properties; 2026-05-18)
- **Pagination**: `/page/N/?query...`
- **Key feature**: **Scrapling MCP `get` renders JS natively** — no Docker Chrome needed anymore

## Scraping Strategy

**MCP-native:** `scrapling_get` renders the JS content. All listing fields visible in text output.

```
scrapling_get(
  url: "{url}",
  extraction_type: "text",
  main_content_only: true
)
```

The rendered text shows listings with titles "TIPO en BARRIO", prices, and fields (Habitaciones, Cuartos de baño, Área).

**Previous approach (deprecated):** Docker Chrome + `Selector(content=html)` — MCP tools replace this entirely.

## Field Mappings

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `MTC-{property_id}` | `data-property-id="118397"` in server HTML or from card context |
| `portal` | `metrocasas` | Fixed |
| `tipo` | Card title: "TIPO en BARRIO" | `Apartamento` → `apartamento` |
| `precio` | Near "Para alquiler" | `$1,600,000` → `1600000` |
| `area` | "Área: N m2" | `95 m2` → `95` |
| `habitaciones` | "Habitaciones: N" | `2` → `2` |
| `banos` | "Cuartos de baño: N" | `1` → `1` |
| `parqueaderos` | **Not in card** | → `0` |
| `estrato` | **Not in card** (available as filter) | → `0` |
| `barrio` | Card title: "TIPO en BARRIO" or "TIPO BARRIO" | `Laureles` |
| `url` | `data-property-url` or from title construction | Full absolute URL |

**Notes**:
- MCP `scrapling_get` renders JS — no browser/fetch needed
- Titles may use "en" or omit it: "Apartamento en Laureles" or "Apartaestudio La America"
- 71 listings extracted with MCP-native approach
- Area missing for some apartaestudios
