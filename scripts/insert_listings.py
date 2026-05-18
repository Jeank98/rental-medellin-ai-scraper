#!/usr/bin/env python3
"""Insert scraped listings into PostgreSQL from a JSON file.

Usage:
    uv run python scripts/insert_listings.py <json_file> <ciudad>

JSON format: list of objects with keys matching the listings table columns.
"""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import create_tables, insert_listings, get_count, test_connection, get_conn


def main():
    if len(sys.argv) != 3:
        print("Usage: uv run python scripts/insert_listings.py <json_file> <ciudad>")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    ciudad = sys.argv[2].strip().lower()

    if not json_path.exists():
        print(f"ERROR: File not found: {json_path}")
        sys.exit(1)

    if not test_connection():
        print("ERROR: Could not connect to database. Check your DATABASE_URL in .env")
        sys.exit(1)

    create_tables()

    with open(json_path) as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("ERROR: JSON must be a list of listing objects")
        sys.exit(1)

    rows = []
    portal = ""
    for item in data:
        item["ciudad"] = ciudad
        if not portal:
            portal = item.get("portal", "")
        rows.append(item)

    before = get_count()

    # Count how many will become inactive
    inactive_before = 0
    if portal and ciudad:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM listings WHERE portal=%s AND ciudad=%s AND status='active'",
                    (portal, ciudad)
                )
                inactive_before = cur.fetchone()[0]

    insert_listings(rows)
    after = get_count()

    # Count currently inactive
    inactive_after = 0
    if portal and ciudad:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM listings WHERE portal=%s AND ciudad=%s AND status='inactive'",
                    (portal, ciudad)
                )
                inactive_after = cur.fetchone()[0]

    new_rows = after - before
    updated = len(rows) - new_rows
    print(f"Scraped: {len(rows)} | New: {new_rows} | Refreshed: {updated} | Total in DB: {after}")
    if inactive_after > 0:
        print(f"Now inactive (delisted): {inactive_after}")

    # show first 3 and last 3 active
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tipo, precio, barrio, area FROM listings WHERE portal=%s AND ciudad=%s AND status='active' ORDER BY id",
                (portal, ciudad)
            )
            active = cur.fetchall()
            if active:
                print("\nSample (first 3):")
                for r in active[:3]:
                    print(f"  {r[0]} | {r[1]} | {r[2]:,} COP | {r[3]} | {r[4]}m²")
                if len(active) > 3:
                    print("  ...")
                    for r in active[-3:]:
                        print(f"  {r[0]} | {r[1]} | {r[2]:,} COP | {r[3]} | {r[4]}m²")


if __name__ == "__main__":
    main()
