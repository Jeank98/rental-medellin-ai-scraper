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
    assert _page_url(1, "apartamentos") == (
        "https://zitios.com.co/inmuebles/g/arriendo/t/apartamentos/c/medell%C3%ADn/"
    )
    assert _page_url(4, "casas").endswith("?pagina=4")


def test_search_parser_filters_non_residential_and_uses_slug_type() -> None:
    rows = parse_search_page(_load("search_page_1.html"))

    assert [row["id"] for row in rows] == ["ZIT-10188009", "ZIT-10125019"]
    assert rows[0]["tipo"] == "apartamento"
    assert rows[0]["parqueaderos"] == 1
    assert rows[1]["tipo"] == "apartaestudio"
    assert rows[1]["parqueaderos"] == 0
    assert rows[1]["estrato"] == 0
    assert list(rows[0]) == CANONICAL_COLUMNS


def test_search_parser_rejects_non_residential_and_mixed_management_cards() -> None:
    rows = parse_search_page(_load("search_page_non_residential.html"))

    assert [row["tipo"] for row in rows] == ["apartamento"]
    assert [row["id"] for row in rows] == ["ZIT-10188009"]


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
        _page_url(page, property_type): _load(
            f"search_page_{page}.html"
        )
        for property_type in ("apartamentos", "casas", "apartaestudios")
        for page in (1, 2)
    }
    requested_urls: list[str] = []
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
        requested_urls.append(url)
        return pages.get(url, "")

    def bulk(urls: list[str]) -> list[tuple[str, str]]:
        return [(url, details[url]) for url in urls]

    with mock.patch("scrape.zitios.fetch_page", side_effect=fetch), mock.patch(
        "scrape.zitios.bulk_fetch", side_effect=bulk
    ) as bulk_mock:
        rows = scrape(max_pages=2)

    assert requested_urls == [
        _page_url(page, property_type)
        for property_type in ("apartamentos", "casas", "apartaestudios")
        for page in (1, 2)
    ]
    assert [row["id"] for row in rows] == ["ZIT-10188009", "ZIT-10125019"]
    assert len(rows) == 2
    assert rows[0]["estrato"] == 3
    assert rows[0]["parqueaderos"] == 1
    assert rows[1]["estrato"] == 0
    assert rows[1]["parqueaderos"] == 0
    assert all(list(row) == CANONICAL_COLUMNS for row in rows)
    assert bulk_mock.call_args.args[0] == [
        "https://zitios.com.co/inmueble/arriendo-apartamento-robledo-pajarito_10188009",
        "https://zitios.com.co/inmueble/arriendo-apartaestudio-en-calasanz_10125019",
    ]


def test_scrape_never_sends_non_residential_cards_to_detail_fetch() -> None:
    search_url = _page_url(1, "apartamentos")
    detail_url = (
        "https://zitios.com.co/inmueble/arriendo-apartamento-robledo-pajarito_10188009"
    )

    def fetch(url: str) -> str:
        return _load("search_page_non_residential.html") if url == search_url else ""

    with mock.patch("scrape.zitios.fetch_page", side_effect=fetch), mock.patch(
        "scrape.zitios.bulk_fetch",
        side_effect=lambda urls: [(detail_url, _load("detail_10188009.html"))],
    ) as bulk_mock:
        rows = scrape(max_pages=1)

    assert [row["id"] for row in rows] == ["ZIT-10188009"]
    assert bulk_mock.call_args.args[0] == [detail_url]
