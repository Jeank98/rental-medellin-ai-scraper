"""Fixture-backed tests for the Arango Tobon two-phase scraper."""

from pathlib import Path
from unittest import mock

from scrape.arangotobon import (
    COLUMNS,
    PREFIX,
    build_page_url,
    merge_detail,
    parse_detail_page,
    parse_search_page,
    scrape,
    UnsupportedCityError,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "arangotobon"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_build_page_url_uses_canonical_root_and_route_pages() -> None:
    assert build_page_url(1) == (
        "https://www.arangotobon.com/inmuebles/Arriendo/"
        "clases_Apartamento_Apto-Loft_Apartaestudio_Casa/"
        "municipios_Medell%C3%ADn/"
    )
    assert build_page_url(4).endswith("municipios_Medell%C3%ADn/4")


def test_build_page_url_rejects_unconfirmed_city() -> None:
    try:
        build_page_url(1, "bogota")
    except UnsupportedCityError:
        pass
    else:
        raise AssertionError("Expected unsupported city to be rejected")


def test_search_parser_maps_all_residential_classes_and_deduplicates_anchors() -> None:
    rows = parse_search_page(_load("search_page.html"))

    assert [row["id"] for row in rows] == [
        f"{PREFIX}-3440",
        f"{PREFIX}-4517",
        f"{PREFIX}-4571",
        f"{PREFIX}-4466",
    ]
    assert [row["tipo"] for row in rows] == [
        "apartaestudio",
        "apartamento",
        "apartaestudio",
        "casa",
    ]
    assert [row["precio"] for row in rows] == [1400000, 1900000, 2750000, 3500000]
    assert [row["area"] for row in rows] == [35, 40, 22, 120]
    assert [row["habitaciones"] for row in rows] == [1, 2, 1, 3]
    assert [row["banos"] for row in rows] == [1, 1, 1, 3]
    assert all(row["parqueaderos"] == 0 for row in rows)
    assert all(list(row) == COLUMNS for row in rows)
    assert len({row["url"] for row in rows}) == len(rows)


def test_detail_parser_adds_structured_fields_and_only_structured_parking() -> None:
    detail = parse_detail_page(_load("detail_3440.html"))
    assert detail == {
        "codigo": "3440",
        "tipo": "apartaestudio",
        "precio": 1400000,
        "area": 35,
        "habitaciones": 1,
        "banos": 1,
        "parqueaderos": 0,
        "estrato": 4,
        "barrio": "Laureles",
    }

    loft = parse_detail_page(_load("detail_4571.html"))
    assert loft["tipo"] == "apartaestudio"
    assert loft["estrato"] == 4
    assert loft["barrio"] == "Belen Fatima"

    parking = parse_detail_page(_load("detail_4466_parking.html"))
    assert parking["parqueaderos"] == 2


def test_dual_prices_keep_only_rental_side_within_postgres_integer_range() -> None:
    search_rows = parse_search_page(_load("search_page_dual_prices.html"))
    expected_prices = {
        "ATB-4553": 3000000,
        "ATB-4120": 4000000,
        "ATB-4038": 4100000,
        "ATB-4467": 15000000,
    }

    assert {row["id"]: row["precio"] for row in search_rows} == expected_prices
    assert all(0 <= row["precio"] <= 2_147_483_647 for row in search_rows)

    detail_files = {
        "ATB-4553": "detail_4553_dual.html",
        "ATB-4120": "detail_4120_dual.html",
        "ATB-4038": "detail_4038_dual.html",
        "ATB-4467": "detail_4467_dual.html",
    }
    detail_prices = {
        listing_id: parse_detail_page(_load(filename))["precio"]
        for listing_id, filename in detail_files.items()
    }

    assert detail_prices == expected_prices
    assert all(0 <= price <= 2_147_483_647 for price in detail_prices.values())


def test_merge_detail_rejects_code_mismatch_without_changing_identity() -> None:
    row = parse_search_page(_load("search_page.html"))[0]
    detail = parse_detail_page(_load("detail_4517.html"))

    assert merge_detail(row, detail) is False
    assert row["id"] == "ATB-3440"
    assert row["estrato"] == 0


def test_scrape_deduplicates_stale_pages_fetches_details_and_merges() -> None:
    search = _load("search_page.html")
    parsed = parse_search_page(search)
    detail_names = {
        "3440": "detail_3440.html",
        "4517": "detail_4517.html",
        "4571": "detail_4571.html",
        "4466": "detail_4466_parking.html",
    }
    detail_map = {
        row["url"]: _load(detail_names[row["id"].split("-", 1)[1]])
        for row in parsed
    }

    with mock.patch(
        "scrape.arangotobon.fetch_page", side_effect=[search, search]
    ) as pages, mock.patch(
        "scrape.arangotobon.bulk_fetch", return_value=list(detail_map.items())
    ) as details:
        rows = scrape(max_pages=3)

    assert pages.call_count == 2
    details.assert_called_once()
    assert len(rows) == 4
    assert len({row["id"] for row in rows}) == 4
    assert {row["estrato"] for row in rows} == {3, 4, 5}
    assert rows[-1]["parqueaderos"] == 2
    assert all(list(row) == COLUMNS for row in rows)


def test_scrape_keeps_card_defaults_when_detail_fails() -> None:
    with mock.patch(
        "scrape.arangotobon.fetch_page", return_value=_load("search_page.html")
    ), mock.patch("scrape.arangotobon.bulk_fetch", return_value=[]):
        rows = scrape(max_pages=1)

    assert len(rows) == 4
    assert all(row["estrato"] == 0 for row in rows)
    assert all(row["parqueaderos"] == 0 for row in rows)
