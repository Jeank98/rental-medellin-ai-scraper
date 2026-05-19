# AGENTS.md — Rental Medellín AI Scraper

This project is a **knowledge base + tooling** for AI agents that scrape real estate rental listings from Colombian portals. It contains reference documentation, database integration, and Scrapling MCP configuration.

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
| `reference/portal-field-mappings.md` | Index of all portal mappings — see `reference/portals/` for individual files |
| `reference/portals/{name}.md` | Field mappings discovered for a specific portal |
| `db/__init__.py` | PostgreSQL connection, table schema, insert operations |
| `scripts/insert_listings.py` | Bulk insert listings from JSON into PostgreSQL |

### Workflow for scraping a new portal
1. Load `skills/real-estate-scraper/SKILL.md`
2. Follow its 4-phase workflow: Discovery → Bulk Scrape → Save (CSV or DB) → Report
3. When in doubt about a field mapping, consult `docs/variable-detection.md`
4. When a field is missing, follow `docs/decision-tree.md`
5. Report discovered field mappings back to `reference/portals/{portal_name}.md`

### Output standards
- Each listing must have exactly 11 columns in this order: `id, portal, tipo, precio, area, habitaciones, banos, parqueaderos, estrato, barrio, url`
- All numeric fields as plain integers (no formatting, no symbols)
- Missing numeric fields → `0` (never `N/A`, never empty)
- Missing string fields → empty string
- `id` format: `{PREFIX}-{CODE}`
- `tipo` normalized to lowercase: `apartamento`, `casa`, `apartaestudio`
- Output goes to CSV (`results/{portal}_arriendos_{ciudad}.csv`) or PostgreSQL (`DATABASE_URL` in `.env`); ask user per scrape

### Tool requirements
- Scrapling MCP must be configured in opencode.json (Docker: `pyd4vinci/scrapling`) — see `config/scrapling-mcp-setup.md`
- The `real-estate-scraper` skill must be installed in `~/.config/opencode/skills/`

### ⛔ NO REGEX RULE (mandatory)

**Zero static pattern matching.** This project uses Scrapling MCP tools (`scrapling_get`, `scrapling_screenshot`, `scrapling_bulk_get`) for ALL field extraction. The agent reads the rendered text output from Scrapling and uses its own reasoning to identify and extract fields — guided by `docs/variable-detection.md`.

**Never use:**
- `re.search`, `re.match`, `re.findall`, `re.compile` for field extraction
- Hardcoded CSS selectors (`.alcobas`, `.garaje`) in Python code
- Per-portal scraper scripts
- `adaptive_extractor.py` or any regex-based extraction

**Always use:**
- `scrapling_get` to fetch pages and see their content
- `scrapling_screenshot` for visually identifying icon-only fields
- `scrapling_bulk_get` for parallel multi-page extraction
- The agent's own reasoning to map text → 11 columns per `docs/variable-detection.md`

### MCP Limitation — Button Click / Scroll Fallback

Scrapling MCP does not expose `page_action` for clicks or scrolls. For "Load More" portals, use Python API:

```python
from scrapling import StealthyFetcher
from playwright.sync_api import Page

def click_load_more(page: Page):
    last = page.locator('text=Código:').count()
    while True:
        btn = page.locator('text=Cargar más inmuebles')
        if btn.count() == 0 or not btn.first.is_visible():
            break
        btn.first.click()
        page.wait_for_timeout(2000)
        current = page.locator('text=Código:').count()
        if current == last: break
        last = current

resp = StealthyFetcher.fetch(url, page_action=click_load_more, headless=True)
```

**Never hardcode click/scroll counts.** Stop when button disappears OR listing count stops growing.

See `reference/portals/coninsa.md` and `reference/portals/arrendamientosvillacruz.md` for full examples.
