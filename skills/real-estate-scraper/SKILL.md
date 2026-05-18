---
name: real-estate-scraper
description: Scrape real estate rental listings from any portal using Scrapling MCP tools exclusively. The AI agent fetches pages, reads content, identifies fields visually, and extracts listings — zero regex, zero scripts, zero hardcoded selectors.
license: MIT
compatibility: opencode
metadata:
  audience: all
  workflow: real-estate-scrape
---

## What I Do

Scrape rental listings from any real estate portal using **only Scrapling MCP tools**. No Python scripts, no regex, no CSS selectors — the agent fetches, sees, reasons, and extracts. Screenshots handle icon-only fields. Bulk tools handle pagination.

Output columns (always 11, in this order):

| # | Column | Type | Description |
|---|--------|------|-------------|
| 1 | `id` | str | `{PORTAL_PREFIX}-{CODE}` (e.g. `MXB-69007`) |
| 2 | `portal` | str | Domain without TLD (e.g. `maxibienes`) |
| 3 | `tipo` | str | `apartamento`, `casa`, `apartaestudio`, `local`, `oficina`, `bodega`, `lote`, `finca` |
| 4 | `precio` | int | Rental price, digits only |
| 5 | `area` | int | m², digits only |
| 6 | `habitaciones` | int | Bedrooms |
| 7 | `banos` | int | Bathrooms |
| 8 | `parqueaderos` | int | Parking spots |
| 9 | `estrato` | int | 1-6 (Colombia), 0 if unavailable |
| 10 | `barrio` | str | Neighborhood |
| 11 | `url` | str | Full detail page URL |

---

## Prerequisites

- **Scrapling MCP** configured and loaded — tools: `scrapling_get`, `scrapling_bulk_get`, `scrapling_fetch`, `scrapling_screenshot`, `scrapling_open_session`
- Reference docs (read as needed):
  - `docs/variable-detection.md` — field detection strategies
  - `docs/columns-spec.md` — types and normalization
  - `docs/scraping-rules.md` — pagination discovery, validation
  - `docs/decision-tree.md` — missing field logic
  - `reference/portals/` — per-portal mappings (check first!)

## ⛔ NO REGEX RULE

**Never use regex, Python scripts, or hardcoded selectors for field extraction.** The agent uses Scrapling MCP tools to see page content, then applies its own reasoning guided by `docs/variable-detection.md`. Regex is only acceptable for pagination discovery (finding page numbers in HTML source) — never for extracting listing field values.

---

## Workflow — 4 Phases

### Phase 1: Discovery (single page)

**Check `reference/portals/` first** — if scraped before, verify existing mappings.

#### Step 1.1 — Fetch page 1 as text

```
scrapling_get(
  url: "{USER_URL}",
  stealthy_headers: true,
  timeout: 30,
  extraction_type: "text",
  main_content_only: true
)
```

Read the output. Identify: listing count, visible fields, missing fields.

#### Step 1.2 — Portal identity

- **PORTAL**: domain without TLD. `www.maxibienes.com` → `maxibienes`
- **PREFIX**: 2-4 uppercase letters. Maxibienes → `MXB`

#### Step 1.3 — Find listing cards

Use `css_selector` to narrow output to just listing cards:

```
scrapling_get(
  url: "{USER_URL}",
  extraction_type: "text",
  css_selector: ".grid-style1 .item"
)
```

Try `[class*="item"]`, `[class*="card"]`, `[class*="property"]`, `article`. Count = per-page listings.

#### Step 1.4 — Map fields (text-based)

For each of the 11 columns, read the text output and apply detection strategies from `docs/variable-detection.md`:

- **tipo**: heading text, "Tipo:" label. Normalize to lowercase.
- **precio**: `$` + number. Handle ARRIENDO/VENTA (split `/`, take first). Strip formatting → int.
- **area**: `m²`, `m2`, `metros` + number. Extract int.
- **habitaciones**: bed icon keywords, "alcoba", "habitación" + number.
- **banos**: bath icon keywords, "baño", "bath" + number. Absent → 0.
- **parqueaderos**: car/garage keywords, "garaje", "parqueadero" + number. Absent → 0.
- **estrato**: "Estrato: N" where N=1-6. Absent → 0.
- **barrio**: "Ubicación:", "Barrio:", "Zona:", "Sector:" labels. Or parsed from title "TIPO en BARRIO".
- **url**: `<a href>` wrapping the card. Make absolute.
- **id**: "REF:", "Código:", "Code:" + value. Or URL path extraction. Compose `{PREFIX}-{CODE}`.

#### Step 1.4b — Visual resolution (icons without labels)

For fields missing from text (icons only), use:

```
scrapling_open_session(type: "dynamic")
scrapling_fetch(url, session_id=..., css_selector=".listing-card")
scrapling_screenshot(selector=".listing-card", session_id=...)
```

The screenshot returns an image the agent can SEE — identify icons visually:
- 🛏️ + number = habitaciones
- 🚿 + number = banos
- 🚗 + number = parqueaderos
- 📍 + text = barrio

Close session: `scrapling_close_session(session_id)`

#### Step 1.5 — Pagination

Find total pages:
- Text: "Mostrando X de Y", "Página X de Y"
- JS vars: `var totalInmuebles = N`
- Large page probe: `?page=999` → observe redirect or stale content
- Binary search if no explicit count

**Halt and report** before bulk scrape.

---

### Phase 2: Bulk Scrape

#### Step 2.1 — Generate URLs

Build all page URLs using the pattern discovered in Step 1.5.

#### Step 2.2 — Fetch all pages

```
scrapling_bulk_get(
  urls: [all_page_urls],
  stealthy_headers: true,
  timeout: 60,
  extraction_type: "text",
  css_selector: "{CARD_SELECTOR}"
)
```

#### Step 2.3 — Extract

**The agent processes the returned text directly.** For each listing:
- Read the text output (flat listing content)
- Apply field mappings from Phase 1
- String fields: trim, normalize tipo to lowercase
- Integer fields: strip non-digits → int. Empty → 0.
- **id**: compose `{PREFIX}-{CODE}`

#### Step 2.4 — Validate

- No duplicate `id` values
- `precio` > 0 (flag zeros)
- `habitaciones`, `banos` in 0-20
- `parqueaderos` in 0-10 (flag outliers)
- `estrato` in 0-6 (flag > 6)
- All URLs absolute and non-empty

**Report anomalies** — don't silently fix.

---

### Phase 3: Output

Ask: CSV or PostgreSQL?

**CSV**: Write `results/{portal}_arriendos_{ciudad}.csv` (UTF-8, comma, 11 columns).

**PostgreSQL**: Write listings as JSON → `uv run python scripts/insert_listings.py <json> <ciudad>`.

---

### Phase 4: Report

| Metric | Value |
|---|---|
| Portal | {PORTAL} |
| City | {ciudad} |
| Total listings | {N} |
| Pages scraped | {M} |
| Property types | {counts} |
| Unique neighborhoods | {count} |
| Price range | {min} - {max} |
| Anomalies | {description} |

Show first 3 and last 3 rows.

---

## Edge Cases

- **JS-rendered pages**: Scrapling MCP's `get` already renders JS — no `fetch` needed unless Cloudflare
- **Anti-bot**: Use `stealthy_headers: true`. For Cloudflare, `scrapling_stealthy_fetch`
- **Infinite scroll**: `scrapling_open_session` + `scrapling_fetch` + click "load more"
- **Two-phase portals**: Cards missing fields → collect detail URLs → `scrapling_bulk_get` detail pages
- **Hidden JSON**: Some portals have JSON in `<textarea>` — visible in text output, parse inline
