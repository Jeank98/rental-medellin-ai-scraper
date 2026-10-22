#!/usr/bin/env python3
"""Scrape Escala Inmobiliaria rental listings."""

import argparse
import sys

sys.path.insert(0, ".")

from scrape.cities import resolve_city
from scrape.cli import create_parser, run_scraper


def main(args: argparse.Namespace | None = None) -> int:
    """Run the Escala scraper through the shared CLI."""
    if args is None:
        args = create_parser(
            "escalainmobiliaria", "Scrape Escala Inmobiliaria rental listings"
        ).parse_args()

    # Canonicalize before the shared runner writes CSV/DB so the storage scope
    # is the same key every other portal uses.
    ciudad = resolve_city(args.ciudad)
    args.ciudad = ciudad

    from scrape.escalainmobiliaria import scrape

    return run_scraper(
        lambda: scrape(
            ciudad=ciudad,
            sample_only=args.sample_only,
            max_pages=args.max_pages,
            verbose=args.verbose,
        ),
        portal=getattr(args, "portal", None) or "escalainmobiliaria",
        args=args,
    )


if __name__ == "__main__":
    sys.exit(main())
