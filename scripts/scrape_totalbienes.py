#!/usr/bin/env python3
"""Scrape Total Bienes SAS rental listings in Medellin."""

import argparse
import sys

sys.path.insert(0, ".")

from scrape.cli import create_parser, run_scraper


def main(args: argparse.Namespace | None = None) -> int:
    """Run Total Bienes through the shared scraper CLI."""
    if args is None:
        args = argparse.Namespace(
            portal="totalbienes",
            output="both",
            ciudad="medellin",
            sample_only=True,
            max_pages=1,
            verbose=False,
        )
    from scrape.totalbienes import scrape

    return run_scraper(
        lambda: scrape(
            ciudad=args.ciudad,
            sample_only=args.sample_only,
            max_pages=args.max_pages,
            verbose=args.verbose,
        ),
        portal=args.portal,
        args=args,
    )


if __name__ == "__main__":
    parser = create_parser(
        "totalbienes", "Scrape Total Bienes SAS rental listings (Medellin)"
    )
    sys.exit(main(parser.parse_args()))
