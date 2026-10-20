"""Fixture-backed tests for the Arango Tobon two-phase scraper (WordPress site)."""

from pathlib import Path
from unittest import mock

from scrape.arangotobon import (
    COLUMNS,
    PREFIX,
    SEARCH_URL,
    UnsupportedCityError,
    build_page_url,
    count_cards,
    merge_detail,
    parse_detail_page,
    parse_search_page,
    parse_total_results,
    scrape,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "arangotobon"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_build_page_url_uses_canonical_search_route_and_pag_param() -> None:
    assert build_page_url(1) == SEARCH_URL
    assert build_page_url(1) == (
        "https://arangotobon.com/todas-las-propiedades/"
        "?destinacion=Arriendo&municipio=medellin"
    )
    assert build_page_url(3).endswith("&pag=3")


def test_build_page_url_rejects_unconfirmed_city() -> None:
    try:
        build_page_url(1, "bogota")
    except UnsupportedCityError:
        pass
    else:
        raise AssertionError("Expected unsupported city to be rejected")


def test_search_parser_maps_residential_cards_and_skips_other_classes() -> None:
    rows = parse_search_page(_load("search_page.html"))

    assert [row["id"] for row in rows] == [
        f"{PREFIX}-3386",
        f"{PREFIX}-3824",
        f"{PREFIX}-4557",
        f"{PREFIX}-367",
    ]
    assert {row["tipo"] for row in rows} == {"apartamento"}
    assert [row["precio"] for row in rows] == [1800000, 2000000, 2100000, 2400000]
    assert [row["area"] for row in rows] == [75, 70, 55, 65]
    assert [row["barrio"] for row in rows] == [
        "Belen Los Alpes",
        "Belen Los Alpes",
        "Floridanueva",
        "San Joaquin",
    ]
    assert all(row["parqueaderos"] == 0 for row in rows)
    assert all(row["portal"] == "arangotobon" for row in rows)
    assert all(list(row) == COLUMNS for row in rows)
    assert len({row["url"] for row in rows}) == len(rows)


def test_search_page_counter_and_card_count_are_readable() -> None:
    search = _load("search_page.html")

    assert parse_total_results(search) == 40
    assert count_cards(search) == 5
    assert parse_total_results(_load("empty_page.html")) == 0
    assert count_cards(_load("empty_page.html")) == 0
    assert parse_search_page(_load("empty_page.html")) == []


def test_detail_parser_reads_features_and_structured_parking() -> None:
    detail = parse_detail_page(_load("detail_1748.html"))

    assert detail == {
        "codigo": "1748",
        "tipo": "apartamento",
        "precio": 2600000,
        "area": 62,
        "habitaciones": 2,
        "banos": 2,
        "parqueaderos": 1,
        "estrato": 4,
        "barrio": "Belen Fatima",
    }

    no_parking = parse_detail_page(_load("detail_3386.html"))
    assert no_parking["parqueaderos"] == 0
    assert no_parking["estrato"] == 3
    assert no_parking["habitaciones"] == 2
    assert no_parking["banos"] == 1
    assert no_parking["barrio"] == "Belen Los Alpes"


def test_merge_detail_rejects_code_mismatch_without_changing_identity() -> None:
    row = parse_search_page(_load("search_page.html"))[0]
    detail = parse_detail_page(_load("detail_9999_mismatch.html"))

    assert merge_detail(row, detail) is False
    assert row["id"] == f"{PREFIX}-3386"
    assert row["estrato"] == 0
    assert row["habitaciones"] == 0


def test_merge_detail_fills_detail_only_fields() -> None:
    row = parse_search_page(_load("search_page.html"))[0]
    detail = parse_detail_page(_load("detail_3386.html"))

    assert merge_detail(row, detail) is True
    assert row["habitaciones"] == 2
    assert row["banos"] == 1
    assert row["estrato"] == 3
    assert row["parqueaderos"] == 0
    assert row["precio"] == 1800000


def test_scrape_deduplicates_stale_pages_fetches_details_and_merges() -> None:
    search = _load("search_page.html")
    parsed = parse_search_page(search)
    detail_names = {
        "3386": "detail_3386.html",
        "3824": "detail_3824.html",
        "4557": "detail_4557.html",
        "367": "detail_367.html",
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
    assert all(row["estrato"] > 0 for row in rows)
    assert all(list(row) == COLUMNS for row in rows)


def test_scrape_reuses_unchanged_detail_fields_and_fetches_only_price_misses(
    capsys,
) -> None:
    search = _load("search_page.html")
    reused, changed, *new_rows = parse_search_page(search)
    detail_names = {
        "3386": "detail_3386.html",
        "3824": "detail_3824.html",
        "4557": "detail_4557.html",
        "367": "detail_367.html",
    }
    details = {
        row["url"]: _load(detail_names[row["id"].split("-", 1)[1]])
        for row in [changed, *new_rows]
    }
    previous = {
        reused["id"]: {
            **reused,
            "habitaciones": 4,
            "banos": 3,
            "estrato": 6,
            "barrio": "Anterior",
            "parqueaderos": 2,
        },
        changed["id"]: {**changed, "precio": changed["precio"] - 1},
    }

    with (
        mock.patch("scrape.arangotobon.fetch_page", return_value=search),
        mock.patch(
            "scrape.arangotobon.bulk_fetch",
            return_value=list(details.items()),
        ) as detail_fetch,
        mock.patch("db.get_active_listings_by_id", return_value=previous) as snapshot,
    ):
        rows = scrape(max_pages=1, reuse_unchanged_details=True)

    snapshot.assert_called_once_with("arangotobon", "medellin")
    assert detail_fetch.call_args.args[0] == [row["url"] for row in [changed, *new_rows]]
    assert "ATB detail reuse: 1 reused; 3 detail pages fetched" in capsys.readouterr().out
    by_id = {row["id"]: row for row in rows}
    assert by_id[reused["id"]]["estrato"] == 6
    assert by_id[reused["id"]]["barrio"] == "Anterior"
    assert by_id[reused["id"]]["habitaciones"] == 4
    assert by_id[reused["id"]]["parqueaderos"] == 2


def test_scrape_keeps_card_defaults_when_detail_fails() -> None:
    with mock.patch(
        "scrape.arangotobon.fetch_page", return_value=_load("search_page.html")
    ), mock.patch("scrape.arangotobon.bulk_fetch", return_value=[]):
        rows = scrape(max_pages=1)

    assert len(rows) == 4
    assert all(row["estrato"] == 0 for row in rows)
    assert all(row["parqueaderos"] == 0 for row in rows)
    assert all(row["precio"] > 0 for row in rows)
