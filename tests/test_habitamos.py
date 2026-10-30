"""Habitamos REST adapter.

The portal moved its results from server-rendered cards to
``/api/propiedades/buscar``; these tests pin the new contract so a silent
empty-listing regression fails here instead of in the orchestrator.
"""

import json

import pytest

from scrape import habitamos
from scrape.habitamos import (
    UnsupportedCityError,
    build_api_url,
    parse_search_payload,
    resolve_municipio,
    to_listing,
)

PAYLOAD = {
    "resultados": [
        {
            "codigo": 70456,
            "negocio": "Arriendo",
            "tipo": "Apartamento",
            "municipio": "Envigado",
            "barrio": "El Dorado",
            "precio_arriendo": 2_900_000,
            "precio_venta": 0,
            "area": "68",
            "area_numero": 68,
            "alcobas": 2,
            "banos": 2,
            "parqueaderos": 1,
            "foto": "https://factura-habitamos.s3.amazonaws.com/fotos/foto.jpeg",
        },
        {
            "codigo": 70457,
            "negocio": "Arriendo",
            "tipo": "Local",
            "municipio": "Envigado",
            "barrio": "Centro",
            "precio_arriendo": 3_500_000,
            "area_numero": 40,
            "alcobas": 0,
            "banos": 1,
            "parqueaderos": 0,
        },
        {
            "codigo": 70458,
            "negocio": "Arriendo",
            "tipo": "Casa",
            "municipio": "Envigado",
            "barrio": "Las Flores",
            "precio_arriendo": 0,
            "area_numero": 120,
            "alcobas": 3,
            "banos": 2,
            "parqueaderos": 2,
        },
    ],
    "total": 55,
    "pagina": 1,
    "por_pagina": 12,
    "total_paginas": 5,
}


def test_payload_is_unwrapped_from_the_html_body() -> None:
    raw = "<html><body>" + json.dumps(PAYLOAD) + "</body></html>"

    parsed = parse_search_payload(raw)

    assert parsed["total_paginas"] == 5
    assert len(parsed["resultados"]) == 3


def test_non_json_payload_fails_loudly() -> None:
    with pytest.raises(ValueError):
        parse_search_payload("<html><body>Service Unavailable</body></html>")


def test_apartment_maps_to_the_eleven_columns() -> None:
    row = to_listing(PAYLOAD["resultados"][0])

    assert row == {
        "id": "HBM-70456",
        "portal": "habitamos",
        "tipo": "apartamento",
        "precio": 2_900_000,
        "area": 68,
        "habitaciones": 2,
        "banos": 2,
        "parqueaderos": 1,
        "estrato": 0,
        "barrio": "El Dorado",
        "url": "https://www.habitamos.com.co/propiedades/70456",
    }


def test_non_residential_inventory_is_dropped() -> None:
    assert to_listing(PAYLOAD["resultados"][1]) is None


def test_listing_without_a_rent_price_is_dropped() -> None:
    assert to_listing(PAYLOAD["resultados"][2]) is None


def test_api_url_filters_by_municipality() -> None:
    url = build_api_url(3, "Itagüí")

    assert "pagina=3" in url
    assert "comercio=arriendo" in url
    assert "Itag%C3%BC%C3%AD" in url


@pytest.mark.parametrize(
    ("ciudad", "expected"),
    [
        ("medellin", "Medellín"),
        ("Medellín", "Medellín"),
        ("envigado", "Envigado"),
        ("ITAGUI", "Itagüí"),
        ("sabaneta", "Sabaneta"),
        ("la-estrella", "La Estrella"),
        ("La Estrella", "La Estrella"),
    ],
)
def test_city_labels_resolve(ciudad, expected) -> None:
    assert resolve_municipio(ciudad) == expected


def test_unknown_city_raises_instead_of_scraping_another_municipality() -> None:
    with pytest.raises(UnsupportedCityError):
        resolve_municipio("bogota")


def test_scrape_paginates_until_total_pages(monkeypatch) -> None:
    pages = {
        1: {**PAYLOAD, "pagina": 1, "total_paginas": 2},
        2: {
            **PAYLOAD,
            "pagina": 2,
            "total_paginas": 2,
            "resultados": [{**PAYLOAD["resultados"][0], "codigo": 70499}],
        },
    }
    requested: list[int] = []

    def fake_fetch(url: str) -> str:
        page = int(url.split("pagina=")[1].split("&")[0])
        requested.append(page)
        return "<html><body>" + json.dumps(pages[page]) + "</body></html>"

    monkeypatch.setattr(habitamos, "fetch_page", fake_fetch)

    rows = habitamos.scrape(ciudad="envigado")

    assert requested == [1, 2]
    assert [row["id"] for row in rows] == ["HBM-70456", "HBM-70499"]
