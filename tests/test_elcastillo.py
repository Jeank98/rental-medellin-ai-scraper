"""Fixture-backed tests for the Arrendamientos El Castillo scraper."""

import argparse
import io
from pathlib import Path
from unittest import mock

import scripts.scrape_arrendamientoselcastillo as cli
from scrape.arrendamientoselcastillo import (
    _SEARCH_URLS,
    parse_detail_estrato,
    parse_search_html,
    scrape,
    scroll_to_load_all,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "elcastillo"
CANONICAL = [
    "id",
    "portal",
    "tipo",
    "precio",
    "area",
    "habitaciones",
    "banos",
    "parqueaderos",
    "estrato",
    "barrio",
    "url",
]


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_search_cards_preserve_contract_and_current_price() -> None:
    rows = parse_search_html(_load("search_page.html"))

    assert len(rows) == 3
    assert list(rows[0]) == CANONICAL
    assert rows[0] == {
        "id": "AEC-49041",
        "portal": "arrendamientoselcastillo",
        "tipo": "apartamento",
        "precio": 6200000,
        "area": 137,
        "habitaciones": 3,
        "banos": 5,
        "parqueaderos": 2,
        "estrato": 0,
        "barrio": "Laureles",
        "url": "https://www.arrendamientoselcastillo.com.co/detalle-propiedad/apartamento-enarriendo-en-laureles-49041",
    }


def test_non_residential_card_keeps_explicit_zeroes() -> None:
    rows = parse_search_html(_load("search_page.html"))
    local = next(row for row in rows if row["id"] == "AEC-48924")

    assert local["tipo"] == "local"
    assert local["habitaciones"] == 0
    assert local["banos"] == 1
    assert local["parqueaderos"] == 0


def test_detail_parser_recovers_stratum_only() -> None:
    assert parse_detail_estrato(_load("detail_49041.html")) == 5
    assert parse_detail_estrato(_load("detail_without_estrato.html")) == 0


def test_scroll_stops_only_after_no_new_ids() -> None:
    class FakeLocator:
        def __init__(self, page: "FakePage") -> None:
            self.page = page

        def inner_text(self) -> str:
            return self.page.text

    class FakePage:
        def __init__(self) -> None:
            self.texts = [
                "COD: 49041\nCOD: 48924",
                "COD: 49041\nCOD: 48924\nCOD: 17307",
                "COD: 49041\nCOD: 48924\nCOD: 17307",
            ]
            self.index = 0
            self.text = self.texts[0]
            self.scrolls = 0
            self.mouse = FakeMouse(self)

        def locator(self, _selector: str) -> FakeLocator:
            return FakeLocator(self)

        def mouse_wheel(self, _x: int, _y: int) -> None:
            self.scrolls += 1
            self.index = min(self.index + 1, len(self.texts) - 1)
            self.text = self.texts[self.index]

        def wait_for_timeout(self, _milliseconds: int) -> None:
            return None

    class FakeMouse:
        def __init__(self, page: FakePage) -> None:
            self.page = page

        def wheel(self, x: int, y: int) -> None:
            self.page.mouse_wheel(x, y)

    page = FakePage()
    scroll_to_load_all(page)

    assert page.scrolls == 2


def test_scrape_merges_detail_stratum_and_deduplicates() -> None:
    search_html = _load("search_page.html")
    detail_html = _load("detail_49041.html")
    sparse_detail = _load("detail_without_estrato.html")
    detail_map = {
        row["url"]: (detail_html if row["id"] == "AEC-49041" else sparse_detail)
        for row in parse_search_html(search_html)
        if row["tipo"] != "local"
    }

    with (
        mock.patch(
            "scrape.arrendamientoselcastillo.stealthy_fetch_with_action",
            side_effect=[search_html, "", ""],
        ) as search_fetch,
        mock.patch(
            "scrape.arrendamientoselcastillo.bulk_fetch",
            return_value=list(detail_map.items()),
        ) as detail_fetch,
    ):
        rows = scrape(sample_only=False)

    assert len(rows) == 2
    assert rows[0]["estrato"] == 5
    assert rows[1]["estrato"] == 0
    assert search_fetch.call_count == len(_SEARCH_URLS)
    detail_fetch.assert_called_once()
    assert list(rows[0]) == CANONICAL


def test_residential_sources_filter_commercial_before_detail_phase() -> None:
    search_html = _load("search_mixed.html")
    residential = parse_search_html(search_html)[:3]
    details = [(row["url"], _load("detail_49041.html")) for row in residential]

    with (
        mock.patch(
            "scrape.arrendamientoselcastillo.stealthy_fetch_with_action",
            return_value=search_html,
        ) as search_fetch,
        mock.patch(
            "scrape.arrendamientoselcastillo.bulk_fetch",
            return_value=details,
        ) as detail_fetch,
    ):
        rows = scrape(sample_only=False)

    assert {row["tipo"] for row in rows} == {
        "apartamento",
        "casa",
        "apartaestudio",
    }
    assert {row["id"] for row in rows} == {
        "AEC-49041",
        "AEC-33011",
        "AEC-17307",
    }
    assert [call.args[0] for call in search_fetch.call_args_list] == list(_SEARCH_URLS)
    detail_urls = detail_fetch.call_args.args[0]
    assert detail_urls == [row["url"] for row in residential]
    assert all("local-enarriendo" not in url for url in detail_urls)
    assert all("bodega-enarriendo" not in url for url in detail_urls)
    assert all("oficina-enarriendo" not in url for url in detail_urls)


def test_sample_cli_does_not_write_outputs() -> None:
    args = argparse.Namespace(
        portal="arrendamientoselcastillo",
        output="both",
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
    )

    with (
        mock.patch(
            "scrape.arrendamientoselcastillo.stealthy_fetch_with_action",
            return_value=_load("search_mixed.html"),
        ),
        mock.patch(
            "scrape.arrendamientoselcastillo.bulk_fetch",
            return_value=[],
        ),
        mock.patch("scrape.cli.write_to_csv") as csv_writer,
        mock.patch("scrape.cli.write_to_db") as db_writer,
        mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
    ):
        assert cli.main(args) == 0

    csv_writer.assert_not_called()
    db_writer.assert_not_called()
    assert "Sample: 3 listing(s) extracted" in stdout.getvalue()
    assert "AEC-49041" in stdout.getvalue()
    assert "AEC-33011" in stdout.getvalue()
    assert "AEC-17307" in stdout.getvalue()
