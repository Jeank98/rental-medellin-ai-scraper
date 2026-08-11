"""CLI integration tests for Acrecer.

These tests verify the CLI wrapper's sample-only no-write behavior
and zero-row failure path. The sample-only test runs the REAL
scraper (scrape.accrecer.scrape) through the wrapper, patching only
scrape.accrecer.fetch_page with a frozen RSC fixture page, plus the
output writers. The zero-row test exercises run_scraper's exit path.
"""

import argparse
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

# This import FAILS until scripts/scrape_accrecer.py is created.
import scripts.scrape_accrecer  # noqa: F401 — will raise ModuleNotFoundError


class TestSampleOnlyNoWrite(unittest.TestCase):
    """Given --sample-only, when scraper runs, then no writers are called."""

    FIXTURES = Path(__file__).resolve().parent / "fixtures" / "accrecer"

    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = {
            "portal": "accrecer",
            "output": "both",
            "ciudad": "medellin",
            "sample_only": True,
            "max_pages": 1,
            "verbose": False,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def _load_fixture(self, name: str) -> str:
        with open(self.FIXTURES / name, encoding="utf-8") as fh:
            return fh.read()

    def test_sample_only_prints_sample_line(self):
        """Given a fixture-backed REAL scraper in sample-only mode, when run,
        then it prints 'Sample: N listing(s) extracted' and writes nothing."""
        args = self._make_args()
        fixture_html = self._load_fixture("cli_sample_page.html")

        with unittest.mock.patch(
            "scrape.accrecer.fetch_page", return_value=fixture_html
        ), unittest.mock.patch("scrape.cli.write_to_csv") as mock_csv, \
             unittest.mock.patch("scrape.cli.write_to_db") as mock_db, \
             unittest.mock.patch("scrape.cli.validate", return_value=[]), \
             unittest.mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            scripts.scrape_accrecer.main(args=args)

        mock_csv.assert_not_called()
        mock_db.assert_not_called()
        # Fixture yields 1 listing per property type (Apartamento + Casa),
        # so the real scraper reports 2 listings extracted.
        self.assertIn(
            "Sample: 2 listing(s) extracted", mock_stdout.getvalue(),
            "Sample line must report the extracted listing count",
        )


class TestZeroRowExit(unittest.TestCase):
    """Given a scraper that returns 0 rows, when run, then SystemExit(2) is raised."""

    def test_zero_rows_exits_with_code_2(self):
        """Given zero listings, when run_scraper is invoked, then SystemExit(2)."""
        args = argparse.Namespace(
            portal="accrecer", output="csv", ciudad="medellin",
            sample_only=False, max_pages=None, verbose=False,
        )
        from scrape.cli import run_scraper

        with self.assertRaises(SystemExit) as ctx:
            run_scraper(lambda: [], "accrecer", args)

        self.assertEqual(ctx.exception.code, 2,
                         "Zero rows must exit with code 2")


if __name__ == "__main__":
    unittest.main()
