"""CLI and registry tests for Arango Tobon."""

import argparse
import io
from unittest import mock

import scripts.scrape_arangotobon as arangotobon_cli
from scrape.arangotobon import parse_search_page
from tests.test_arangotobon import _load


def test_sample_only_does_not_write_outputs() -> None:
    args = argparse.Namespace(
        portal="arangotobon",
        output="both",
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
    )
    rows = parse_search_page(_load("search_page.html"))
    details = {
        row["url"]: _load(
            {
                "ATB-3440": "detail_3440.html",
                "ATB-4517": "detail_4517.html",
                "ATB-4571": "detail_4571.html",
                "ATB-4466": "detail_4466_parking.html",
            }[row["id"]]
        )
        for row in rows
    }
    with mock.patch(
        "scrape.arangotobon.fetch_page", return_value=_load("search_page.html")
    ), mock.patch(
        "scrape.arangotobon.bulk_fetch", return_value=list(details.items())
    ), mock.patch("scrape.cli.write_to_csv") as csv, mock.patch(
        "scrape.cli.write_to_db"
    ) as db, mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
        result = arangotobon_cli.main(args=args)

    assert result == 0
    csv.assert_not_called()
    db.assert_not_called()
    assert "Sample: 4 listing(s) extracted" in stdout.getvalue()


def test_cli_forwards_reuse_flag() -> None:
    args = argparse.Namespace(
        portal="arangotobon",
        output="both",
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
        reuse_unchanged_details=True,
    )

    with (
        mock.patch(
            "scripts.scrape_arangotobon.scrape", return_value=[]
        ) as scrape_mock,
        mock.patch(
            "scripts.scrape_arangotobon.run_scraper",
            side_effect=lambda scraper_fn, **_kwargs: (scraper_fn(), 0)[1],
        ),
    ):
        assert arangotobon_cli.main(args=args) == 0

    scrape_mock.assert_called_once_with(
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
        reuse_unchanged_details=True,
    )
