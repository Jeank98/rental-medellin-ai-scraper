# AGENTS.md — Rental Medellín AI Scraper

This project is a **knowledge base + tooling** for AI agents that scrape real estate rental listings from Colombian portals. It contains scraping scripts, database integration, and reference documentation.

## What every agent working with this project must know

### Project purpose
Scrape rental property listings from any Colombian real estate portal, extract standardized fields, and output listings as a typed CSV or to a PostgreSQL database. The agent must discover page structure dynamically — no hardcoded selectors.

### Key files
| File | Purpose |
|---|---|
| `skills/real-estate-scraper/SKILL.md` | The page-agnostic scraping skill — load this first |
| `docs/columns-spec.md` | Exact column definitions, types, and normalization rules |
| `docs/variable-detection.md` | How to detect each field in unfamiliar HTML |
| `docs/scraping-rules.md` | Rules for exploration, field mapping, pagination, and output |
| `docs/decision-tree.md` | What to do when fields are missing or ambiguous |
| `config/scrapling-mcp-setup.md` | How to install and configure Scrapling MCP |
| `reference/portal-field-mappings.md` | Field mappings discovered for specific portals |
| `db/__init__.py` | PostgreSQL connection, table schema, insert operations |
| `scripts/insert_listings.py` | Bulk insert listings from JSON into PostgreSQL |

### Workflow for scraping a new portal
1. Load `skills/real-estate-scraper/SKILL.md`
2. Follow its 4-phase workflow: Discovery → Bulk Scrape → Save (CSV or DB) → Report
3. When in doubt about a field mapping, consult `docs/variable-detection.md`
4. When a field is missing, follow `docs/decision-tree.md`
5. Report discovered field mappings back to `reference/portal-field-mappings.md`

### Output standards
- Each listing must have exactly 11 columns in this order: `id, portal, tipo, precio, area, habitaciones, banos, parqueaderos, estrato, barrio, url`
- All numeric fields as plain integers (no formatting, no symbols)
- Missing numeric fields → `0` (never `N/A`, never empty)
- Missing string fields → empty string
- `id` format: `{PREFIX}-{CODE}`
- `tipo` normalized to lowercase: `apartamento`, `casa`, `apartaestudio`
- Output goes to CSV (`results/{portal}_arriendos_{ciudad}.csv`) or PostgreSQL (`DATABASE_URL` in `.env`); ask user per scrape

### Tool requirements
- Scrapling MCP must be configured in opencode.json
- The `real-estate-scraper` skill must be installed in `~/.config/opencode/skills/`
