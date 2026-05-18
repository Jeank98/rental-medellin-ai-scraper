#!/usr/bin/env python3
"""Create the listings table in Neon."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import create_tables, test_connection

if __name__ == "__main__":
    if not test_connection():
        print("ERROR: Could not connect to database. Check your DATABASE_URL in .env")
        sys.exit(1)

    create_tables()
    print("Table 'listings' created successfully (or already exists).")
