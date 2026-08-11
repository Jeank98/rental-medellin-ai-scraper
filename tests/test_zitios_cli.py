"""CLI integration tests for the Zitios wrapper."""

import argparse
import io
from pathlib import Path
from unittest import mock

import scripts.scrape_zitios

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "zitios"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_sample_only_uses_fixture_scraper_without_writers() -> None:
    args = argparse.Namespace(
        portal="zitios",
        output="both",
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
    )
    search_url = "https://zitios.com.co/inmuebles/g/arriendo/c/medell%C3%ADn/"
    detail_urls = [
        "https://zitios.com.co/inmueble/arriendo-apartamento-robledo-pajarito_10188009",
        "https://zitios.com.co/inmueble/arriendo-apartaestudio-en-calasanz_10125019",
    ]

    def fetch(url: str) -> str:
        if url == search_url:
            return _load("search_page_1.html")
        return ""

    detail_html = {
        detail_urls[0]: _load("detail_10188009.html"),
        detail_urls[1]: _load("detail_10125019.html"),
    }

    with mock.patch("scrape.zitios.fetch_page", side_effect=fetch), mock.patch(
        "scrape.zitios.bulk_fetch",
        side_effect=lambda urls: [(url, detail_html[url]) for url in urls],
    ), mock.patch("scrape.cli.write_to_csv") as csv_writer, mock.patch(
        "scrape.cli.write_to_db"
    ) as db_writer, mock.patch("sys.stdout", new_callable=io.StringIO) as output:
        assert scripts.scrape_zitios.main(args=args) == 0

    csv_writer.assert_not_called()
    db_writer.assert_not_called()
    assert "Sample: 2 listing(s) extracted" in output.getvalue()
