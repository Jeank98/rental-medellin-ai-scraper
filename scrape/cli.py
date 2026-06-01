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
    """Create a pre-configured ArgumentParser for a portal scraper.

    Args:
        portal: Default portal name (used as program name and as default
                for the --portal CLI arg).
        description: Human-readable description shown in --help.
    """
    parser = argparse.ArgumentParser(
        prog=f"scrape_{portal}",
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--portal',
        default=portal,
        help=f'Portal name used in CSV/DB output paths (default: {portal})',
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


def run_scraper(scraper_fn, portal: str = None, args: argparse.Namespace = None) -> int:
    """Run a scraper and handle output based on CLI args.

    Args:
        scraper_fn: Callable that returns a list of listing dicts.
        portal: Portal name. Used for CSV/DB output paths and deactivate_listings
                calls. May be overridden by `args.portal` if the user passed
                `--portal` on the CLI. If not provided, falls back to
                `scraper_fn.__name__` (backward compatibility for old scripts
                that pass `lambda: scrape(...)` — the lambda's __name__ is
                '<lambda>', so this is brittle; new scripts should pass an
                explicit portal name).
        args: Parsed argparse Namespace with --portal, --output, --ciudad,
              --sample-only, --max-pages, --verbose.
    """
    if portal is None:
        portal = scraper_fn.__name__ if hasattr(scraper_fn, '__name__') else 'unknown'
    portal = getattr(args, 'portal', None) or portal

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


if __name__ == '__main__':
    # When this file is run as a script, its __name__ is '__main__' and
    # the function globals live in sys.modules['__main__']. When imported
    # as 'scrape.cli', this block is skipped — so the tests only run in
    # the script path. We monkey-patch via sys.modules[__name__] for that
    # case; sys.modules['scrape.cli'] may not exist when run directly.
    this_module = sys.modules[__name__]

    # 1. create_parser accepts portal and adds --portal arg with that default
    parser = create_parser('adn', 'Test scraper')
    assert parser.prog == 'scrape_adn', f"expected prog='scrape_adn', got {parser.prog!r}"
    ns = parser.parse_args(['--ciudad', 'bogota'])
    assert ns.portal == 'adn', f"expected portal default 'adn', got {ns.portal!r}"
    assert ns.ciudad == 'bogota', f"expected ciudad 'bogota', got {ns.ciudad!r}"
    assert ns.output == 'both', f"expected output default 'both', got {ns.output!r}"
    assert ns.sample_only is False
    assert ns.max_pages is None
    assert ns.verbose is False

    # 2. --portal overrides default
    ns2 = parser.parse_args(['--portal', 'custom_portal'])
    assert ns2.portal == 'custom_portal', f"expected --portal override, got {ns2.portal!r}"

    # 3. run_scraper uses explicit portal param, NOT scraper_fn.__name__ (which is '<lambda>')
    fake_rows = [{'id': 'X-1', 'portal': 'X', 'tipo': 'apartamento', 'precio': 1000,
                  'area': 50, 'habitaciones': 2, 'banos': 1, 'parqueaderos': 0,
                  'estrato': 3, 'barrio': 'Test', 'url': 'http://example.com/x'}]

    captured = {}

    def fake_csv(rows, portal, ciudad):
        captured['csv_portal'] = portal

    def fake_db(rows, portal, ciudad):
        captured['db_portal'] = portal

    def fake_validate(row):
        return []

    orig_csv = this_module.write_to_csv
    orig_db = this_module.write_to_db
    orig_val = this_module.validate
    this_module.write_to_csv = fake_csv
    this_module.write_to_db = fake_db
    this_module.validate = fake_validate
    try:
        scraper_lambda = lambda: fake_rows
        assert scraper_lambda.__name__ == '<lambda>', "test premise: lambda name should be '<lambda>'"

        args_ns = argparse.Namespace(
            portal='real_portal_name',
            output='both',
            ciudad='medellin',
            sample_only=False,
            max_pages=None,
            verbose=False,
        )
        rc = run_scraper(scraper_lambda, 'fallback_name', args_ns)
        assert rc == 0
        assert captured.get('csv_portal') == 'real_portal_name', (
            f"CSV should use args.portal, got {captured.get('csv_portal')!r}"
        )
        assert captured.get('db_portal') == 'real_portal_name', (
            f"DB should use args.portal, got {captured.get('db_portal')!r}"
        )
        assert captured.get('csv_portal') != '<lambda>', "must NOT use scraper_fn.__name__"
    finally:
        this_module.write_to_csv = orig_csv
        this_module.write_to_db = orig_db
        this_module.validate = orig_val

    # 4. run_scraper falls back to portal kwarg when args.portal missing (backward compat)
    captured2 = {}

    def fake_csv2(rows, portal, ciudad):
        captured2['csv_portal'] = portal

    def fake_db2(rows, portal, ciudad):
        captured2['db_portal'] = portal

    this_module.write_to_csv = fake_csv2
    this_module.write_to_db = fake_db2
    this_module.validate = fake_validate
    try:
        args_ns_old = argparse.Namespace(
            output='csv',
            ciudad='medellin',
            sample_only=False,
            max_pages=None,
            verbose=False,
        )
        rc = run_scraper(lambda: fake_rows, 'kwarg_portal', args_ns_old)
        assert rc == 0
        assert captured2.get('csv_portal') == 'kwarg_portal', (
            f"portal kwarg should win when args.portal missing, got {captured2.get('csv_portal')!r}"
        )
    finally:
        this_module.write_to_csv = orig_csv
        this_module.write_to_db = orig_db
        this_module.validate = orig_val

    # 4b. backward compat: old script calls run_scraper(scraper_fn=fn, args=ns) — no portal kwarg.
    # portal defaults to None and falls back to scraper_fn.__name__ ('<lambda>').
    captured2b = {}

    def fake_csv2b(rows, portal, ciudad):
        captured2b['csv_portal'] = portal

    this_module.write_to_csv = fake_csv2b
    this_module.write_to_db = fake_db2
    this_module.validate = fake_validate
    try:
        args_ns_legacy = argparse.Namespace(
            output='csv',
            ciudad='medellin',
            sample_only=False,
            max_pages=None,
            verbose=False,
        )
        rc = run_scraper(scraper_fn=lambda: fake_rows, args=args_ns_legacy)
        assert rc == 0
        assert captured2b.get('csv_portal') == '<lambda>', (
            f"legacy 2-kwarg call should fall back to scraper_fn.__name__, "
            f"got {captured2b.get('csv_portal')!r}"
        )
    finally:
        this_module.write_to_csv = orig_csv
        this_module.write_to_db = orig_db
        this_module.validate = orig_val

    # 5. sample-only returns 0 and does NOT call writers
    captured3 = {'called': False}

    def fake_csv3(rows, portal, ciudad):
        captured3['called'] = True

    this_module.write_to_csv = fake_csv3
    this_module.validate = fake_validate
    try:
        args_ns_sample = argparse.Namespace(
            portal='sample_portal',
            output='both',
            ciudad='medellin',
            sample_only=True,
            max_pages=None,
            verbose=False,
        )
        rc = run_scraper(lambda: fake_rows, 'sample_portal', args_ns_sample)
        assert rc == 0
        assert captured3['called'] is False, "sample-only must skip CSV write"
    finally:
        this_module.write_to_csv = orig_csv
        this_module.validate = orig_val

    print("All cli.py assertions passed.")
