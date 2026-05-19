# Scraping Rules

Rules that govern every scrape operation, regardless of portal.

## Phase 1: Discovery (mandatory, never skip)

### 1.1 Always fetch one page first
Never jump to bulk scrape. Fetch page 1 with `scrapling_get` using text extraction to understand the page structure.

### 1.2 Never assume field positions
Even if a portal's layout suggests "the second number is bathrooms", verify with:
- CSS class names (`alcobas`, `banos`, `garaje`)
- Icon filenames (`bed-icon.png`, `bath-icon.png`, `car-icon.png`)
- Text labels (`Baños:`, `Habitaciones:`)
- HTML structure inspection

Positional assumptions caused the A12439 bug (car icon number was interpreted as bathrooms).

### 1.3 Always extract with HTML first, then text
Use `scrapling_get` with `extraction_type: "html"` and a CSS selector targeting listing cards. Parse the HTML to:
- Find exact CSS class names
- Inspect icon filenames
- Locate labels
- Build precise regex patterns

### 1.4 Always verify on 3+ cards
After mapping fields on one card, verify the same mapping works on at least 3 different cards from the same page. Different property types may have different layouts.

### 1.5 Always discover pagination before scaling
- Look for "Page X of N", "Página X de N" text
- Look for numbered pagination links
- Look for "Next"/"Siguiente" links
- Determine URL pattern: query param (`?page=N`), path segment (`/pagina/N`), or AJAX
- **JS variable detection**: check `<script>` tags for variables like `var totalInmuebles = 870; var totalpagina = 12;` — compute `ceil(total / per_page)`
- **Large page probe**: request a very large page number (e.g., `?page=999`) and observe:
  - The last valid page number in pagination elements
  - Whether the site serves stale/placeholder listings past the end (detect by comparing listing codes across pages)
- **Binary search**: when no pagination info is available, binary-search to find the last valid page by checking if pages return fresh listing codes vs. stale duplicates

### 1.6 Identify missing fields and two-phase potential
- After mapping fields on 3+ cards, list which of the 11 columns are missing from cards
- For each missing field, check the portal reference: some portals are documented as two-phase (detail pages have the missing fields)
- If banos or estrato are missing AND the portal reference shows them on detail pages → this portal requires two-phase scrape
- **Field check order**: inspect CSS classes first (1.2), then check if missing fields exist on the detail page
- Document the two-phase strategy (if needed) in the portal reference file

## Phase 2: Bulk Scrape

### 2.1 Use `scrapling_bulk_get` when possible
For server-rendered pages, `bulk_get` is faster and cheaper than browser-based fetching.

### 2.2 Two-phase portals: cards first, then detail pages
- **Phase A**: `scrapling_bulk_get` all search result pages → extract card-level fields + detail page URLs
- **Phase B**: `scrapling_bulk_get` all detail page URLs → extract ONLY the fields missing from cards (typically banos, estrato)
- **Merge**: update phase A listings with phase B values; keep card values for fields already present
- Detail pages that fail to load → keep card defaults (0 for numeric, "" for string)

### 2.3 Two-phase portals requiring JS: use `scrapling_bulk_fetch` or `bulk_stealthy_fetch`
If detail pages require JavaScript rendering (not Santa Fe / Santillana / Monserrate — these are server-rendered).

### 2.4 Use `scrapling_bulk_fetch` for JavaScript-rendered pages
If listings load via AJAX/JavaScript, use `bulk_fetch` or `bulk_stealthy_fetch`.

### 2.5 Batch pagination for large portals
If total pages > 30, split into batches of ~25 pages per `bulk_get` call to avoid timeouts.

### 2.6 Always use stealthy headers
```json
{ "stealthy_headers": true }
```
Prevents basic anti-bot detection.

### 2.7 Respect the portal
If the server returns 429 (rate limit), add delays between batches. If blocked, switch to `stealthy_fetch`.

## Phase 3: Extraction and Typing

### 3.1 Extract with precise regex
Use the field mappings discovered in Phase 1 to write exact regex patterns. Test on the first card.

### 3.2 Type consistently
- `precio`, `area`, `habitaciones`, `banos`, `parqueaderos`, `estrato`: strip all non-digits → `int()`. Empty → `0`.
- `id`, `portal`, `tipo`, `barrio`, `url`: `.strip()`. Empty → `""`.
- `tipo`: `.lower()` and normalize per `columns-spec.md`.

### 3.3 Never silently fix data
If a value seems wrong (parking = 2611), include it as-is but flag it in the report. The user decides what to do.

### 3.4 Deduplicate by `id`
The composite `id` field prevents duplicates across pages and portals. If a portal lists the same property on multiple pages, the second occurrence will have the same `id` and should be flagged.

## Phase 4: Output — CSV or Database

The agent must ask the user where to save before writing output.

### 4.1 Column order is fixed (both outputs)
Always: `id, portal, tipo, precio, area, habitaciones, banos, parqueaderos, estrato, barrio, url`

### 4.2 Option A: CSV (default, portable)
- Write to `results/{portal}_arriendos_{ciudad}.csv`
- Encoding: UTF-8, comma delimiter, no BOM
- No quotes unless value contains comma or newline
- Directory `results/` is gitignored (CSVs never committed)

### 4.3 Option B: PostgreSQL database
- Requires `DATABASE_URL` in `.env` (PostgreSQL connection string; provider-agnostic)
- One-time setup: `uv run python scripts/setup_db.py`
- Insert data: write listings to a JSON file, then run `uv run python scripts/insert_listings.py <json_file> <ciudad>`
- Uses `ON CONFLICT (id) DO UPDATE` — re-scraping refreshes rows, no duplicates
- JSON format: list of objects with keys matching column names (minus `ciudad`, added by script)

### 4.4 Always produce a report
After output, report:
- Total listings scraped
- Total pages
- Property types found
- Unique neighborhoods count
- Price range (min-max)
- Anomalies detected (count and description)
- Fields that were missing/unavailable
- Output location (CSV path or DB row count)
