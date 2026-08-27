"""CLI regression tests for Monserrate's failure status propagation."""

import argparse
from unittest import mock

import scripts.scrape_monserrate as monserrate_cli


def test_main_returns_shared_cli_failure_status() -> None:
    args = argparse.Namespace(
        portal="arrendamientosmonserrate",
        output="db",
        ciudad="medellin",
        sample_only=False,
        max_pages=1,
        verbose=False,
    )

    with mock.patch.object(monserrate_cli, "run_scraper", return_value=1):
        assert monserrate_cli.main(args=args) == 1
