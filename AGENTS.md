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
2. **CHECK `reference/portal-field-mappings.md` FIRST** — if portal exists, load its individual file from `reference/portals/{name}.md`. This gives you the card selector, pagination pattern, known field mappings, and portal-specific gotchas. Skip Phase 1 Discovery — go straight to bulk scrape.
3. If portal is NOT in the index, follow the full 4-phase workflow: Discovery → Bulk Scrape → Save (CSV or DB) → Report
4. When in doubt about a field mapping, consult `docs/variable-detection.md`
5. When a field is missing, follow `docs/decision-tree.md`
6. Report discovered field mappings back to `reference/portals/{portal_name}.md`

### Portal knowledge recycling (MANDATORY)

**When a user asks to scrape a known portal:** Load `reference/portals/{name}.md` immediately. Do NOT re-discover page structure. The file tells you:
- Card selector and listings per page
- Pagination URL pattern (how to generate all page URLs)
- Which fields are present vs missing on cards
- Whether detail pages are needed (two-phase portals)
- Portal-specific gotchas (dual prices, compound tipos, text-based garaje, etc.)
- Whether Python API fallback is needed (Coninsa, Villa Cruz)

This makes repeat scrapes instant — no Phase 1 needed for known portals.

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

### ⛔ SAMPLE-FIRST RULE (mandatory)

**Never bulk-scrape before verifying extraction on a sample.** Before running any bulk operation (full portal scrape, detail-page batch, DB mass-update), test the extraction logic on 1-3 pages first and confirm the output is correct. Only then scale up.

**Triggers that require sample-first:**
- New extraction logic (any Python script or agent reasoning that parses page content)
- New portal or new two-phase strategy
- New field being extracted from a known source
- DB mass-update script

**Sample verification checklist:**
- [ ] Fetch 1-3 sample pages
- [ ] Run extraction logic on each
- [ ] Verify every target field has a non-zero value where expected (banos > 0 for residential, estrato 1-6, etc.)
- [ ] Check for edge cases: missing fields, 0 values, out-of-range values
- [ ] **Only after all samples pass** → run the full batch

**Anti-pattern:**
- Running 1,128 detail pages 3 times because the extraction had a bug that would have been caught on page 1

### ⛔ BATCH DELEGATION (preferred for bulk operations)

**When scraping 200+ detail pages or search pages, delegate batches to sub-agents in parallel.** This keeps the orchestrator context clean and reduces total wall-clock time.

**When to use:**
- Phase B of two-phase portals (100+ detail pages)
- Full portal scrapes (50+ search pages)
- Any operation with >200 HTTP requests

**How to delegate:**
1. Split listings into batches of 100-200
2. Write a reusable batch runner script (Python using `scrapling.Fetcher`)
3. Save each batch's URLs to a JSON file
4. Launch all batches as `delegate` sub-agents in parallel
5. Merge results and update DB

**Example** (Santa Fe Phase B, 1,128 detail pages → 8 batches × 150):
- Generated 8 JSON batch files with IDs and URLs
- Single `asf_batch_runner.py` script shared by all batches
- 8 `delegate` calls in parallel — all completed in ~25s
- Merged results and batch-updated DB with CASE WHEN

**Do NOT:**
- Run 1,000+ sequential `scrapling_bulk_get` calls in the orchestrator
- Try to parallelize by writing per-portal threading code — delegation is simpler
- Re-scrape entire portal to test a fix — test on 1-3 samples first per SAMPLE-FIRST RULE

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
