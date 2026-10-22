---
name: db-to-sheets
description: "Trigger: export to sheets, exportar a sheets, migrate to google sheets, db to spreadsheet. Export PostgreSQL listings to a Google Sheets spreadsheet."
license: MIT
compatibility: opencode
metadata:
  audience: all
  workflow: db-to-sheets-export
---

## What I Do

Export active rental listings from the PostgreSQL database to a Google Sheets
live mirror using the Google Sheets API. The agent runs a Python script that
reads the database, authenticates via OAuth 2.0 desktop flow, and writes the
filtered rows with formatting.

**Auto-filters applied:**
- `status == active` — inactive/delisted history stays in PostgreSQL but is
  never copied to the live mirror (legacy in-memory rows missing `status` are
  treated as active)
- `precio >= 200.000 COP` — excludes placeholder/error listings
- `tipo IN (apartamento, apto, apartaestudio, casa, casa-finca, casa unifamiliar)` —
  excludes commercial, lots, and offices

The shared mirror (`GOOGLE_SHEET_ID`) is **unfiltered by city and portal**:
eligible active rows from every municipality and portal are included, subject
to the price and property-type filters above. A Medellín-only run must retain
the other municipalities. `--city` and
`--portal` remain available for standalone filtered exports, but they replace
the target sheet's contents; use `--new` (or a separate sheet) when the filtered
export must coexist with the shared mirror.

Exported columns are the 14-column DB shape: the canonical 11 listing fields
plus `ciudad`, `status`, and `scraped_at`. CSV output remains a separate
11-column format; see `docs/columns-spec.md`.

> **Run after a full scrape**: the spreadsheet is fed from PostgreSQL, so
> export after a complete scrape, not a capped collection. The selected runner
> skips Sheets on any failure. `scripts/run_all.py --fail-fast` skips Sheets
> after a scraper failure; normal `run_all.py` mode may export after healthy
> portals finish despite another portal failing. Both runners block publication
> when a required backup fails.

The script can operate in two modes:

- **In-place update**: If `GOOGLE_SHEET_ID` is set in `.env`, the target sheet
  is cleared and repopulated with the current active DB mirror on each run.
- **New sheet creation**: If `GOOGLE_SHEET_ID` is not set (or `--new` is used),
  a new spreadsheet is created. Optionally placed in a Drive folder via
  `GOOGLE_SHEET_FOLDER_ID`.

---

## Prerequisites

### Google Cloud Setup (one-time, per user)

1. Go to https://console.cloud.google.com/auth/clients/create
2. Select **Application type: Desktop app**
3. Give it a name (e.g. "Rental Scraper Export")
4. Download the client ID and client secret
5. Add them to `.env`:
   ```
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-your-client-secret
   ```

### Dependencies

The project already includes:
- `google-api-python-client`
- `google-auth-oauthlib`
- `python-dotenv` (for `.env` loading)

A working PostgreSQL database via `DATABASE_URL` in `.env`.

---

## Usage

### Basic export (all listings)

```bash
uv run python scripts/export_to_sheets.py
```

### Force new sheet (ignore GOOGLE_SHEET_ID)

```bash
uv run python scripts/export_to_sheets.py --new
```

### Filter by city

```bash
uv run python scripts/export_to_sheets.py --city medellin
```

This is a standalone filtered export. If `GOOGLE_SHEET_ID` points at the shared
mirror, add `--new` so other cities are not dropped from the shared sheet.

### Filter by portal

```bash
uv run python scripts/export_to_sheets.py --portal maxibienes
```

`--portal accrecer` exports only Acrecer's rows. The same shared-mirror warning
applies: use `--new` for a filtered standalone sheet.

### Custom sheet title

```bash
uv run python scripts/export_to_sheets.py --title "My Custom Export"
```

### Combine filters

```bash
uv run python scripts/export_to_sheets.py --city medellin --portal maxibienes --title "Medellín - Maxibienes"
```

---
## What Happens

1. Script loads `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from `.env`
2. On **first run**, opens a browser for OAuth consent. Token is saved to `~/.config/gworkspace-tools/token.json`. Subsequent runs reuse the saved token (including refresh).
3. Reads PostgreSQL listings and applies the active-status, price, and
   property-type filters described above, plus `--city`/`--portal` only when
   explicitly requested for a standalone export
4. **If `GOOGLE_SHEET_ID` is set** (and `--new` not passed):
   - Clears ALL content from the existing sheet
   - Rewrites the current active data with headers
   - With no `--city`/`--portal` filters this preserves every active city; with
     a filter it replaces the shared mirror with that subset, so use `--new`
     unless you intend that replacement
   - Re-applies formatting (bold header, frozen row, column widths)
   - Deletes any extra sheets beyond the first one
   - The sheet URL stays the same — no new link to share
5. **If `GOOGLE_SHEET_ID` is NOT set** (or `--new` is passed):
   - Creates a new sheet titled `"Rental Listings Export - {timestamp}"` (or custom `--title`)
   - If `GOOGLE_SHEET_FOLDER_ID` is set, places the new sheet in that Drive folder
   - Prints the new sheet URL and the `GOOGLE_SHEET_ID` to add to `.env` for future in-place updates

---

## Error Handling

| Error | What happens |
|---|---|
| Missing `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Prints setup instructions and exits |
| Token expired/revoked | Automatically re-triggers OAuth browser flow |
| Database connection fails | Prints error and exits |
| No active listings match filters | Prints "No listings found" and exits gracefully |
| Sheets API quota exceeded | Prints clear error message |
| Invalid or inaccessible `GOOGLE_SHEET_ID` | Prints permission/not-found error and exits |
| Invalid `GOOGLE_SHEET_FOLDER_ID` | Warns and places sheet in root instead |

The full scraper pipeline writes a structured `SCRAPER_RESULT` marker for each
portal. Its pre-write backup state is `success`, `skipped`, or `failed`; a
required failed backup prevents both DB and Sheets writes. See
`docs/operations.md` for pipeline recovery and zero-result semantics.
---

## Token Storage

- OAuth tokens saved at `~/.config/gworkspace-tools/token.json`
- Includes refresh token — user only authenticates once
- Directory is created automatically on first run

---

## Agent Instructions

When a user asks to export to Google Sheets:

1. Verify Google credentials exist in `.env` (read `.env.example` to see the format; do NOT read `.env`)
2. If missing, tell the user to follow the **Google Cloud Setup** section above
3. Run the script with the user's requested filters:
   ```bash
   uv run python scripts/export_to_sheets.py [--city CITY] [--portal PORTAL] [--title TITLE] [--new]
   ```
   Leave the shared mirror unfiltered unless the user explicitly wants that
   subset to replace it; prefer `--new` for filtered exports.
4. Report the sheet URL to the user
5. If a new sheet was created, remind the user to add `GOOGLE_SHEET_ID` to `.env` for in-place updates on future runs

**Never hardcode Google credentials.** Always read them from the user's `.env` file.
