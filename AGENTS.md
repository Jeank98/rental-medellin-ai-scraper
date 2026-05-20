# AGENTS.md — Rental Medellín AI Scraper

This project is a **knowledge base + tooling** for scraping real estate rental listings from Colombian portals. It provides 12 per-portal executable Python scripts (powered by a shared `scrape/` package), plus AI-agent reference documentation for portal discovery and field mapping.

## What every agent working with this project must know

### Project purpose
Scrape rental property listings from any Colombian real estate portal, extract standardized fields, and output listings as a typed CSV or to a PostgreSQL database. **Scripts are the PRIMARY production path** — the agentic workflow exists as a fallback and for documenting new portal structures.

### Production: scripts first, agents second
All 12 portals have standalone executable scripts at `scripts/scrape_{portal}.py`. These call into a shared `scrape/{portal}.py` module and use `scrape/cli.py` for standardized CLI behavior (`--output csv|db|both`, `--ciudad`, `--sample-only`, `--max-pages`, `--verbose`).

**When a portal has a working script, ALWAYS use the script.** The agentic workflow (Scrapling MCP tools + agent reasoning) is reserved for:
- Discovering a brand-new portal not yet in the codebase
- Debugging a script that broke after a site redesign
- Updating field mappings in `reference/portals/{name}.md`

### Strategy types (12 portals)

| Strategy | Count | Portals |
|---|---|---|
| REST API | 1 | ADN (Arrendamientos del Norte) |
| GraphQL | 1 | Coninsa |
| Single-phase HTML | 5 | Maxibienes, AlbertoAlvarez, MerinoHermanos, Habitamos, Metrocasas |
| Two-phase HTML | 4 | SantaFe, Santillana, Alnago, Monserrate |
| Load More (JS) | 1 | VillaCruz |

### Key files
| File | Purpose |
|---|---|
| **Scripts (primary production path)** | |
| `scripts/run_all.py` | Orchestrator: runs all 12 scrapers with health check → DB backup → parallel scrape → validation → report |
| `scripts/scrape_{portal}.py` × 12 | Per-portal CLI entry points (thin wrappers calling `scrape/{portal}.py`) |
| `scrape/orchestrator.py` | Pipeline logic: health checks, parallel execution, backup, reporting |
| `scrape/report.py` | Report formatting for the orchestrator |
| `scrape/cli.py` | Shared CLI factory (`create_parser` / `run_scraper`) for all portal scripts |
| `scrape/{portal}.py` × 12 | Per-portal scraper logic (extraction, pagination, normalization) |
| `scrape/fetcher.py` | HTTP fetch utilities (requests, aiohttp, Scrapling, Playwright) |
| `scrape/normalize.py` | Normalization functions (precio, tipo, estrato, garaje, barrio, URL) |
| `scrape/validator.py` | Anomaly detection and validation |
| `scrape/csv_writer.py` | CSV output writer |
| `scrape/db_writer.py` | PostgreSQL insert/upsert writer |
| **Agentic reference docs (fallback + documentation)** | |
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

### Running all portals at once

```
uv run python scripts/run_all.py --workers 12
```

Options:
- `--workers N` — concurrent scrapers (default 4, max 12 for full parallel)
- `--ciudad` — city filter (default `medellin`)
- `--skip-backup` — skip pg_dump before scraping
- `--skip-health` — skip health check (run all scrapers regardless)
- `--verbose` — detailed logging

### Running a single portal

```
uv run python scripts/scrape_asf.py              # scrape Santa Fe (default: csv + db)
uv run python scripts/scrape_asf.py --output csv  # CSV only
uv run python scripts/scrape_asf.py --output db   # DB only
uv run python scripts/scrape_asf.py --sample-only # validate 1-3 pages, print summary, exit
uv run python scripts/scrape_asf.py --max-pages 3 # limit pages for testing
```

All portal scripts share these flags.

### Workflow for scraping a new portal

**Production path (new script):**
1. Study the portal in a browser to understand its structure
2. Check `reference/portal-field-mappings.md` — if portal exists, load `reference/portals/{name}.md`
3. Determine the strategy type (REST API, GraphQL, single-phase HTML, two-phase HTML, Load More)
4. Write `scrape/{name}.py` — the scraper module using `scrape.fetcher`, `scrape.normalize`, `scrape.validator`
5. Write `scripts/scrape_{name}.py` — thin CLI entry point using `scrape.cli.create_parser` and `scrape.cli.run_scraper`
6. Register the portal in `scrape/orchestrator.py` → `PORTALS` dict
7. Test with `--sample-only`, then full scrape; verify output matches `docs/columns-spec.md`
8. Report discovered field mappings to `reference/portals/{name}.md`

**Agentic fallback (documentation only):**
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

### Zero-genuineness — when 0 means "not available"

Some portals do not expose certain fields at all. A `0` for these fields is correct and expected — not a bug:

| Portal | Genuinely absent fields (always 0) |
|---|---|
| ADN (REST API) | `banos`, `parqueaderos`, `estrato` |
| Habitamos | `area`, `estrato` |
| Monserrate | `area` (detail page only) |
| Coninsa (GraphQL) | `area` (not in the API response) |

Do NOT flag these as anomalies. The validator in `scrape/validator.py` accounts for per-portal genuine zeros.

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
