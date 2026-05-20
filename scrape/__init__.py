"""Scrape package — shared utilities for Colombian real estate portal scrapers.

Provides fetcher, normalizer, validator, and output writer functions
that are used by thin CLI scripts in scripts/ and per-portal modules.
"""

from scrape.fetcher import fetch_page, fetch_json, bulk_fetch
from scrape.normalize import (
    normalize_price,
    normalize_tipo,
    normalize_estrato,
    normalize_garaje,
    normalize_barrio,
    normalize_url,
    TIPO_MAPPING,
)
from scrape.validator import validate
from scrape.db_writer import write_to_db
from scrape.csv_writer import write_to_csv
from scrape.cli import create_parser, run_scraper

__all__ = [
    "fetch_page",
    "fetch_json",
    "bulk_fetch",
    "normalize_price",
    "normalize_tipo",
    "normalize_estrato",
    "normalize_garaje",
    "normalize_barrio",
    "normalize_url",
    "TIPO_MAPPING",
    "validate",
    "write_to_db",
    "write_to_csv",
    "create_parser",
    "run_scraper",
]
