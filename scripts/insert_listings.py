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
    flagged = []
    for item in data:
        item["ciudad"] = ciudad
        if not portal:
            portal = item.get("portal", "")
        
        # === VALIDATION ===
        issues = []
        
        # Price: must be > 100,000 COP (minimum realistic rent)
        precio = item.get("precio", 0)
        if 0 < precio < 100000:
            issues.append(f"precio={precio} too low → 0")
            item["precio"] = 0
        if precio > 500_000_000:
            issues.append(f"precio={precio:,} unusually high")
        
        # Area: must be in reasonable range
        area = item.get("area", 0)
        if area > 10000:
            issues.append(f"area={area} unusually high")
        
        # Habitaciones: 0-30 range
        hab = item.get("habitaciones", 0)
        if hab > 30:
            issues.append(f"habitaciones={hab} > 30")
        
        # Banos: 0-20 range
        banos = item.get("banos", 0)
        if banos > 20:
            issues.append(f"banos={banos} > 20")
        
        # Parqueaderos: 0-10 range (flag > 5)
        parq = item.get("parqueaderos", 0)
        if parq > 10:
            issues.append(f"parqueaderos={parq} > 10")
        
        # Estrato: 0-6 (Colombia range; flag 7+)
        estrato = item.get("estrato", 0)
        if estrato > 6:
            issues.append(f"estrato={estrato} > 6 (Colombia max)")
        
        # Barrio: must not be empty, must not contain code/price artifacts
        barrio = item.get("barrio", "")
        if not barrio:
            issues.append("barrio is empty")
        elif any(kw in barrio.lower() for kw in ['código', 'code:', 'arriendo', '$', 'rent:']):
            issues.append(f"barrio contains artifacts: {barrio[:60]}")
            # Try to salvage: take first part before "."
            item["barrio"] = barrio.split('.')[0].strip()
        
        # URL: must be absolute, must not have en. subdomain
        url = item.get("url", "")
        if url and not url.startswith("http"):
            issues.append(f"url not absolute: {url[:50]}")
        if 'en.habitamos' in url:
            issues.append("url has en. subdomain")
            item["url"] = url.replace('en.habitamos.com.co', 'habitamos.com.co')
        if not url:
            issues.append("url is empty")
        
        # ID: must not be empty, must not contain price artifacts
        eid = item.get("id", "")
        if not eid:
            issues.append("id is empty")
        elif any(kw in eid.lower() for kw in ['rent:', 'sale:', '$']):
            issues.append(f"id contains price artifacts: {eid}")
            # Extract numeric code
            import re
            m = re.search(r'(\d+)', eid)
            if m and item.get("portal"):
                item["id"] = f"{item['portal'][:3].upper()}-{m.group(1)}"
        
        # Tipo: must not be empty
        tipo = item.get("tipo", "")
        if not tipo:
            issues.append("tipo is empty")
        elif tipo in ('arriendo', 'venta', 'for lease', 'for sale'):
            issues.append(f"tipo is transaction type, not property type: {tipo}")
        
        if issues:
            flagged.append({"id": eid, "issues": issues})
        
        rows.append(item)
    
    if flagged:
        print(f"⚠️  {len(flagged)} listings flagged:")
        for f in flagged[:5]:
            print(f"  {f['id']}: {', '.join(f['issues'])}")
        if len(flagged) > 5:
            print(f"  ... and {len(flagged)-5} more")

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
