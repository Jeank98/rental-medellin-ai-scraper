#!/usr/bin/env python3
"""Scrape Proser Inmobiliaria Medellín rental listings."""

import argparse
import sys

sys.path.insert(0, ".")

from scrape.cli import create_parser, run_scraper
from scrape.proserinmobiliaria import scrape


def main(args: argparse.Namespace | None = None) -> int:
    """Run the Proser scraper through the shared CLI."""
    parser = create_parser(
        "proserinmobiliaria",
        "Scrape Proser Medellín rental listings",
    )
    parser.add_argument(
        "--reuse-unchanged-details",
        action="store_true",
        help="Reuse verified active detail fields when the listing price is unchanged",
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


if __name__ == "__main__":
    sys.exit(main())
