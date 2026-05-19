#!/usr/bin/env python3
"""Export real rental listings from PostgreSQL to a Google Sheets spreadsheet.

Filters applied automatically:
  - precio >= 200,000 COP (excludes placeholder/free listings)
  - tipo IN (apartamento, apto, casa, casa-finca, casa unifamiliar)

If GOOGLE_SHEET_ID is set in .env, clears and repopulates an existing sheet
in-place (live DB mirror). Otherwise creates a new sheet, optionally in
GOOGLE_SHEET_FOLDER_ID. Use --new to force creation even when GOOGLE_SHEET_ID
is set.

Usage:
    uv run python scripts/export_to_sheets.py [--title TITLE] [--city CITY] [--portal PORTAL] [--new]

Requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env.
First run opens a browser for OAuth consent; tokens are saved to
~/.config/gworkspace-tools/token.json for subsequent runs.
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from db import get_all, test_connection

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]

TOKEN_DIR = Path.home() / ".config" / "gworkspace-tools"
TOKEN_FILE = TOKEN_DIR / "token.json"

# Only export these property types (others are filtered out)
ALLOWED_TIPOS = {"apartamento", "apto", "casa", "casa-finca", "casa unifamiliar"}

# Minimum price in COP — anything below is likely an error or placeholder
MIN_PRICE = 200_000

HEADERS = [
    "id",
    "portal",
    "tipo",
    "precio",
    "area",
    "habitaciones",
    "banos",
    "parqueaderos",
    "estrato",
    "barrio",
    "url",
    "ciudad",
    "status",
    "scraped_at",
]

COLUMN_WIDTHS = {
    0: 140,   # id
    1: 100,   # portal
    2: 100,   # tipo
    3: 100,   # precio
    4: 70,    # area
    5: 80,    # habitaciones
    6: 70,    # banos
    7: 80,    # parqueaderos
    8: 70,    # estrato
    9: 120,   # barrio
    10: 320,  # url
    11: 100,  # ciudad
    12: 80,   # status
    13: 180,  # scraped_at
}


def get_credentials():
    """Obtain valid OAuth 2.0 credentials, triggering browser flow if needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("ERROR: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")
        print("Create OAuth 2.0 credentials at: https://console.cloud.google.com/auth/clients/create")
        print("Application type: Desktop app")
        sys.exit(1)

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            pass

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_DIR.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(creds.to_json())
            return creds
        except Exception:
            pass

    # No valid credentials — start OAuth flow
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    try:
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = flow.run_local_server(port=0)
    except Exception as e:
        print(f"ERROR: OAuth flow failed: {e}")
        print("Check that GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env are correct.")
        print("Also verify the OAuth consent screen has the Desktop app type.")
        sys.exit(1)

    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json())
    print(f"Token saved to {TOKEN_FILE}")
    return creds


def build_sheets_service():
    """Build and return an authorized Google Sheets API service."""
    from googleapiclient.discovery import build

    creds = get_credentials()
    return build("sheets", "v4", credentials=creds)


def build_drive_service():
    """Build and return an authorized Google Drive API service."""
    from googleapiclient.discovery import build

    creds = get_credentials()
    return build("drive", "v3", credentials=creds)


def fetch_listings(city=None, portal=None):
    """Fetch listings from the database with optional filters.

    Always applies MIN_PRICE and ALLOWED_TIPOS filters.
    """
    all_rows = get_all()

    if city:
        city_lower = city.lower()
        all_rows = [r for r in all_rows if r.get("ciudad", "").lower() == city_lower]

    if portal:
        portal_lower = portal.lower()
        all_rows = [r for r in all_rows if r.get("portal", "").lower() == portal_lower]

    # Filter out listings below minimum price
    all_rows = [r for r in all_rows if int(r.get("precio", 0)) >= MIN_PRICE]

    # Filter to only allowed property types
    all_rows = [r for r in all_rows if r.get("tipo", "").lower() in ALLOWED_TIPOS]

    return all_rows


def rows_to_values(rows):
    """Convert DB rows to a list of lists suitable for Sheets API."""
    values = [HEADERS]
    for row in rows:
        values.append([
            row.get("id", ""),
            row.get("portal", ""),
            row.get("tipo", ""),
            row.get("precio", 0),
            row.get("area", 0),
            row.get("habitaciones", 0),
            row.get("banos", 0),
            row.get("parqueaderos", 0),
            row.get("estrato", 0),
            row.get("barrio", ""),
            row.get("url", ""),
            row.get("ciudad", ""),
            row.get("status", ""),
            str(row.get("scraped_at", "")),
        ])
    return values


def _sheet_range(name):
    """Wrap sheet name in single quotes for A1 notation if it contains spaces."""
    if any(c in name for c in " !@#$%^&*()+-=,.<>/?;:'\"[]{}|`~"):
        return f"'{name}'"
    return name


def apply_formatting(service, spreadsheet_id, sheet_id):
    """Apply bold header, freeze row, and column widths to a sheet."""
    from googleapiclient.errors import HttpError

    format_requests = []

    # Bold header row
    format_requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"bold": True},
                },
            },
            "fields": "userEnteredFormat.textFormat.bold",
        }
    })

    # Freeze header row
    format_requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {
                    "frozenRowCount": 1,
                },
            },
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # Column widths
    for col_idx, width in COLUMN_WIDTHS.items():
        format_requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex": col_idx + 1,
                },
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        })

    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": format_requests},
        ).execute()
    except HttpError as e:
        print(f"WARNING: Formatting failed (data was written): {e}")


def update_existing_sheet(service, sheet_id, rows, title=None):
    """Clear an existing sheet and repopulate with fresh data.

    Deletes extra sheets beyond the first to keep the spreadsheet clean.
    """
    from googleapiclient.errors import HttpError

    # Verify the sheet exists
    try:
        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    except HttpError as e:
        if e.resp.status == 404:
            print(f"ERROR: Sheet with ID '{sheet_id}' not found.")
            print("Check that GOOGLE_SHEET_ID in .env is correct.")
        elif e.resp.status == 403:
            print(f"ERROR: No permission to access sheet '{sheet_id}'.")
            print("Make sure the sheet is shared with the authenticated Google account.")
        else:
            print(f"ERROR: Failed to access sheet: {e}")
        sys.exit(1)

    sheets = spreadsheet.get("sheets", [])
    first_sheet = sheets[0]
    first_sheet_name = first_sheet["properties"]["title"]

    # Rename spreadsheet if title is provided
    if title:
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={
                    "requests": [{
                        "updateSpreadsheetProperties": {
                            "properties": {"title": title},
                            "fields": "title",
                        }
                    }]
                },
            ).execute()
        except HttpError as e:
            print(f"WARNING: Could not rename spreadsheet: {e}")

    # Clear all content from the first sheet
    try:
        service.spreadsheets().values().clear(
            spreadsheetId=sheet_id,
            range=_sheet_range(first_sheet_name),
        ).execute()
    except HttpError as e:
        print(f"ERROR: Failed to clear sheet: {e}")
        sys.exit(1)

    # Write fresh data
    values = rows_to_values(rows)
    range_str = f"{_sheet_range(first_sheet_name)}!A1:{chr(65 + len(HEADERS) - 1)}{len(values)}"

    try:
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=range_str,
            body={"values": values},
            valueInputOption="USER_ENTERED",
        ).execute()
    except HttpError as e:
        error_reason = str(e)
        if "quota" in error_reason.lower() or "rate" in error_reason.lower():
            print(f"ERROR: Google Sheets API quota exceeded: {e}")
        else:
            print(f"ERROR: Failed to write data: {e}")
        sys.exit(1)

    # Re-apply formatting to the first sheet (sheetId 0)
    apply_formatting(service, sheet_id, 0)

    # Delete extra sheets beyond the first
    extra_sheets = sheets[1:]
    if extra_sheets:
        delete_requests = []
        for sheet in extra_sheets:
            delete_requests.append({
                "deleteSheet": {
                    "sheetId": sheet["properties"]["sheetId"],
                }
            })

        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={"requests": delete_requests},
            ).execute()
        except HttpError as e:
            print(f"WARNING: Failed to delete extra sheets: {e}")

    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


def create_and_populate_sheet(service, title, rows, folder_id=None):
    """Create a new spreadsheet, optionally in a folder, populate, and format."""
    from googleapiclient.errors import HttpError

    try:
        spreadsheet = service.spreadsheets().create(
            body={"properties": {"title": title}}
        ).execute()
    except HttpError as e:
        print(f"ERROR: Failed to create spreadsheet: {e}")
        sys.exit(1)

    new_sheet_id = spreadsheet["spreadsheetId"]
    sheet_url = spreadsheet["spreadsheetUrl"]

    # Move to folder if requested
    if folder_id:
        try:
            drive_service = build_drive_service()
            drive_service.files().update(
                fileId=new_sheet_id,
                addParents=folder_id,
                removeParents="root",
            ).execute()
        except HttpError as e:
            if e.resp.status == 404:
                print(f"WARNING: Folder not found ('{folder_id}'). Sheet created in root.")
            else:
                print(f"WARNING: Could not move sheet to folder: {e}. Sheet created in root.")

    values = rows_to_values(rows)
    range_str = f"A1:{chr(65 + len(HEADERS) - 1)}{len(values)}"

    try:
        service.spreadsheets().values().update(
            spreadsheetId=new_sheet_id,
            range=range_str,
            body={"values": values},
            valueInputOption="USER_ENTERED",
        ).execute()
    except HttpError as e:
        error_reason = str(e)
        if "quota" in error_reason.lower() or "rate" in error_reason.lower():
            print(f"ERROR: Google Sheets API quota exceeded: {e}")
        else:
            print(f"ERROR: Failed to write data: {e}")
        sys.exit(1)

    apply_formatting(service, new_sheet_id, 0)

    return sheet_url


def main():
    parser = argparse.ArgumentParser(
        description="Export PostgreSQL listings to Google Sheets"
    )
    parser.add_argument(
        "--title",
        help="Custom sheet title (default: 'Rental Listings Export - <timestamp>')",
    )
    parser.add_argument("--city", help="Filter listings by city (case-insensitive)")
    parser.add_argument("--portal", help="Filter listings by portal (case-insensitive)")
    parser.add_argument(
        "--new",
        action="store_true",
        help="Force creation of a new sheet even if GOOGLE_SHEET_ID is set in .env",
    )
    args = parser.parse_args()

    if not test_connection():
        print("ERROR: Could not connect to database. Check DATABASE_URL in .env")
        sys.exit(1)

    rows = fetch_listings(city=args.city, portal=args.portal)

    if not rows:
        print("No listings found in the database.")
        sys.exit(0)

    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    folder_id = os.getenv("GOOGLE_SHEET_FOLDER_ID", "").strip() or None
    title = args.title or f"Rental Listings Export - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    print(f"Exporting {len(rows)} listings to Google Sheets...")

    service = build_sheets_service()

    if sheet_id and not args.new:
        url = update_existing_sheet(service, sheet_id, rows, args.title)
        print(f"\nDone! Sheet updated: {url}")
    else:
        url = create_and_populate_sheet(service, title, rows, folder_id)
        print(f"\nDone! Sheet URL: {url}")

        new_sheet_id = url.split("/d/")[1].split("/")[0]
        print()
        print(f"Add this to your .env for in-place updates on future runs:")
        print(f"GOOGLE_SHEET_ID={new_sheet_id}")
        print()
        print("Add GOOGLE_SHEET_ID to your .env to update this sheet in-place on future runs")


if __name__ == "__main__":
    main()
