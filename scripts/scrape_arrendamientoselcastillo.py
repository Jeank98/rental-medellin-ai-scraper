#!/usr/bin/env python3
"""Scrape Arrendamientos El Castillo rental listings."""

import argparse
import sys

sys.path.insert(0, ".")

from scrape.arrendamientoselcastillo import scrape
from scrape.cli import create_parser, run_scraper


def main(args: argparse.Namespace | None = None) -> int:
    """Run El Castillo through the shared scraper CLI."""
    if args is None:
        args = create_parser(
            "arrendamientoselcastillo",
            "Scrape Arrendamientos El Castillo rental listings (Medellín)",
        ).parse_args()
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
