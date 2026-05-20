# rental-medellin-ai-scraper

AI-agent-driven knowledge base for scraping real estate rental listings from Colombian portals. The agent discovers page structure dynamically — no hardcoded selectors. Output as CSV or to a PostgreSQL database.

## Quick Start

```bash
# Run all 12 portals at once:
uv run python scripts/run_all.py --workers 12

# Run a single portal:
uv run python scripts/scrape_maxibienes.py --output db

# Health check only (no scrape):
uv run python scripts/run_all.py --skip-health --workers 12
```

### Setup

#### 1. Scrapling MCP
See [`config/scrapling-mcp-setup.md`](config/scrapling-mcp-setup.md).

**Docker (recommended):**
```bash
docker pull pyd4vinci/scrapling
```

Add to `~/.config/opencode/opencode.json`:
```json
{
  "mcp": {
    "scrapling": {
      "command": ["docker", "run", "-i", "--rm", "pyd4vinci/scrapling", "mcp"],
      "enabled": true,
      "type": "local"
    }
  }
}
```

#### 2. Install the skill
```bash
cp -r skills/real-estate-scraper ~/.config/opencode/skills/
```

#### 3. Scrape a portal
In OpenCode, say:
```
Scrape rental listings from https://example.com/propiedades/?bussines_type=Arrendar
```
The agent loads `real-estate-scraper` skill and follows the 4-phase workflow.

#### 4. Database setup (optional)
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
├── scrape/                          # Shared scraper package
│   ├── __init__.py                  # Re-exports: fetcher, normalize, validate, writers
│   ├── cli.py                       # Shared CLI argument parser + run_scraper helper
│   ├── fetcher.py                   # fetch_page, fetch_json, bulk_fetch via Scrapling
│   ├── normalize.py                 # Field normalizers (price, tipo, estrato, barrio, etc.)
│   ├── validator.py                 # Output validation
│   ├── csv_writer.py                # CSV output writer
│   ├── db_writer.py                 # Direct-to-DB INSERT/DELETE operations
│   ├── report.py                    # Box-drawn console report formatter
│   ├── orchestrator.py              # 5-phase pipeline: health → scrape → validate → backup → report
│   ├── maxibienes.py                # MXB scraper
│   ├── albertoalvarez.py            # AAL scraper
│   ├── alnago.py                    # ALN scraper (JSON API)
│   ├── arrendamientosdelnorte.py    # ADN scraper
│   ├── arrendamientosmonserrate.py  # MNS scraper
│   ├── arrendamientossantafe.py     # ASF scraper
│   ├── arrendamientosvillacruz.py   # AVC scraper (Selenium Load More)
│   ├── coninsa.py                   # CON scraper (Selenium Load More)
│   ├── habitamos.py                 # HBM scraper
│   ├── merinohermanos.py            # MHR scraper (JSON API)
│   ├── metrocasas.py                # MTC scraper
│   └── santillana.py                # STL scraper
├── scripts/                         # Thin CLI entry points
│   ├── run_all.py                   # Orchestrator: runs all 12 portals in parallel
│   ├── scrape_maxibienes.py
│   ├── scrape_albertoalvarez.py
│   ├── scrape_alnago.py
│   ├── scrape_adn.py
│   ├── scrape_monserrate.py
│   ├── scrape_asf.py
│   ├── scrape_villacruz.py
│   ├── scrape_coninsa.py
│   ├── scrape_habitamos.py
│   ├── scrape_merinohermanos.py
│   ├── scrape_metrocasas.py
│   ├── scrape_santillana.py
│   ├── setup_db.py                  # Create listings table
│   ├── test_save.py                 # Test insert and read-back
│   ├── insert_listings.py           # Bulk insert from JSON
│   └── export_to_sheets.py          # Export DB to Google Sheets
├── db/
│   └── __init__.py                  # PostgreSQL connection and schema
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
│   └── portals/                      # Individual portal files (12 portals)
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

## Portal Coverage

| # | Portal | Prefix | Strategy | Script |
|---|--------|--------|----------|--------|
| 1 | Maxibienes | `MXB` | Single-phase | `scrape_maxibienes.py` |
| 2 | Alberto Alvarez | `AAL` | Single-phase | `scrape_albertoalvarez.py` |
| 3 | Alnago | `ALN` | Two-phase (JSON API → detail) | `scrape_alnago.py` |
| 4 | Arrendamientos del Norte | `ADN` | Single-phase | `scrape_adn.py` |
| 5 | Arrendamientos Monserrate | `MNS` | Two-phase (detail pages) | `scrape_monserrate.py` |
| 6 | Arrendamientos SantaFe | `ASF` | Two-phase (detail pages) | `scrape_asf.py` |
| 7 | Arrendamientos Villa Cruz | `AVC` | Single-phase + Selenium Load More | `scrape_villacruz.py` |
| 8 | Coninsa | `CON` | Single-phase + Selenium Load More | `scrape_coninsa.py` |
| 9 | Habitamos | `HBM` | Single-phase | `scrape_habitamos.py` |
| 10 | Merino Hermanos | `MHR` | Single-phase (JSON API) | `scrape_merinohermanos.py` |
| 11 | Metrocasas | `MTC` | Single-phase | `scrape_metrocasas.py` |
| 12 | Santillana | `STL` | Two-phase (detail pages) | `scrape_santillana.py` |

## Requirements

- **Python 3.10+** with `uv` package manager
- **PostgreSQL** (any provider) if using `--output db`
- **pg_dump** (in `$PATH`) for automated DB backups via `run_all.py`
- **Scrapling MCP** (Docker or Python) for page fetching
- **Chromium/Chrome** for Selenium-based portals (Villa Cruz, Coninsa)

## Orchestrator Output

`run_all.py` produces a box-drawn console report with 5 sections:

```
╔══════════════════════════════════════════════════╗
║           SCRAPER ORCHESTRATOR REPORT            ║
║                 2024-05-20 14:30:00              ║
╠══════════════════════════════════════════════════╣
║                  HEALTH CHECK                    ║
║     ✅ maxibienes       30 listings    5s        ║
║     ✅ albertoalvarez   52 listings    8s        ║
║     ❌ habitamos       (timeout)       -         ║
╠══════════════════════════════════════════════════╣
║                 SCRAPE RESULTS                   ║
║     ✅ maxibienes      285 listings   45s        ║
║     ✅ albertoalvarez  412 listings   72s        ║
╠══════════════════════════════════════════════════╣
║              VALIDATION: PASSED                  ║
╠══════════════════════════════════════════════════╣
║         BACKUP: ~/Backups/rental_...sql          ║
║   DB UPDATE: 2,345 listings across 10 portals    ║
║            TOTAL TIME: 3m 42s                    ║
╚══════════════════════════════════════════════════╝
```

## License
MIT
