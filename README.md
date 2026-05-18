# rental-medellin-ai-scraper

AI-agent-driven knowledge base for scraping real estate rental listings from Colombian portals. The agent discovers page structure dynamically — no hardcoded selectors, no runtime code, no scraped data stored here.

## Quick Start

### 1. Install Scrapling MCP
See [`config/scrapling-mcp-setup.md`](config/scrapling-mcp-setup.md).

```bash
brew install scrapling
```

Add to `~/.config/opencode/opencode.json`:
```json
"scrapling": {
  "command": ["/opt/homebrew/bin/scrapling", "mcp"],
  "enabled": true,
  "type": "local"
}
```

### 2. Install the skill
```bash
cp -r skills/real-estate-scraper ~/.config/opencode/skills/
```
Reload OpenCode.

### 3. Scrape a portal
In OpenCode, say:
```
Scrape rental listings from https://example.com/propiedades/?bussines_type=Arrendar
```
The agent loads `real-estate-scraper` skill and follows the 4-phase workflow.

## Project Structure
```
rental-medellin-ai-scraper/
├── AGENTS.md                        # Agent instructions
├── README.md                        # This file
├── .gitignore                       # No CSVs, no data
├── skills/
│   └── real-estate-scraper/
│       └── SKILL.md                 # Page-agnostic scraping skill
├── docs/
│   ├── columns-spec.md              # Column definitions and types
│   ├── variable-detection.md        # Field detection strategies
│   ├── scraping-rules.md            # Rules for scraping any portal
│   └── decision-tree.md             # Missing-field decision logic
├── config/
│   └── scrapling-mcp-setup.md       # Scrapling MCP setup guide
└── reference/
    └── portal-field-mappings.md      # Discovered field mappings per portal
```

## CSV Output Columns
| # | Column | Type | Description |
|---|--------|------|-------------|
| 1 | `id` | str | Composite key `{PREFIX}-{CODE}` |
| 2 | `portal` | str | Portal identifier |
| 3 | `tipo` | str | `apartamento`, `casa`, `apartaestudio` |
| 4 | `precio` | int | Rental price (digits only) |
| 5 | `area` | int | Square meters |
| 6 | `habitaciones` | int | Bedrooms |
| 7 | `banos` | int | Bathrooms |
| 8 | `parqueaderos` | int | Parking spots |
| 9 | `estrato` | int | Socioeconomic level (1-6, Colombia) |
| 10 | `barrio` | str | Neighborhood |
| 11 | `url` | str | Property detail page URL |

## Portals Scraped
| Portal | Prefix | Status | Reference |
|--------|--------|--------|-----------|
| [Maxibienes](https://www.maxibienes.com) | `MXB` | ✅ Done | See `reference/portal-field-mappings.md` |
| [Arrendamientos SantaFe](https://arrendamientossantafe.com) | `ASF` | 🔲 Discovery complete (99 pages), bulk scrape pending | Field mapping done, see `reference/portal-field-mappings.md` |

## License
MIT
