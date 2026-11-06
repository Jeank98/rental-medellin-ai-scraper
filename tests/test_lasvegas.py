"""Las Vegas REST adapter: mapping, city codes and pagination."""

import json

import pytest

from scrape import lasvegas
from scrape.lasvegas import (
    UnsupportedCityError,
    build_api_url,
    parse_payload,
    resolve_city_code,
    to_listing,
)

ITEM = {
    "codpro": 516230,
    "city": "Sabaneta ",
    "city_code": 5631,
    "neighborhood": "Aves Maria",
    "type": "APARTAMENTO",
    "biz": "ARRIENDO",
    "biz_code": 1,
    "area_cons": 72,
    "bedrooms": 3,
    "bathrooms": 2,
    "parking": 1,
    "rent": 2_600_000,
    "price": "2600000",
    "stratum": 3,
}


def test_listing_maps_to_the_eleven_columns() -> None:
    assert to_listing(ITEM) == {
        "id": "LVG-516230",
        "portal": "arrendamientoslasvegas",
        "tipo": "apartamento",
        "precio": 2_600_000,
        "area": 72,
        "habitaciones": 3,
        "banos": 2,
        "parqueaderos": 1,
        "estrato": 3,
        "barrio": "Aves Maria",
        "url": "https://arrendamientoslasvegas.com/inmuebles/516230",
    }


def test_non_residential_and_priceless_records_are_dropped() -> None:
    assert to_listing({**ITEM, "type": "LOCAL"}) is None
    assert to_listing({**ITEM, "rent": 0, "price": "0"}) is None


def test_payload_unwraps_the_html_body() -> None:
    raw = "<html><body>" + json.dumps({"data": [ITEM], "last_page": 1}) + "</body></html>"

    assert parse_payload(raw)["last_page"] == 1


def test_non_json_payload_fails_loudly() -> None:
    with pytest.raises(ValueError):
        parse_payload("<html><body>maintenance</body></html>")


@pytest.mark.parametrize(
    ("ciudad", "code"),
    [
        ("medellin", 5001),
        ("Medellín", 5001),
        ("envigado", 5266),
        ("ITAGUI", 5360),
        ("sabaneta", 5631),
        ("la-estrella", 5380),
    ],
)
def test_city_codes_resolve(ciudad, code) -> None:
    assert resolve_city_code(ciudad) == code


def test_unknown_city_raises() -> None:
    with pytest.raises(UnsupportedCityError):
        resolve_city_code("bogota")


def test_api_url_uses_the_verified_parameters() -> None:
    url = build_api_url(3, 5631)

    assert "page=3" in url
    assert "perpage=50" in url
    assert "biz=1,3" in url
    assert "city=5631" in url


def test_scrape_paginates_until_last_page(monkeypatch) -> None:
    pages = {
        1: {"data": [ITEM], "last_page": 2},
        2: {"data": [{**ITEM, "codpro": 516999}], "last_page": 2},
    }
    requested: list[int] = []

    def fake_fetch(url: str) -> str:
        page = int(url.split("&page=")[1].split("&")[0])
        requested.append(page)
        return "<html><body>" + json.dumps(pages[page]) + "</body></html>"

    monkeypatch.setattr(lasvegas, "fetch_page", fake_fetch)

    rows = lasvegas.scrape(ciudad="sabaneta")

    assert requested == [1, 2]
    assert [row["id"] for row in rows] == ["LVG-516230", "LVG-516999"]
