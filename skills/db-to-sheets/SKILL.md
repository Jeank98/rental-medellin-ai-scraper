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

Export real rental listings from the PostgreSQL database to a Google Sheets spreadsheet using the Google Sheets API. The agent runs a Python script that reads the database, authenticates via OAuth 2.0 desktop flow, and writes all rows with formatting.

**Auto-filters applied:**
- `precio >= 200.000 COP` — excludes placeholder/error listings
- `tipo IN (apartamento, apto, casa, casa-finca, casa unifamiliar)` — excludes commercial, lots, offices, etc.

Exported columns: `id`, `portal`, `tipo`, `precio`, `area`, `habitaciones`, `banos`, `parqueaderos`, `estrato`, `barrio`, `url`, `ciudad`, `status`, `scraped_at`

The script can operate in two modes:

- **In-place update**: If `GOOGLE_SHEET_ID` is set in `.env`, the target sheet is cleared and repopulated with fresh DB data on each run — the sheet acts as a live mirror of the database.
- **New sheet creation**: If `GOOGLE_SHEET_ID` is not set (or `--new` is used), a new spreadsheet is created. Optionally placed in a Drive folder via `GOOGLE_SHEET_FOLDER_ID`.

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

### Filter by portal

```bash
uv run python scripts/export_to_sheets.py --portal maxibienes
```

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
3. Reads all listings from `db.get_all()` with optional `--city` and `--portal` filters
4. **If `GOOGLE_SHEET_ID` is set** (and `--new` not passed):
   - Clears ALL content from the existing sheet
   - Rewrites fresh data with headers
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
| No listings found | Prints "No listings found" and exits gracefully |
| Sheets API quota exceeded | Prints clear error message |
| Invalid or inaccessible `GOOGLE_SHEET_ID` | Prints permission/not-found error and exits |
| Invalid `GOOGLE_SHEET_FOLDER_ID` | Warns and places sheet in root instead |

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
4. Report the sheet URL to the user
5. If a new sheet was created, remind the user to add `GOOGLE_SHEET_ID` to `.env` for in-place updates on future runs

**Never hardcode Google credentials.** Always read them from the user's `.env` file.
