#!/usr/bin/env python3
"""Test: insert a sample listing and read it back."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import create_tables, insert_listing, get_count, get_all

if __name__ == "__main__":
    create_tables()

    test_row = {
        "id": "TEST-001",
        "portal": "test_portal",
        "tipo": "apartamento",
        "precio": 1450000,
        "area": 65,
        "habitaciones": 2,
        "banos": 1,
        "parqueaderos": 1,
        "estrato": 4,
        "barrio": "Laureles",
        "url": "https://example.com/propiedad/001",
        "ciudad": "medellin",
    }

    insert_listing(test_row)
    print(f"Inserted test row. Total rows: {get_count()}")

    rows = get_all()
    for r in rows:
        print(f"  {r['id']} | {r['tipo']} | {r['precio']:,} COP | {r['barrio']} | {r['ciudad']}")
