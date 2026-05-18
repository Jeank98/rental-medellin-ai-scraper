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
- To find total pages: request a very large page number (e.g., `?page=999`) and observe the last visible page number in the pagination element

## Phase 2: Bulk Scrape

### 2.1 Use `scrapling_bulk_get` when possible
For server-rendered pages, `bulk_get` is faster and cheaper than browser-based fetching.

### 2.2 Use `scrapling_bulk_fetch` for JavaScript-rendered pages
If listings load via AJAX/JavaScript, use `bulk_fetch` or `bulk_stealthy_fetch`.

### 2.3 Batch pagination for large portals
If total pages > 30, split into batches of ~25 pages per `bulk_get` call to avoid timeouts.

### 2.4 Always use stealthy headers
```json
{ "stealthy_headers": true }
```
Prevents basic anti-bot detection.

### 2.5 Respect the portal
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

## Phase 4: CSV Output

### 4.1 Column order is fixed
Always: `id, portal, tipo, precio, area, habitaciones, banos, parqueaderos, estrato, barrio, url`

### 4.2 Encoding and format
- UTF-8 encoding
- Comma delimiter
- No quotes unless value contains comma or newline
- No BOM

### 4.3 File naming
`{portal}_arriendos_{ciudad}.csv`

Examples:
- `maxibienes_arriendos_medellin.csv`
- `arrendamientossantafe_arriendos_medellin.csv`

### 4.4 Always produce a report
After CSV generation, report:
- Total listings scraped
- Total pages
- Property types found
- Unique neighborhoods count
- Price range (min-max)
- Anomalies detected (count and description)
- Fields that were missing/unavailable
