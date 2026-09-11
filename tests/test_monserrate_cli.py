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


def test_main_forwards_reuse_flag() -> None:
    args = argparse.Namespace(
        portal="arrendamientosmonserrate",
        output="both",
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
        reuse_unchanged_details=True,
    )

    with (
        mock.patch(
            "scripts.scrape_monserrate.scrape",
            return_value=[],
        ) as scrape_mock,
        mock.patch(
            "scripts.scrape_monserrate.run_scraper",
            side_effect=lambda scraper_fn, **_kwargs: (scraper_fn(), 0)[1],
        ),
    ):
        assert monserrate_cli.main(args=args) == 0

    scrape_mock.assert_called_once_with(
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
        reuse_unchanged_details=True,
    )
