"""Regression test for safe DB failure propagation from scraper CLIs."""

import argparse
import unittest
from unittest import mock

from scrape.cli import run_scraper


class TestCLIDBFailure(unittest.TestCase):
    """A failed DB replacement must reach the orchestrator as a failure."""

    def test_db_write_failure_returns_nonzero_without_claiming_success(self) -> None:
        args = argparse.Namespace(
            portal="example",
            output="db",
            ciudad="medellin",
            sample_only=False,
            max_pages=None,
            verbose=False,
        )
        rows = [{"id": "EX-1", "portal": "example"}]

        with mock.patch("scrape.cli.write_to_db", return_value=0):
            self.assertEqual(run_scraper(lambda: rows, portal="example", args=args), 1)
