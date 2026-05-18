---
name: real-estate-scraper
description: Scrape real estate rental listings from any portal. Uses Scrapling MCP tools directly — the AI agent discovers page structure, maps fields visually with screenshots, and extracts listings in conversation. No hardcoded selectors or scripts.
license: MIT
compatibility: opencode
metadata:
  audience: all
  workflow: real-estate-scrape
---

## What I Do

Scrape real estate rental listings from any portal URL using Scrapling MCP tools directly in conversation. I fetch pages, see the content, reason about field mappings, and extract data — no hardcoded selectors, no per-portal scripts. When text labels are absent (icon-only fields), I use `scrapling_screenshot` to visually identify what each icon means.

Output columns (always in this order):

| # | Column | Type | Description |
|---|--------|------|-------------|
| 1 | `id` | str | Composite key: `{PORTAL_PREFIX}-{INTERNAL_CODE}` (e.g. `MXB-69007`). Globally unique. |
| 2 | `portal` | str | Portal identifier (domain without TLD, e.g. `maxibienes`, `fincaraiz`) |
| 3 | `tipo` | str | Property type, normalized: `apartamento`, `casa`, `apartaestudio`, `local`, `oficina`, `bodega`, `lote`, `finca` |
| 4 | `precio` | int | Rental price in local currency (digits only, no dots/commas/symbols) |
| 5 | `area` | int | Area in m² (digits only) |
| 6 | `habitaciones` | int | Number of bedrooms |
| 7 | `banos` | int | Number of bathrooms |
| 8 | `parqueaderos` | int | Number of parking spots |
| 9 | `estrato` | int | Socioeconomic level (1-6, Colombia-specific; 0 if unavailable) |
| 10 | `barrio` | str | Neighborhood name |
| 11 | `url` | str | Full URL to the property detail page |

---

## Prerequisites

- **Scrapling MCP** configured in opencode.json — provides `scrapling_get`, `scrapling_bulk_get`, `scrapling_screenshot`, etc.
- **Scrapling MCP must be loaded in the current session** — verify by checking available tools for `scrapling_*`
- A search results URL from a real estate portal
- Reference docs (read as needed):
  - `docs/variable-detection.md` — field detection strategies (read during Phase 1)
  - `docs/columns-spec.md` — exact column types and normalization rules
  - `docs/scraping-rules.md` — pagination discovery, validation rules
  - `docs/decision-tree.md` — what to do when fields are missing or ambiguous
  - `reference/portal-field-mappings.md` — previously discovered mappings (check first!)

---

## Workflow — 4 Phases

### Phase 1: Discovery (single page)

**Goal**: Understand the page structure using the AI's own eyes. Do NOT skip to bulk scrape yet.

**Always check `reference/portal-field-mappings.md` first** — if this portal was scraped before, use existing mappings as a starting point and verify they still hold.

#### Step 1.1 — Fetch page 1 as text

Use `scrapling_get` to get an overview:

```
scrapling_get(
  url: "{USER_URL}",
  stealthy_headers: true,
  timeout: 30,
  extraction_type: "text",
  main_content_only: true
)
```

This gives a clean text view of the page. Identify:
- How many listings appear (count repeating patterns)
- What fields are visible in text form (prices, areas, neighborhoods)
- What fields are missing from text (likely icon-only or visual)

If the portal redirects or requires JavaScript, detect and switch to `scrapling_fetch`.

#### Step 1.2 — Determine portal identity

From the URL:
- **`PORTAL`**: domain without TLD. `www.maxibienes.com` → `maxibienes`
- **`PREFIX`**: 2-4 uppercase letters. Maxibienes → `MXB`, ArrendamientosSantaFe → `ASF`

#### Step 1.3 — Find listing cards with CSS selector

Fetch page 1 again with HTML extraction, trying different selectors until you find listing cards:

```
scrapling_get(
  url: "{USER_URL}",
  stealthy_headers: true,
  timeout: 30,
  extraction_type: "html",
  css_selector: ".grid-style1 .item"   // try common patterns
)
```

Common selectors to try: `[class*="item"]`, `[class*="card"]`, `[class*="property"]`, `article`, `.listing`. You're looking for a selector that returns exactly N elements where N matches the listing count from Step 1.1.

#### Step 1.4 — Map fields (text-based first)

For each target column, apply the detection strategies from `docs/variable-detection.md` on the text output from Step 1.1:

- **`tipo`**: heading text, "Tipo:" label, URL path segment. Normalize per `columns-spec.md`.
- **`precio`**: currency symbol + number, "Arriendo" keyword. Handle ARRIENDO/VENTA dual prices (split `/`, take first).
- **`area`**: `m²`, `m2`, `mt2`, `metros` pattern.
- **`habitaciones`**: bed icon keywords, "alcoba", "habitación" labels.
- **`banos`**: bath icon keywords, "baño", "bath" labels. Often absent → 0.
- **`parqueaderos`**: car/garage icon keywords, "garaje", "parqueadero" labels.
- **`estrato`**: "Estrato:" + number 1-6. Colombian portals only. Absent → 0.
- **`barrio`**: "Ubicación:", "Barrio:", "Zona:", "Sector:" labels.
- **`url`**: anchor wrapping the card/image. Make absolute.
- **`id`**: "REF:", "Código:", "Code:", URL path. Compose `{PREFIX}-{CODE}`.

**For text-only fields that are unclear or ambiguous, STOP and use Step 1.4b.**

#### Step 1.4b — Visual field resolution with screenshots

When a field cannot be determined from text alone (icons without labels, unusual layouts, ambiguous positions), use `scrapling_screenshot` to see the actual listing card:

1. Open a browser session: `scrapling_open_session(type: "dynamic")`
2. Fetch page 1: `scrapling_fetch` with `session_id` and the card CSS selector
3. Take a screenshot: `scrapling_screenshot(selector: "{CARD_SELECTOR}")`

The screenshot returns an actual image the model can see — not a base64 blob. **Look at the icons visually**:
- 🛏️ + number = habitaciones
- 🚿/🛁 + number = banos
- 🚗 + number = parqueaderos
- 📍 + text = barrio

Map each icon to its column by visual position and icon type. Record your findings.

4. Close session when done: `scrapling_close_session(session_id)`

#### Step 1.5 — Discover pagination

Find the total number of listings and pages:

1. Count listings on page 1 from Step 1.3
2. Look for pagination clues:
   - Text: "Page X of N", "Página X de N"
   - JavaScript variables in page source: `var totalInmuebles = N; var totalpagina = N;`
   - Pagination links with last-page number
3. **Large-page probe**: request `?page=999` and observe:
   - The URL redirect → actual last page
   - Whether stale/placeholder listings appear past the end (compare listing IDs)
4. Calculate: `total_pages = ceil(total_listings / listings_per_page)`

**Halt and report your findings to the user** before proceeding: portal, prefix, card selector, field mappings (with confidence levels), total pages, any fields confirmed as missing.

---

### Phase 2: Bulk Scrape

#### Step 2.1 — Generate all page URLs

Build the full URL for every page (1 to total_pages) using the pattern from Step 1.5.

#### Step 2.2 — Fetch all pages with `scrapling_bulk_get`

Use `scrapling_bulk_get` to fetch all pages in a single parallel call:

```
scrapling_bulk_get(
  urls: ["{url_page_1}", "{url_page_2}", ...],
  stealthy_headers: true,
  timeout: 60,
  extraction_type: "text",
  css_selector: "{LISTING_CARD_SELECTOR}"
)
```

If the page requires JavaScript, use `scrapling_bulk_fetch` instead.
If the portal blocks bulk requests, fall back to sequential `scrapling_get` calls.

#### Step 2.3 — Extract and type

**The AI processes the returned content directly in conversation.** For each listing card returned by scrapling:

- Extract values using the field mappings discovered in Phase 1
- **String fields**: trim whitespace, normalize tipo to lowercase
- **Integer fields**: strip non-digit characters, convert to int. Empty → 0.
- **`id`**: compose `{PREFIX}-{CODE}`. If no code found, generate from row index.
- **`portal`**: set to the portal name from Step 1.2.

Use the strategies from `docs/variable-detection.md` to handle edge cases (dual prices, missing fields, icon-based values).

#### Step 2.4 — Validate

Check the extracted data:
- No duplicate `id` values
- `precio` > 0 for all rows (flag zeros)
- `area` > 0 for most rows
- `habitaciones`, `banos` in reasonable range (0-20)
- `parqueaderos` in reasonable range (0-10, flag outliers)
- `estrato` in 0-6 (flag > 6 as source data error)
- All `url` values are absolute and non-empty

**Report anomalies to the user** rather than silently fixing.

---

### Phase 3: Output — CSV or Database

**Before writing output, ask the user where to save**: CSV file (portable, no setup) or PostgreSQL database.

#### Option A: CSV (default)

Ensure `results/` directory exists, then write to `results/{portal}_arriendos_{ciudad}.csv`:

```
id,portal,tipo,precio,area,habitaciones,banos,parqueaderos,estrato,barrio,url
```

- Encoding: UTF-8, comma delimiter
- No quotes unless value contains comma or newline
- Directory `results/` is gitignored

#### Option B: PostgreSQL database

If the user has configured `DATABASE_URL` in `.env`:

1. Write the scraped data to a temporary JSON file
2. Run: `uv run python scripts/insert_listings.py <json_file> <ciudad>`

The table uses `ON CONFLICT (id) DO UPDATE` and auto-manages `active`/`inactive` status. Re-scraping marks unseen listings as inactive.

---

### Phase 4: Report

Print a summary table:

| Metric | Value |
|---|---|
| Portal | {PORTAL} |
| City | {ciudad} |
| Total listings | {N} |
| Pages scraped | {M} |
| Property types | {unique tipos} |
| Unique neighborhoods | {count} |
| Price range | {min} - {max} |
| Anomalies | {count and description} |
| Output | CSV path or DB row count |

Show the first 3 and last 3 rows as inline samples.

---

## Edge Cases and Best Practices

### Dynamic content
- If listings load via AJAX/JavaScript, use `scrapling_fetch` (opens Chromium)
- Check the browser console for API endpoints — calling the API directly is faster
- For infinite scroll, find the API endpoint and paginate through it

### Anti-bot protection
- Always use `stealthy_headers: true` with `scrapling_get`
- For Cloudflare/Turnstile, use `scrapling_stealthy_fetch`
- Add delays between requests if the server returns 429

### Icon-only fields (visual detection)
- When text extraction shows numbers but no labels, use `scrapling_screenshot` to see the icons
- The model can visually identify: bed icon → habitaciones, bath/shower → banos, car → parqueaderos
- Record discovered icon mappings in `reference/portal-field-mappings.md` for future scrapes

### Duplicate properties
- The composite `id` de-duplicates naturally
- Flag duplicates in the report but keep both rows — the user decides

### Missing fields
- Set numeric fields to 0 if missing after exhaustive search (including screenshot inspection)
- Set string fields to empty string
- Never use placeholder values (e.g. "N/A", -1)

### Multi-currency
- Prefer COP for Colombian portals
- Note non-COP currencies in the report

### Scalability
- `id` column is the merge key across portals
- `portal` column enables filtering by source
- Re-scraping with DB option auto-manages active/inactive status
