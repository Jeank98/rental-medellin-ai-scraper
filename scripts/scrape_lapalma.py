#!/usr/bin/env python3
"""Scrape La Palma Inmobiliaria rental listings."""

import sys

sys.path.insert(0, ".")

from scrape.cli import create_parser, run_scraper
from scrape.lapalma import scrape


def main(args=None):
    """Run the La Palma scraper through the shared CLI."""
    if args is None:
        parser = create_parser(
            "lapalmainmobiliaria", "Scrape La Palma Inmobiliaria rental listings"
        )
        args = parser.parse_args()
    return run_scraper(
        lambda: scrape(
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
