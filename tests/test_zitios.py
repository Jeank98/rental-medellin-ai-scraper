"""Fixture-backed tests for the Zitios two-phase scraper."""

from pathlib import Path
from unittest import mock

import pytest

from scrape.zitios import (
    DetailFields,
    Listing,
    UnsupportedCityError,
    _merge_detail,
    _page_url,
    parse_detail_page,
    parse_search_page,
    scrape,
)

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


def test_page_url_uses_city_and_property_routes() -> None:
    assert _page_url(1) == "https://zitios.com.co/inmuebles/g/arriendo/c/medell%C3%ADn/"
    assert _page_url(1, "apartamentos") == (
        "https://zitios.com.co/inmuebles/g/arriendo/t/apartamentos/c/medell%C3%ADn/"
    )
    assert _page_url(4, "casas").endswith("?pagina=4")


def test_page_url_supports_verified_metro_municipalities() -> None:
    assert _page_url(1, None, "envigado") == (
        "https://zitios.com.co/inmuebles/g/arriendo/c/envigado/"
    )
    assert _page_url(1, "apartamentos", "Itagüí") == (
        "https://zitios.com.co/inmuebles/g/arriendo/t/apartamentos/c/itagui/"
    )
    assert _page_url(2, "casas", "sabaneta").endswith("/c/sabaneta/?pagina=2")


def test_page_url_rejects_unverified_municipality() -> None:
    try:
        _page_url(1, None, "la estrella")
    except UnsupportedCityError:
        pass
    else:
        raise AssertionError("Expected La Estrella to be rejected until its slug is known")


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


def test_detail_parser_recovers_contract_fields_and_leaves_missing_garage_unknown() -> None:
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


@pytest.mark.parametrize(("label", "expected"), [
    ("Garajes: 2", 2),
    ("Parqueaderos: 3", 3),
])
def test_detail_parking_reads_plural_garages_label(label, expected) -> None:
    detail = parse_detail_page(f"<html><body><li>{label}</li></body></html>")
    assert detail["parqueaderos"] == expected

    row = parse_search_page(_load("search_page_1.html"))[0]
    row["parqueaderos"] = 2
    _merge_detail(row, detail)
    assert row["parqueaderos"] == expected


def test_detail_barrio_never_replaces_card_barrio_with_related_listing_metadata() -> None:
    cases = (
        ("ZIT-10135574", "Santa Monica", "Belen Fatima"),
        ("ZIT-10226561", "Guayabal", "Estadio"),
        ("ZIT-10065898", "Belen Fatima", "Estadio"),
    )

    for listing_id, card_barrio, detail_barrio in cases:
        row: Listing = {
            "id": listing_id,
            "portal": "zitios",
            "tipo": "apartamento",
            "precio": 0,
            "area": 0,
            "habitaciones": 0,
            "banos": 0,
            "parqueaderos": 0,
            "estrato": 0,
            "barrio": card_barrio,
            "url": "",
        }
        detail: DetailFields = {
            "tipo": "",
            "precio": 0,
            "area": 0,
            "habitaciones": 0,
            "banos": 0,
            "parqueaderos": None,
            "estrato": 0,
            "barrio": detail_barrio,
        }

        _merge_detail(row, detail)

        assert row["barrio"] == card_barrio, listing_id

    missing_card_barrio: Listing = {
        "id": "ZIT-MISSING-BARRIO",
        "portal": "zitios",
        "tipo": "apartamento",
        "precio": 0,
        "area": 0,
        "habitaciones": 0,
        "banos": 0,
        "parqueaderos": 0,
        "estrato": 0,
        "barrio": "",
        "url": "",
    }
    detail_barrio: DetailFields = {
        "tipo": "",
        "precio": 0,
        "area": 0,
        "habitaciones": 0,
        "banos": 0,
        "parqueaderos": None,
        "estrato": 0,
        "barrio": "Laureles",
    }

    _merge_detail(missing_card_barrio, detail_barrio)

    assert missing_card_barrio["barrio"] == "Laureles"



def test_merge_detail_preserves_card_parking_when_detail_omits_it() -> None:
    row = parse_search_page(_load("search_page_1.html"))[0]
    detail = parse_detail_page(_load("detail_10125019.html"))
    assert row["parqueaderos"] == 1
    assert detail["parqueaderos"] is None

    _merge_detail(row, detail)
    assert row["parqueaderos"] == 1

    detail["parqueaderos"] = 0
    _merge_detail(row, detail)
    assert row["parqueaderos"] == 0


def test_scrape_unions_canonical_fifth_page_after_commercial_only_pages() -> None:
    def card(code: int, slug: str, heading: str) -> str:
        return (
            '<article itemprop="itemListElement">'
            f'<a href="/inmueble/{slug}_{code}"><h2>{heading} enArriendo</h2></a>'
            "</article>"
        )

    duplicate = card(1, "arriendo-apartamento", "Apartamento")
    def commercial(page: int) -> str:
        return card(100 + page, "arriendo-local", "Local")

    subtype = card(2, "arriendo-apartamento", "Penthouse")
    requested = []

    def fetch(url: str) -> str:
        requested.append(url)
        if url == _page_url(1, "apartamentos"):
            return duplicate
        for page in range(1, 6):
            if url == _page_url(page):
                return (duplicate if page == 1 else "") + commercial(page) + (
                    subtype if page == 5 else ""
                )
        return ""

    with (
        mock.patch("scrape.zitios.fetch_page", side_effect=fetch),
        mock.patch("scrape.zitios.bulk_fetch", return_value=[]) as details,
    ):
        rows = scrape()

    assert [row["id"] for row in rows] == ["ZIT-1", "ZIT-2"]
    assert _page_url(5) in requested
    assert _page_url(6) in requested
    assert details.call_args.args[0] == [row["url"] for row in rows]


@pytest.mark.parametrize("bad_html", [
    None, "", "<title>Just a moment...</title>", "<script src='/challenge-platform/x'></script>",
])
def test_scrape_rejects_unavailable_or_challenged_canonical_first_page(bad_html) -> None:
    with mock.patch(
        "scrape.zitios.fetch_page",
        side_effect=lambda url: bad_html if url == _page_url(1) else "",
    ):
        with pytest.raises(RuntimeError):
            scrape(sample_only=True)


@pytest.mark.parametrize(("sample_only", "max_pages", "expected_pages"), [
    (True, None, 1),
    (False, 2, 2),
    (False, 5, 5),
])
def test_scrape_honors_sample_and_explicit_page_bounds(
    sample_only, max_pages, expected_pages
) -> None:
    requested = []

    def fetch(url: str) -> str:
        requested.append(url)
        for page in range(1, 7):
            if url == _page_url(page):
                return (
                    '<article itemprop="itemListElement">'
                    f'<a href="/inmueble/arriendo-local_{page}">'
                    "<h2>Local enArriendo</h2></a></article>"
                )
        return ""

    with mock.patch("scrape.zitios.fetch_page", side_effect=fetch):
        scrape(sample_only=sample_only, max_pages=max_pages)

    assert _page_url(expected_pages) in requested
    assert _page_url(expected_pages + 1) not in requested


def test_scrape_stops_when_a_source_page_repeats() -> None:
    requested = []
    card = (
        '<article itemprop="itemListElement">'
        '<a href="/inmueble/arriendo-local_1"><h2>Local enArriendo</h2></a>'
        "</article>"
    )

    def fetch(url: str) -> str:
        requested.append(url)
        return card if url in (_page_url(1), _page_url(2)) else ""

    with mock.patch("scrape.zitios.fetch_page", side_effect=fetch):
        assert scrape() == []

    assert _page_url(2) in requested
    assert _page_url(3) not in requested


def test_scrape_deduplicates_ids_merges_details_and_keeps_exact_contract() -> None:
    pages = {
        _page_url(page, property_type): _load(
            f"search_page_{page}.html"
        )
        for property_type in ("apartamentos", "casas", "apartaestudios", None)
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
        for property_type in ("apartamentos", "casas", "apartaestudios", None)
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




def test_scrape_reuses_unchanged_detail_candidates_without_replacing_card_barrio(
    capsys,
) -> None:
    search_html = _load("search_page_1.html")
    reused, changed = parse_search_page(search_html)
    assert reused["barrio"]
    previous = {
        reused["id"]: {
            **reused,
            "area": 99,
            "habitaciones": 4,
            "banos": 3,
            "parqueaderos": 2,
            "estrato": 6,
            "barrio": "Anterior",
        },
        changed["id"]: {**changed, "precio": changed["precio"] - 1},
    }

    search_urls = {
        _page_url(1, property_type)
        for property_type in ("apartamentos", "casas", "apartaestudios", None)
    }
    with (
        mock.patch(
            "scrape.zitios.fetch_page",
            side_effect=lambda url: search_html if url in search_urls else "",
        ),
        mock.patch(
            "scrape.zitios.bulk_fetch",
            return_value=[(changed["url"], _load("detail_10125019.html"))],
        ) as detail_fetch,
        mock.patch("db.get_active_listings_by_id", return_value=previous) as snapshot,
    ):
        rows = scrape(max_pages=1, reuse_unchanged_details=True)

    snapshot.assert_called_once_with("zitios", "medellin")
    assert detail_fetch.call_args.args[0] == [changed["url"]]
    assert "ZIT detail reuse: 1 reused; 1 detail pages fetched" in capsys.readouterr().out
    by_id = {row["id"]: row for row in rows}
    assert by_id[reused["id"]]["area"] == 99
    assert by_id[reused["id"]]["estrato"] == 6
    assert by_id[reused["id"]]["barrio"] == reused["barrio"]
def test_scrape_never_sends_non_residential_cards_to_detail_fetch() -> None:
    search_url = _page_url(1, "apartamentos")
    detail_url = (
        "https://zitios.com.co/inmueble/arriendo-apartamento-robledo-pajarito_10188009"
    )

    def fetch(url: str) -> str:
        return _load("search_page_non_residential.html") if url in (search_url, _page_url(1)) else ""

    with mock.patch("scrape.zitios.fetch_page", side_effect=fetch), mock.patch(
        "scrape.zitios.bulk_fetch",
        side_effect=lambda urls: [(detail_url, _load("detail_10188009.html"))],
    ) as bulk_mock:
        rows = scrape(max_pages=1)

    assert [row["id"] for row in rows] == ["ZIT-10188009"]
    assert bulk_mock.call_args.args[0] == [detail_url]


def test_scrape_never_sends_commercial_house_to_detail_fetch() -> None:
    search_url = _page_url(1, "casas")
    residential_url = (
        "https://zitios.com.co/inmueble/arriendo-casa-en-belen-la-gloria_10017304"
    )
    commercial_url = (
        "https://zitios.com.co/inmueble/arriendo-casa-comercial-en-belen-la-gloria_10017303"
    )

    def fetch(url: str) -> str:
        return _load("search_page_commercial_house.html") if url in (search_url, _page_url(1)) else ""

    with mock.patch("scrape.zitios.fetch_page", side_effect=fetch), mock.patch(
        "scrape.zitios.bulk_fetch", return_value=[]
    ) as bulk_mock:
        rows = scrape(max_pages=1)

    assert [row["id"] for row in rows] == ["ZIT-10017304"]
    assert commercial_url not in [row["url"] for row in rows]
    assert bulk_mock.call_args.args[0] == [residential_url]
