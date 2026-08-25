#!/usr/bin/env python3
"""Scrape Arango Tobón Inmobiliaria Medellín rental listings."""

import argparse
import sys

sys.path.insert(0, ".")

from scrape.arangotobon import scrape
from scrape.cli import create_parser, run_scraper


def main(args: argparse.Namespace | None = None) -> int:
    """Run the Arango Tobón scraper through the shared CLI."""
    if args is None:
        parser = create_parser("arangotobon", "Scrape Arango Tobón Medellín rental listings")
        args = parser.parse_args()
    return run_scraper(
        scraper_fn=lambda: scrape(
            ciudad=args.ciudad,
            sample_only=args.sample_only,
            max_pages=args.max_pages,
            verbose=args.verbose,
        ),
        portal=args.portal,
        args=args,
    )


if __name__ == "__main__":
    sys.exit(main())
