#!/usr/bin/env python3
"""Scrape Proser Inmobiliaria Medellín rental listings."""

import argparse
import sys

sys.path.insert(0, ".")

from scrape.cli import create_parser, run_scraper
from scrape.proserinmobiliaria import scrape


def main(args: argparse.Namespace | None = None) -> int:
    """Run the Proser scraper through the shared CLI."""
    if args is None:
        parser = create_parser("proserinmobiliaria", "Scrape Proser Medellín rental listings")
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
