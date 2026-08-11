#!/usr/bin/env python3
"""Scrape Zitios Inmobiliaria rental listings for Medellín."""

import argparse
import sys

sys.path.insert(0, ".")

from scrape.cli import create_parser, run_scraper
from scrape.zitios import scrape


def main(args: argparse.Namespace | None = None) -> int:
    """Run the Zitios scraper through the shared CLI dispatcher."""
    if args is None:
        parser = create_parser("zitios", "Scrape Zitios Inmobiliaria rental listings")
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
