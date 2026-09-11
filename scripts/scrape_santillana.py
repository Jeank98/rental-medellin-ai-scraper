#!/usr/bin/env python3
"""Scrape Santillana rental listings."""

import sys

sys.path.insert(0, ".")

from scrape.cli import create_parser, run_scraper
from scrape.santillana import scrape


def main(args=None) -> int:
    parser = create_parser("santillana", "Scrape Santillana rental listings")
    parser.add_argument(
        "--reuse-unchanged-details",
        action="store_true",
        help="Reuse prior active DB enrichment when Santillana card ID and price match",
    )
    args = args or parser.parse_args()
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


if __name__ == "__main__":
    sys.exit(main())
