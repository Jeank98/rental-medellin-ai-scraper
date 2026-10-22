#!/usr/bin/env python3
"""Scrape Lonja Inmobiliaria del Sur rental listings."""

import argparse
import sys

sys.path.insert(0, ".")

from scrape.cities import resolve_city
from scrape.cli import create_parser, run_scraper
from scrape.lonjainmobiliariadelsur import scrape


def main(args: argparse.Namespace | None = None) -> int:
    """Run the Lonja scraper through the shared CLI."""
    parser = create_parser(
        "lonjainmobiliariadelsur",
        "Scrape Lonja Inmobiliaria del Sur rental listings",
    )
    if args is None:
        args = parser.parse_args()
    try:
        args.ciudad = resolve_city(args.ciudad)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
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
