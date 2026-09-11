"""Regression coverage for SantaFe Phase-B detail reuse."""

import argparse
from unittest import mock

import scripts.scrape_asf as asf_cli
from scrape.arrendamientossantafe import scrape


def _search_card(code: str, price: str) -> str:
    return f"""
    <article class="property-card">
      <span class="id">REF: {code}</span>
      <p class="tipo-inmueble">Tipo: Apartamento</p>
      <div class="precio"><p>${price}</p></div>
      <span class="area">55m²</span>
      <span class="alcobas">2</span>
      <span class="garaje">1</span>
      <div class="sector"><p class="d-inline">Ubicación: Laureles</p></div>
      <div class="inner-card"><a href="/propiedades/{code}">Detail</a></div>
    </article>
    """


def _run_scrape(*, reuse: bool, previous: dict | None = None, cache_error: Exception | None = None):
    search_url = "https://arrendamientossantafe.com/propiedades/?page=1&bussines_type=Arrendar"
    detail_urls = {
        "ASF-A1": "https://arrendamientossantafe.com/propiedades/A1",
        "ASF-A2": "https://arrendamientossantafe.com/propiedades/A2",
        "ASF-A3": "https://arrendamientossantafe.com/propiedades/A3",
    }
    search_html = "<li class='current'>1</li>" + "".join(
        [
            _search_card("A1", "1,500,000"),
            _search_card("A2", "1,600,000"),
            _search_card("A3", "1,700,000"),
        ]
    )
    details = {
        detail_urls["ASF-A1"]: "<div>Baños: 1 Estrato: 3</div>",
        detail_urls["ASF-A2"]: "<div>Baños: 2 Estrato: 4</div>",
        detail_urls["ASF-A3"]: "<div>Baños: 3 Estrato: 5</div>",
    }

    def bulk_fetch(urls: list[str]) -> list[tuple[str, str]]:
        if urls == [search_url]:
            return [(search_url, search_html)]
        return [(url, details[url]) for url in urls]

    snapshot = (
        mock.patch("db.get_active_listings_by_id", side_effect=cache_error)
        if cache_error
        else mock.patch("db.get_active_listings_by_id", return_value=previous or {})
    )
    with (
        mock.patch("scrape.arrendamientossantafe.fetch_page", return_value=search_html),
        mock.patch(
            "scrape.arrendamientossantafe.bulk_fetch",
            side_effect=bulk_fetch,
        ) as bulk_fetch_mock,
        snapshot as snapshot_mock,
    ):
        rows = scrape(max_pages=1, reuse_unchanged_details=reuse)

    return rows, bulk_fetch_mock, snapshot_mock, detail_urls


def test_reuses_unchanged_cards_and_fetches_only_new_or_changed_details(capsys) -> None:
    previous = {
        "ASF-A1": {
            "id": "ASF-A1",
            "precio": 1_500_000,
            "area": 999,
            "banos": 7,
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
    assert bulk_fetch_mock.call_args_list[1].args[0] == [
        detail_urls["ASF-A2"],
        detail_urls["ASF-A3"],
    ]
    by_id = {row["id"]: row for row in rows}
    assert by_id["ASF-A1"]["area"] == 55
    assert by_id["ASF-A1"]["banos"] == 7
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
    assert bulk_fetch_mock.call_args_list[1].args[0] == list(detail_urls.values())
    assert [(row["banos"], row["estrato"]) for row in rows] == [(1, 3), (2, 4), (3, 5)]


def test_cache_failure_falls_back_to_full_detail_fetch() -> None:
    rows, bulk_fetch_mock, snapshot_mock, detail_urls = _run_scrape(
        reuse=True,
        cache_error=RuntimeError("database unavailable"),
    )

    snapshot_mock.assert_called_once_with("arrendamientossantafe", "medellin")
    assert bulk_fetch_mock.call_args_list[1].args[0] == list(detail_urls.values())
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
