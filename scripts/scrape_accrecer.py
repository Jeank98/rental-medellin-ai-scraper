#!/usr/bin/env python3
"""Scrape Acrecer rental listings (Medellín)."""
import argparse
import sys
sys.path.insert(0, '.')

from scrape.cli import create_parser, run_scraper


def main(args=None):
    """Run the Acrecer scraper through the shared CLI.

    Args:
        args: Pre-parsed argparse.Namespace. When None (direct invocation
              without CLI context, e.g. from the test harness), runs a
              bounded one-page-per-type sample-only pass that writes
              nothing.
    """
    if args is None:
        args = argparse.Namespace(
            portal='accrecer',
            output='both',
            ciudad='medellin',
            sample_only=True,
            max_pages=1,
            verbose=False,
        )
    from scrape.accrecer import scrape
    exit_code = run_scraper(
        lambda: scrape(
            ciudad=args.ciudad,
            sample_only=args.sample_only,
            max_pages=args.max_pages,
            verbose=args.verbose,
        ),
        portal=args.portal,
        args=args,
    )
    return exit_code


if __name__ == '__main__':
    parser = create_parser('accrecer', 'Scrape Acrecer rental listings (Medellín)')
    sys.exit(main(parser.parse_args()))
