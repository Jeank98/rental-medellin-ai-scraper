#!/usr/bin/env python3
"""Scrape Inmobiliaria La Estrella rental listings."""

import argparse
import sys

sys.path.insert(0, ".")

from scrape.cities import resolve_city
from scrape.cli import create_parser, run_scraper
from scrape.inmobiliarialaestrella import scrape


def main(args: argparse.Namespace | None = None) -> int:
    """Run Inmobiliaria La Estrella through the shared scraper CLI."""
    parser = create_parser(
        "inmobiliarialaestrella",
        "Scrape Inmobiliaria La Estrella rental listings",
    )
    if args is None:
        args = parser.parse_args()
    args.ciudad = resolve_city(args.ciudad)
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
