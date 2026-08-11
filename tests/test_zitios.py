"""Fixture-backed tests for the Zitios two-phase scraper."""

from pathlib import Path
from unittest import mock

from scrape.zitios import _page_url, parse_detail_page, parse_search_page, scrape

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "zitios"
CANONICAL_COLUMNS = [
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


def test_page_url_uses_verified_four_page_route() -> None:
    assert _page_url(1) == "https://zitios.com.co/inmuebles/g/arriendo/c/medell%C3%ADn/"
    assert _page_url(4).endswith("?pagina=4")


def test_search_parser_filters_mixed_management_and_uses_slug_type() -> None:
    rows = parse_search_page(_load("search_page_1.html"))

    assert [row["id"] for row in rows] == ["ZIT-10188009", "ZIT-10125019"]
    assert rows[0]["tipo"] == "apartamento"
    assert rows[0]["parqueaderos"] == 1
    assert rows[1]["tipo"] == "apartaestudio"
    assert rows[1]["parqueaderos"] == 0
    assert rows[1]["estrato"] == 0
    assert list(rows[0]) == CANONICAL_COLUMNS


def test_detail_parser_recovers_contract_fields_and_proves_missing_garage() -> None:
    detail = parse_detail_page(_load("detail_10188009.html"))

    assert detail["tipo"] == "apartamento"
    assert detail["precio"] == 2000000
    assert detail["area"] == 55
    assert detail["habitaciones"] == 3
    assert detail["banos"] == 2
    assert detail["parqueaderos"] == 1
    assert detail["estrato"] == 3
    assert detail["barrio"] == "Robledo Pajarito"

    sparse = parse_detail_page(_load("detail_10125019.html"))
    assert sparse["parqueaderos"] is None


def test_scrape_deduplicates_ids_merges_details_and_keeps_exact_contract() -> None:
    pages = {
        _page_url(1): _load("search_page_1.html"),
        _page_url(2): _load("search_page_2.html"),
    }
    details = {
        "https://zitios.com.co/inmueble/arriendo-apartamento-robledo-pajarito_10188009": _load(
            "detail_10188009.html"
        ),
        "https://zitios.com.co/inmueble/arriendo-apartaestudio-en-calasanz_10125019": _load(
            "detail_10125019.html"
        ),
        "https://zitios.com.co/inmueble/arriendo-local-en-anda-lucia-la-francia_10008418": _load(
            "detail_10008418.html"
        ),
    }

    def fetch(url: str) -> str:
        return pages.get(url, "")

    def bulk(urls: list[str]) -> list[tuple[str, str]]:
        return [(url, details[url]) for url in urls]

    with mock.patch("scrape.zitios.fetch_page", side_effect=fetch), mock.patch(
        "scrape.zitios.bulk_fetch", side_effect=bulk
    ) as bulk_mock:
        rows = scrape(max_pages=2)

    assert [row["id"] for row in rows] == [
        "ZIT-10188009",
        "ZIT-10125019",
        "ZIT-10008418",
    ]
    assert len(rows) == 3
    assert rows[0]["estrato"] == 3
    assert rows[0]["parqueaderos"] == 1
    assert rows[1]["estrato"] == 0
    assert rows[1]["parqueaderos"] == 0
    assert rows[2]["tipo"] == "local"
    assert rows[2]["habitaciones"] == 0
    assert rows[2]["banos"] == 1
    assert all(list(row) == CANONICAL_COLUMNS for row in rows)
    assert bulk_mock.call_args.args[0] == [
        "https://zitios.com.co/inmueble/arriendo-apartamento-robledo-pajarito_10188009",
        "https://zitios.com.co/inmueble/arriendo-apartaestudio-en-calasanz_10125019",
        "https://zitios.com.co/inmueble/arriendo-local-en-anda-lucia-la-francia_10008418",
    ]
