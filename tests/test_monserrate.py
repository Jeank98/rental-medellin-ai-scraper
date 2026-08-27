"""Fixture-backed tests for the Monserrate DOM-scoped detail parser."""

from pathlib import Path
from unittest import mock

from scrape.arrendamientosmonserrate import (
    _merge_detail,
    _parse_detail_page,
    scrape,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "monserrate"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _row(url: str = "https://www.arrendamientosmonserrate.com/propiedad/barrio-miranda/") -> dict:
    return {
        "id": "",
        "portal": "arrendamientosmonserrate",
        "tipo": "",
        "precio": 1_500_000,
        "area": 0,
        "habitaciones": 0,
        "banos": 0,
        "parqueaderos": 0,
        "estrato": 0,
        "barrio": "",
        "url": url,
    }


def test_detail_parser_uses_attributes_table_and_sku_not_sidebar_options() -> None:
    row = _row()
    _merge_detail(row, _parse_detail_page(_load("detail_sidebar_contamination.html")))

    assert row["id"] == "MNS-A62"
    assert row["tipo"] == "bodega"
    assert row["barrio"] == "Centro"
    assert row["banos"] == 2
    assert row["estrato"] == 0
    assert row["area"] == 0
    assert row["habitaciones"] == 0
    assert row["parqueaderos"] == 0
    assert "$" not in row["barrio"]
    assert "opci" not in row["barrio"].lower()
def test_detail_parser_bounds_first_valid_numeric_value() -> None:
    detail = {
        "area": "999999 m², 80 m²",
        "habitaciones": "99 opciones, 3 alcobas",
        "banos": "99 baños, 2 sanitarios, 1 lavamanos.",
        "estrato": "10",
        "parqueaderos": "Doble lineal",
    }
    row = _row()
    _merge_detail(row, detail)

    assert row["area"] == 80
    assert row["habitaciones"] == 3
    assert row["banos"] == 2
    assert row["estrato"] == 0
    assert row["parqueaderos"] == 2

def test_detail_parser_keeps_absent_attributes_at_zero() -> None:
    row = _row()
    _merge_detail(row, {"tipo": "Apartamento", "barrio": "Miranda"})

    assert row["tipo"] == "apartamento"
    assert row["barrio"] == "Miranda"
    assert row["area"] == 0
    assert row["habitaciones"] == 0
    assert row["banos"] == 0
    assert row["parqueaderos"] == 0
    assert row["estrato"] == 0


def test_missing_code_gets_deterministic_non_empty_url_fallback() -> None:
    first = _row("https://example.test/propiedad/uno/")
    second = _row("https://example.test/propiedad/uno/")
    different = _row("https://example.test/propiedad/dos/")

    _merge_detail(first, {})
    _merge_detail(second, {})
    _merge_detail(different, {})

    assert first["id"]
    assert first["id"] == second["id"]
    assert first["id"] != different["id"]


def test_duplicate_detail_codes_receive_unique_ids() -> None:
    listing_page = """
    <ul>
      <li class="product type-product">
        <a href="/propiedad/uno/"><h2 class="woocommerce-loop-product__title">Local en Uno</h2></a>
        <span class="price">$1.000.000</span>
      </li>
      <li class="product type-product">
        <a href="/propiedad/dos/"><h2 class="woocommerce-loop-product__title">Local en Dos</h2></a>
        <span class="price">$2.000.000</span>
      </li>
    </ul>
    """
    detail = '<span class="sku_wrapper">Código: <span class="sku">A62</span></span>'

    with mock.patch(
        "scrape.arrendamientosmonserrate.fetch_page", return_value=listing_page
    ), mock.patch(
        "scrape.arrendamientosmonserrate.bulk_fetch",
        return_value=[
            ("https://www.arrendamientosmonserrate.com/propiedad/uno/", detail),
            ("https://www.arrendamientosmonserrate.com/propiedad/dos/", detail),
        ],
    ):
        rows = scrape(max_pages=1)

    assert len(rows) == 2
    assert len({row["id"] for row in rows}) == 2
    assert rows[0]["id"] == "MNS-A62"
    assert rows[1]["id"].startswith("MNS-A62-")
