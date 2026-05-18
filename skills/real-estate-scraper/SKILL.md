---
name: real-estate-scraper
description: Scrape real estate rental listings from any portal. Discovers listing cards, maps fields dynamically, handles pagination, and outputs a typed CSV with id, portal, tipo, precio, area, habitaciones, banos, parqueaderos, estrato, barrio, url. Uses Scrapling MCP for all HTTP fetching.
license: MIT
compatibility: opencode
metadata:
  audience: all
  workflow: real-estate-scrape
---

## What I Do

Scrape real estate rental listings from any portal URL. I discover the page structure dynamically — no hardcoded selectors. I find listing cards, map fields using keyword signals, handle pagination, and output a clean typed CSV ready for analysis.

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

- Scrapling MCP configured in opencode.json (must be loaded in current session)
- A search results URL from a real estate portal

---

## Workflow — 4 Phases

### Phase 1: Discovery (single page)

**Goal**: understand the page structure. Do NOT skip to bulk scrape yet.

#### Step 1.1 — Fetch page 1

Use `scrapling_get` or `scrapling_fetch` (use `fetch` if the page requires JavaScript):

```
scrapling_get(
  url: "{USER_URL}",
  stealthy_headers: true,
  timeout: 30,
  extraction_type: "text"
)
```

If the portal redirects or the listings are in an iframe, detect that and adjust.

#### Step 1.2 — Determine portal identity

From the URL, derive two values:
- **`PORTAL`**: domain without TLD. e.g. `www.maxibienes.com` → `maxibienes`, `www.fincaraiz.com.co` → `fincaraiz`
- **`PREFIX`**: 2-4 uppercase letters from the portal name. e.g. Maxibienes → `MXB`, FincaRaiz → `FNR`, MetroCuadrado → `MTC`

#### Step 1.3 — Find listing cards

The page has repeating HTML blocks representing individual listings. To find them:

1. Split the page text into lines/sections
2. Find the first listing by looking for signals: a price/currency pattern, an area (xx m²), room counts
3. From that position, walk up the DOM to find the repeating container element
4. Verify: extract data from a few containers — they should have similar structure

You are looking for a CSS selector like `.listing-card`, `.item`, `.property`, `article`, `[class*="result"]`, or an HTML tag repeated N times with similar children.

#### Step 1.4 — Map fields

For each target column, look for signals in the listing card's HTML/text. Use these detection strategies (Spanish and English):

**`tipo`** (property type):
- Look for: `apartamento`, `apartaestudio`, `casa`, `apartamento`, `apto`, `departamento`, `department`, `studio`, `house`, `local`, `oficina`, `office`, `bodega`, `warehouse`, `lote`, `lot`, `finca`, `farm`
- Usually in a heading, tag, or label near the top of the card
- Normalize: `apartamento`/`apto`/`departamento` → `apartamento`, `casa`/`house` → `casa`, `apartaestudio`/`studio` → `apartaestudio`

**`precio`** (rental price):
- Look for: `$`, `COP`, `USD`, numbers with thousands separators (`.` or `,`)
- Keywords: `precio`, `canon`, `valor`, `arriendo`, `rent`, `price`, `alquiler`
- Determine if it's daily/weekly/monthly to extract the right value (prefer monthly for rentals)
- Strip all non-digit characters: `$ 1.450.000` → `1450000`

**`area`** (square meters):
- Look for: `m²`, `m2`, `mt2`, `mts²`, `metros`, `sqm`, `sqft`
- Keywords: `área`, `area`, `superficie`, `metros`
- Extract the number immediately before the unit

**`habitaciones`** (bedrooms):
- Look for: single numbers 1-10 near specific icons or labels
- Keywords: `habitación`, `habitaciones`, `alcoba`, `alcobas`, `dormitorio`, `cuarto`, `cuartos`, `bedroom`, `bedrooms`, `hab`, `dorm`
- Icons: bed icon (`fa-bed`, bed SVG), or a bed emoji
- If ambiguous (multiple numbers nearby), prefer the one closest to the bedroom keyword/icon

**`banos`** (bathrooms):
- Keywords: `baño`, `baños`, `bathroom`, `bathrooms`, `banos`, `bath`, `wc`
- Icons: bath/shower icon (`fa-bath`, bath SVG), toilet icon
- Usually paired alongside habitaciones

**`parqueaderos`** (parking spots):
- Keywords: `parqueadero`, `parqueaderos`, `garaje`, `garajes`, `estacionamiento`, `parking`, `garage`, `parq`
- Icons: car icon, garage icon (`fa-car`, `fa-warehouse`, car SVG)
- Usually the last amenity listed

**`estrato`** (socioeconomic level, Colombia):
- Keyword: `estrato` followed by a number 1-6
- Some portals embed it in the title/description, others as a label
- If the portal is not Colombian or estratos are absent, set to 0

**`barrio`** (neighborhood):
- Keywords: `barrio`, `zona`, `sector`, `neighborhood`, `ubicación`, `location`, `address`
- Usually a proper noun (capitalized), often after a label like "Barrio: Laureles"
- Take the text value, not the label

**`url`** (detail page link):
- Find the `<a href="...">` that wraps the listing card or its image/title
- Must be an absolute URL (prepend the domain if relative)
- If no link exists, use the search result URL

**`id`** (composite identifier):
- Compose: `{PREFIX}-{INTERNAL_CODE}`
- The internal code is usually visible in the listing (a numeric or alphanumeric ID, sometimes in a data attribute or the URL path)
- Look for a property code, reference number, or ID visible in the card
- Extract it from the URL path if not visible: `/codigo/69007` → `69007`

#### Step 1.5 — Discover pagination

Find the pagination mechanism:

1. Count the listings on page 1
2. Look for text like "Page 1 of N", "Página 1 de N", "1 / N"
3. Look for "Siguiente", "Next", numbered page links
4. Determine the URL pattern:
   - Query param: `?pagina=2`, `?page=2`, `?pg=2`
   - Path segment: `/pagina/2`, `/page/2`
   - POST/scroll (infinite scroll) — if AJAX-based, look at the network request to find the API endpoint
5. Calculate total pages: `ceil(total_listings / listings_per_page)`

Halt and report your findings to the user before proceeding: listing card selector, field mappings, total pages, portal prefix.

---

### Phase 2: Bulk Scrape

#### Step 2.1 — Generate all page URLs

Build the full URL for every page (1 to total_pages) using the pattern discovered in Step 1.5.

#### Step 2.2 — Fetch all pages

Use `scrapling_bulk_get` to fetch all pages in a single parallel call:

```
scrapling_bulk_get(
  urls: ["{url_page_1}", "{url_page_2}", ...],
  stealthy_headers: true,
  timeout: 60,
  extraction_type: "html",
  css_selector: "{LISTING_CARD_SELECTOR}"
)
```

If the page requires JavaScript, use `scrapling_bulk_fetch` instead.

If the portal blocks bulk requests, fall back to sequential `scrapling_get` calls.

#### Step 2.3 — Extract and type

Process each listing card using the field mappings from Phase 1:

- **String fields** (`id`, `portal`, `tipo`, `barrio`, `url`): trim whitespace, normalize tipo to lowercase
- **Integer fields** (`precio`, `area`, `habitaciones`, `banos`, `parqueaderos`, `estrato`): strip all non-digit characters, convert to int. Empty → 0
- **`id`**: compose from `{PREFIX}-{CODE}`. If no code found, generate from row index

#### Step 2.4 — Validate

Before writing CSV, check:
- No duplicate `id` values
- `precio` > 0 for all rows
- `area` > 0 for most rows (studios may be small but rarely 0)
- `habitaciones`, `banos` in reasonable range (0-20)
- `parqueaderos` in reasonable range (0-10, flag outliers > 10 as possible source errors)
- `estrato` in 0-6 (0 means not available)
- All `url` values are absolute and non-empty

Report anomalies to the user rather than silently fixing.

---

### Phase 3: Output CSV

Write to `{portal}_arriendos_{ciudad}.csv` using the standard column order:

```
id,portal,tipo,precio,area,habitaciones,banos,parqueaderos,estrato,barrio,url
```

- Encoding: UTF-8
- Delimiter: comma
- No quotes unless the value contains a comma or newline
- All numeric fields as plain integers (no formatting)

---

### Phase 4: Report

Print a summary table:

| Metric | Value |
|---|---|
| Portal | {PORTAL} |
| Total listings | {N} |
| Pages scraped | {M} |
| Property types | {unique tipos} |
| Unique neighborhoods | {count} |
| Price range | {min} - {max} |
| Anomalies | {count and description} |

Show the first 3 and last 3 rows as inline samples.

---

## Edge Cases and Best Practices

### Dynamic content
- If listings load via AJAX/JavaScript, use `scrapling_fetch` (opens Chromium)
- Check the browser console for API endpoints — calling the API directly is faster
- For infinite scroll, find the API endpoint and paginate through it

### Anti-bot protection
- Always use `stealthy_headers: true` with `scrapling_get`
- For Cloudflare/Turnstile, use `scrapling_stealthy_fetch` with `solve_cloudflare: true`
- Add delays between requests if the server returns 429

### Duplicate properties
- If a property appears on multiple pages (cross-listed), the composite `id` de-duplicates naturally
- Flag duplicates in the report but keep both rows — the user decides

### Missing fields
- Set numeric fields to 0 if missing after exhaustive search
- Set string fields to empty string
- Never use placeholder values (e.g. "N/A", -1) — they break sorting/analysis

### Multi-currency
- If prices are in different currencies, note the currency in the report
- Default assumption: local currency of the country (COP for Colombia)

### Scalability
- The `id` column is the merge key across portals: `MXB-69007`, `FNR-12345`, `MTC-abc`
- The `portal` column enables filtering by source
- Append (don't overwrite) when scraping multiple portals into one dataset
