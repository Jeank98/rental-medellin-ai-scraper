"""Regression coverage for Santillana Phase-B detail reuse."""

import argparse
from unittest import mock

import scripts.scrape_santillana as santillana_cli
from scrape.santillana import scrape


def _listing(listing_id: str, price: int) -> dict:
    return {
        "id": listing_id,
        "portal": "santillana",
        "tipo": "apartamento",
        "precio": price,
        "area": 0,
        "habitaciones": 0,
        "banos": 0,
        "parqueaderos": 0,
        "estrato": 0,
        "barrio": "",
        "url": f"https://santillanasas.com/inmueble/{listing_id.removeprefix('STL-')}",
    }


def _run_scrape(*, reuse: bool, previous: dict | None = None):
    listings = [
        _listing("STL-1", 1_500_000),
        _listing("STL-2", 1_600_000),
        _listing("STL-3", 1_700_000),
    ]
    fields_by_url = {
        listings[0]["url"]: {"area": 40, "banos": 1, "estrato": 3, "barrio": "Belén"},
        listings[1]["url"]: {
            "area": 50,
            "banos": 2,
            "estrato": 4,
            "barrio": "Laureles",
        },
        listings[2]["url"]: {
            "area": 60,
            "banos": 3,
            "estrato": 5,
            "barrio": "Envigado",
        },
    }

    with (
        mock.patch("scrape.santillana._fetch_all_pages", return_value=listings),
        mock.patch(
            "db.get_active_listings_by_id", return_value=previous or {}
        ) as snapshot,
        mock.patch(
            "scrape.santillana.bulk_fetch",
            side_effect=lambda urls: [(url, url) for url in urls],
        ) as detail_fetch,
        mock.patch(
            "scrape.santillana._parse_detail",
            side_effect=lambda url: fields_by_url[url],
        ),
    ):
        rows = scrape(reuse_unchanged_details=reuse)

    return rows, snapshot, detail_fetch, listings


def test_reuses_unchanged_santillana_details_and_fetches_only_misses(capsys) -> None:
    previous = {
        "STL-1": {
            **_listing("STL-1", 1_500_000),
            "area": 999,
            "habitaciones": 2,
            "banos": 7,
            "parqueaderos": 1,
            "estrato": 6,
            "barrio": "Anterior",
        },
        "STL-2": {**_listing("STL-2", 1_500_000), "banos": 9},
    }

    rows, snapshot, detail_fetch, listings = _run_scrape(reuse=True, previous=previous)

    snapshot.assert_called_once_with("santillana", "medellin")
    assert detail_fetch.call_args.args[0] == [listings[1]["url"], listings[2]["url"]]
    assert (
        "STL detail reuse: 1 reused; 2 detail pages fetched" in capsys.readouterr().out
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id["STL-1"]["area"] == 999
    assert by_id["STL-1"]["banos"] == 7
    assert by_id["STL-1"]["estrato"] == 6
    assert by_id["STL-1"]["barrio"] == "Anterior"
    assert by_id["STL-2"]["area"] == 50
    assert by_id["STL-2"]["banos"] == 2
    assert by_id["STL-3"]["estrato"] == 5


def test_disabled_reuse_keeps_full_santillana_detail_path() -> None:
    rows, snapshot, detail_fetch, listings = _run_scrape(
        reuse=False,
        previous={"STL-1": {**_listing("STL-1", 1_500_000), "banos": 7}},
    )

    snapshot.assert_not_called()
    assert detail_fetch.call_args.args[0] == [row["url"] for row in listings]
    assert [row["banos"] for row in rows] == [1, 2, 3]


def test_cli_forwards_reuse_flag_to_santillana_scraper() -> None:
    args = argparse.Namespace(
        portal="santillana",
        output="both",
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
        reuse_unchanged_details=True,
    )
    row = _listing("STL-1", 1_500_000)

    with (
        mock.patch(
            "scripts.scrape_santillana.scrape", return_value=[row]
        ) as scrape_mock,
        mock.patch(
            "scripts.scrape_santillana.run_scraper",
            side_effect=lambda scraper_fn, **_kwargs: (scraper_fn(), 0)[1],
        ),
    ):
        assert santillana_cli.main(args) == 0

    scrape_mock.assert_called_once_with(
        ciudad="medellin",
        sample_only=True,
        max_pages=1,
        verbose=False,
        reuse_unchanged_details=True,
    )
