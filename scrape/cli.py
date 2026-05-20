"""
Shared CLI factory for all portal scraper entry points.
Provides argparse boilerplate and the run_scraper dispatcher.
"""

import argparse
import sys
import textwrap

from scrape.csv_writer import write_to_csv
from scrape.db_writer import write_to_db
from scrape.validator import validate


def create_parser(portal: str, description: str) -> argparse.ArgumentParser:
    """Create a pre-configured ArgumentParser for a portal scraper."""
    parser = argparse.ArgumentParser(
        prog=f"scrape_{portal}",
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--output',
        choices=['csv', 'db', 'both'],
        default='both',
        help='Where to save results (default: both)',
    )
    parser.add_argument(
        '--ciudad',
        default='medellin',
        help='City filter (default: medellin)',
    )
    parser.add_argument(
        '--sample-only',
        action='store_true',
        help='Validate 1-3 pages, print summary, exit without writing',
    )
    parser.add_argument(
        '--max-pages',
        type=int,
        default=None,
        metavar='N',
        help='Limit pages for testing',
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Detailed extraction logging',
    )
    return parser


def run_scraper(scraper_fn, args: argparse.Namespace) -> int:
    """Run a scraper and handle output based on CLI args.

    Args:
        scraper_fn: Callable that returns a list of listing dicts.
        args: Parsed argparse Namespace with --output, --ciudad,
              --sample-only, --max-pages, --verbose.
    """
    portal = scraper_fn.__name__ if hasattr(scraper_fn, '__name__') else 'unknown'

    rows = scraper_fn()

    # SAMPLE-FIRST: if scraper returns 0 rows, exit with error
    if len(rows) == 0:
        print(f"Error: 0 listings scraped from {portal}. Check the URL or network.", file=sys.stderr)
        sys.exit(2)

    # Anomaly detection
    anomaly_count = 0
    for row in rows:
        warnings = validate(row)
        if warnings:
            anomaly_count += len(warnings)
            for w in warnings:
                print(f"  [ANOMALY] {row.get('id', '?')} — {w}", file=sys.stderr)

    if anomaly_count > 0:
        print(f"\n{anomaly_count} anomaly(s) detected across {len(rows)} listings.", file=sys.stderr)
        print()

    # --sample-only: print summary, don't write
    if args.sample_only:
        print(f"Sample: {len(rows)} listing(s) extracted")
        if rows:
            print()
            print("Sample listing(s):")
            for row in rows[:3]:
                print(textwrap.indent(
                    '\n'.join(f"  {k}: {v}" for k, v in row.items()),
                    '  ',
                ))
                print()
        return 0

    # Write outputs
    if args.output in ('csv', 'both'):
        write_to_csv(rows, portal, args.ciudad)

    if args.output in ('db', 'both'):
        write_to_db(rows, portal, args.ciudad)

    print(f"Scraped {len(rows)} listings from {portal}")

    return 0
