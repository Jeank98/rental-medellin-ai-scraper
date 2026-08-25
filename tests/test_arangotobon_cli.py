"""CLI and registry tests for Arango Tobon."""

import argparse
import io
from unittest import mock

import scripts.scrape_arangotobon as arangotobon_cli
from scrape.arangotobon import parse_search_page
from scrape.orchestrator import PORTALS
from tests.test_arangotobon import _load


def test_arangotobon_is_registered_with_shared_orchestrator() -> None:
    assert PORTALS["arangotobon"] == {"module": "arangotobon"}


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
