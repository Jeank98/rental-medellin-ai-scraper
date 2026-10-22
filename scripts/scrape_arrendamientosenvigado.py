#!/usr/bin/env python3
"""Scrape Arrendamientos Envigado rental listings."""

import argparse
import sys

sys.path.insert(0, ".")

from scrape.arrendamientosenvigado import scrape
from scrape.cities import resolve_city
from scrape.cli import create_parser, run_scraper


def main(args: argparse.Namespace | None = None) -> int:
    parser = create_parser(
        "arrendamientosenvigado",
        "Scrape Arrendamientos Envigado rental listings",
    )
    if args is None:
        args = parser.parse_args()

    # DB/CSV scope must use the canonical city slug, not the free-form CLI alias.
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
