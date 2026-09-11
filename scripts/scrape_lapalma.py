#!/usr/bin/env python3
"""Scrape La Palma Inmobiliaria rental listings."""

import sys

sys.path.insert(0, ".")

from scrape.cli import create_parser, run_scraper
from scrape.lapalma import scrape


def main(args=None):
    """Run the La Palma scraper through the shared CLI."""
    parser = create_parser(
        "lapalmainmobiliaria", "Scrape La Palma Inmobiliaria rental listings"
    )
    parser.add_argument(
        "--reuse-unchanged-details",
        action="store_true",
        help="Reuse active DB detail fields for price-stable listings",
    )
    if args is None:
        args = parser.parse_args()
    return run_scraper(
        lambda: scrape(
            ciudad=args.ciudad,
            sample_only=args.sample_only,
            max_pages=args.max_pages,
            verbose=args.verbose,
            reuse_unchanged_details=getattr(args, "reuse_unchanged_details", False),
        ),
        portal=args.portal,
        args=args,
    )


if __name__ == "__main__":
    sys.exit(main())
