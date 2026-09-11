#!/usr/bin/env python3
"""Scrape Arrendamientos Monserrate rental listings."""
import argparse
import sys

sys.path.insert(0, ".")

from scrape.arrendamientosmonserrate import scrape
from scrape.cli import create_parser, run_scraper


def main(args: argparse.Namespace | None = None) -> int:
    parser = create_parser(
        "arrendamientosmonserrate",
        "Scrape Arrendamientos Monserrate rental listings",
    )
    parser.add_argument(
        "--reuse-unchanged-details",
        action="store_true",
        help="Reuse active detail fields when the listing URL and price are unchanged",
    )
    if args is None:
        args = parser.parse_args()
    return run_scraper(
        scraper_fn=lambda: scrape(
            ciudad=args.ciudad,
            sample_only=args.sample_only,
            max_pages=args.max_pages,
            verbose=args.verbose,
            reuse_unchanged_details=getattr(args, "reuse_unchanged_details", False),
        ),
        portal=args.portal,
        args=args,
    )


if __name__ == '__main__':
    sys.exit(main())
