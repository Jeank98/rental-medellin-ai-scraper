"""CLI regression coverage for Alnago detail reuse."""

import argparse
from unittest import mock

import scripts.scrape_alnago as alnago_cli


def test_cli_forwards_reuse_flag() -> None:
    args = argparse.Namespace(
        portal="alnago",
        output="both",
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
        reuse_unchanged_details=True,
    )

    with (
        mock.patch("scripts.scrape_alnago.scrape", return_value=[]) as scrape_mock,
        mock.patch(
            "scripts.scrape_alnago.run_scraper",
            side_effect=lambda scraper_fn, **_kwargs: (scraper_fn(), 0)[1],
        ),
    ):
        assert alnago_cli.main(args=args) == 0

    scrape_mock.assert_called_once_with(
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
        reuse_unchanged_details=True,
    )
