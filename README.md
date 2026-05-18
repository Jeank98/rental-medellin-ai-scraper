# rental-medellin-ai-scraper

AI-agent-driven knowledge base for scraping real estate rental listings from Colombian portals. The agent discovers page structure dynamically — no hardcoded selectors. Output as CSV or to a PostgreSQL database.

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
The agent loads `real-estate-scraper` skill and follows the 4-phase workflow. By default, results are saved as CSV. If you want them in PostgreSQL, set up the database first (see below).

### 4. Database setup (optional)
If you want to save listings to PostgreSQL instead of CSV:
```bash
cp .env.example .env          # then edit .env with your DATABASE_URL
uv run python scripts/setup_db.py
uv run python scripts/test_save.py
```
The database is provider-agnostic — any PostgreSQL connection string works (Neon, Supabase, local, etc.).

## Project Structure
```
rental-medellin-ai-scraper/
├── AGENTS.md                        # Agent instructions
├── README.md                        # This file
├── .gitignore
├── .env.example                     # DB connection string template
├── db/
│   └── __init__.py                  # PostgreSQL connection, schema, ops
├── scripts/
│   ├── setup_db.py                  # Create listings table
│   ├── test_save.py                 # Test insert and read-back
│   └── insert_listings.py           # Bulk insert from JSON
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
├── reference/
│   ├── portal-field-mappings.md      # Index of all portal mappings
│   └── portals/                      # Individual portal files
│       ├── _TEMPLATE.md
│       ├── maxibienes.md
│       ├── arrendamientossantafe.md
│       ├── albertoalvarez.md
│       └── metrocasas.md
```

## Output Columns
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
| [Maxibienes](https://www.maxibienes.com) | `MXB` | ✅ Done (870) | [mapping](reference/portals/maxibienes.md) |
| [Arrendamientos SantaFe](https://arrendamientossantafe.com) | `ASF` | ✅ Done (1,128) | [mapping](reference/portals/arrendamientossantafe.md) |
| [Alberto Alvarez](https://albertoalvarez.com) | `AAL` | ✅ Done (650) | [mapping](reference/portals/albertoalvarez.md) |
| [Metrocasas](https://metrocasas.co) | `MTC` | ⚠️ Partial (57) | [mapping](reference/portals/metrocasas.md) |
| [Santillana](https://santillanasas.com) | `STL` | ✅ Done (72) | [mapping](reference/portals/santillana.md) |
| [Coninsa](https://www.coninsa.co) | `CON` | 🔲 Blocked (JS SPA) | [mapping](reference/portals/coninsa.md) |

## License
MIT
