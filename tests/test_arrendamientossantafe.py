"""Regression coverage for SantaFe's JSON API and Phase-B detail reuse."""

import argparse
import json
from unittest import mock

import scripts.scrape_asf as asf_cli
from scrape.arrendamientossantafe import scrape

DETAIL_BASE = "https://arrendamientossantafe.com/apisf/property/"


def _wrap(payload: dict) -> str:
    """The endpoints wrap their JSON in an <html><body> prefix."""
    return "<html><body>" + json.dumps(payload) + "</body></html>"


def _result(code: str, price: int) -> dict:
    return {
        "codigo": code,
        "title": f"Apartamento en Laureles {code}",
        "price_raw": price,
        "location": "Laureles",
        "ciudad": "Medellín",
        "type": "Apartamento",
        "size": "55 M²",
        "bedrooms": 2,
        "bathrooms": 1,
        "url": f"/propiedad/{code}",
    }


def _detail(code: str, banos: int, estrato: int, price: int) -> dict:
    return {
        "codigo": code,
        "area": 55,
        "habitaciones": 2,
        "banos": banos,
        "parqueaderos": 1,
        "estrato": estrato,
        "sector": "Laureles",
        "price_raw": price,
    }


def _run_scrape(*, reuse: bool, previous: dict | None = None, cache_error: Exception | None = None):
    detail_urls = {code: f"{DETAIL_BASE}{code}" for code in ("A1", "A2", "A3")}
    search_payload = _wrap(
        {
            "results": [
                _result("A1", 1_500_000),
                _result("A2", 1_600_000),
                _result("A3", 1_700_000),
            ],
            "total": 3,
            "page": 1,
            "per_page": 12,
            "has_more": False,
        }
    )
    details = {
        detail_urls["A1"]: _wrap(_detail("A1", 1, 3, 1_500_000)),
        detail_urls["A2"]: _wrap(_detail("A2", 2, 4, 1_600_000)),
        detail_urls["A3"]: _wrap(_detail("A3", 3, 5, 1_700_000)),
    }

    def bulk_fetch(urls: list[str], max_workers: int | None = None):
        return [(url, details[url]) for url in urls]

    snapshot = (
        mock.patch("db.get_active_listings_by_id", side_effect=cache_error)
        if cache_error
        else mock.patch("db.get_active_listings_by_id", return_value=previous or {})
    )
    with (
        mock.patch("scrape.arrendamientossantafe.fetch_page", return_value=search_payload),
        mock.patch(
            "scrape.arrendamientossantafe.bulk_fetch",
            side_effect=bulk_fetch,
        ) as bulk_fetch_mock,
        snapshot as snapshot_mock,
    ):
        rows = scrape(max_pages=1, reuse_unchanged_details=reuse)

    return rows, bulk_fetch_mock, snapshot_mock, detail_urls


def test_list_records_map_to_the_eleven_columns() -> None:
    rows, _bulk, _snapshot, _urls = _run_scrape(reuse=False)

    assert [row["id"] for row in rows] == ["ASF-A1", "ASF-A2", "ASF-A3"]
    assert rows[0]["portal"] == "arrendamientossantafe"
    assert rows[0]["tipo"] == "apartamento"
    assert rows[0]["area"] == 55
    assert rows[0]["barrio"] == "Laureles"
    assert rows[0]["url"] == "https://arrendamientossantafe.com/propiedad/A1"


def test_reuses_unchanged_cards_and_fetches_only_new_or_changed_details(capsys) -> None:
    previous = {
        "ASF-A1": {
            "id": "ASF-A1",
            "precio": 1_500_000,
            "area": 999,
            "banos": 7,
            "parqueaderos": 2,
            "estrato": 6,
        },
        "ASF-A2": {"id": "ASF-A2", "precio": 1_500_000, "banos": 9, "estrato": 9},
    }

    rows, bulk_fetch_mock, snapshot_mock, detail_urls = _run_scrape(
        reuse=True,
        previous=previous,
    )

    assert "ASF detail reuse: 1 reused; 2 detail pages fetched" in capsys.readouterr().out

    snapshot_mock.assert_called_once_with("arrendamientossantafe", "medellin")
    assert bulk_fetch_mock.call_args_list[0].args[0] == [
        detail_urls["A2"],
        detail_urls["A3"],
    ]
    by_id = {row["id"]: row for row in rows}
    assert by_id["ASF-A1"]["area"] == 55
    assert by_id["ASF-A1"]["banos"] == 7
    assert by_id["ASF-A1"]["parqueaderos"] == 2
    assert by_id["ASF-A1"]["estrato"] == 6
    assert by_id["ASF-A2"]["banos"] == 2
    assert by_id["ASF-A2"]["estrato"] == 4
    assert by_id["ASF-A3"]["banos"] == 3
    assert by_id["ASF-A3"]["estrato"] == 5


def test_disabled_reuse_keeps_the_existing_full_detail_path() -> None:
    rows, bulk_fetch_mock, snapshot_mock, detail_urls = _run_scrape(
        reuse=False,
        previous={"ASF-A1": {"precio": 1_500_000, "banos": 7, "estrato": 6}},
    )

    snapshot_mock.assert_not_called()
    assert bulk_fetch_mock.call_args_list[0].args[0] == list(detail_urls.values())
    assert [(row["banos"], row["estrato"]) for row in rows] == [(1, 3), (2, 4), (3, 5)]


def test_cache_failure_falls_back_to_full_detail_fetch() -> None:
    rows, bulk_fetch_mock, snapshot_mock, detail_urls = _run_scrape(
        reuse=True,
        cache_error=RuntimeError("database unavailable"),
    )

    snapshot_mock.assert_called_once_with("arrendamientossantafe", "medellin")
    assert bulk_fetch_mock.call_args_list[0].args[0] == list(detail_urls.values())
    assert [(row["banos"], row["estrato"]) for row in rows] == [(1, 3), (2, 4), (3, 5)]


def test_cli_forwards_reuse_flag_to_santafe_scraper() -> None:
    args = argparse.Namespace(
        portal="arrendamientossantafe",
        output="both",
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
        reuse_unchanged_details=True,
    )
    row = {
        "id": "ASF-1",
        "portal": "arrendamientossantafe",
        "tipo": "apartamento",
        "precio": 1_500_000,
        "area": 55,
        "habitaciones": 2,
        "banos": 1,
        "parqueaderos": 1,
        "estrato": 4,
        "barrio": "Laureles",
        "url": "https://example.test/ASF-1",
    }

    with (
        mock.patch("scripts.scrape_asf.scrape", return_value=[row]) as scrape_mock,
        mock.patch(
            "scripts.scrape_asf.run_scraper",
            side_effect=lambda scraper_fn, **_kwargs: (scraper_fn(), 0)[1],
        ),
    ):
        assert asf_cli.main(args) == 0

    scrape_mock.assert_called_once_with(
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
        reuse_unchanged_details=True,
    )
