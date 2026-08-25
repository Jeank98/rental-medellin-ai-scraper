#!/usr/bin/env python3
"""Scrape Portada Inmobiliaria rental listings (Medellin)."""

import argparse
import sys

sys.path.insert(0, ".")

from scrape.cli import create_parser, run_scraper


def main(args=None):
    """Run the Portada scraper through the shared CLI."""
    if args is None:
        args = argparse.Namespace(
            portal="portadainmobiliaria",
            output="both",
            ciudad="medellin",
            sample_only=True,
            max_pages=1,
            verbose=False,
        )
    from scrape.portadainmobiliaria import scrape

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
        "portadainmobiliaria",
        "Scrape Portada Inmobiliaria rental listings (Medellin)",
    )
    sys.exit(main(parser.parse_args()))
