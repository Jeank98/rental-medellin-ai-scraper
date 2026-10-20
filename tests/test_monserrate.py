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


def test_type_normalization_maps_punctuated_unifamiliar_house_to_casa() -> None:
    row = _row()
    _merge_detail(row, {"tipo": "casa unifamiliar."})

    assert row["tipo"] == "casa"
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


def test_reuses_unchanged_detail_fields_by_stable_url() -> None:
    listing_page = """
    <ul>
      <li class="product type-product">
        <a href="/propiedad/uno/"><h2 class="woocommerce-loop-product__title">Local en Uno</h2></a>
        <span class="price">$1.000.000</span>
      </li>
    </ul>
    """
    url = "https://www.arrendamientosmonserrate.com/propiedad/uno/"
    previous = {
        "MNS-A62": {
            **_row(url),
            "id": "MNS-A62",
            "precio": 1_000_000,
            "tipo": "bodega",
            "area": 120,
            "habitaciones": 1,
            "banos": 2,
            "parqueaderos": 1,
            "estrato": 4,
            "barrio": "Centro",
        }
    }

    with (
        mock.patch(
            "scrape.arrendamientosmonserrate.fetch_page",
            return_value=listing_page,
        ),
        mock.patch("db.get_active_listings_by_id", return_value=previous),
        mock.patch("scrape.arrendamientosmonserrate.bulk_fetch") as detail_fetch,
    ):
        rows = scrape(max_pages=1, reuse_unchanged_details=True)

    detail_fetch.assert_not_called()
    assert rows == [previous["MNS-A62"]]


def _listing_page(count: int) -> str:
    cards = "".join(
        f"""
      <li class="product type-product">
        <a href="/propiedad/p{index}/"><h2 class="woocommerce-loop-product__title">Local en {index}</h2></a>
        <span class="price">${index}.000.000</span>
      </li>"""
        for index in range(1, count + 1)
    )
    return f"<ul>{cards}</ul>"


def _detail_html(code: str) -> str:
    return f'<span class="sku_wrapper">Código: <span class="sku">{code}</span></span>'


def test_detail_phase_fetches_one_page_at_a_time(monkeypatch) -> None:
    import scrape.arrendamientosmonserrate as module

    monkeypatch.setattr(module, "_DETAIL_BATCH_PAUSE_SECONDS", 0)
    monkeypatch.setattr(module, "_LISTING_PAGE_PAUSE_SECONDS", 0)
    calls: list[tuple[list[str], int | None]] = []

    def fake_bulk(urls, max_workers=None):
        calls.append((list(urls), max_workers))
        return [(url, _detail_html(f"A{index}")) for index, url in enumerate(urls)]

    with mock.patch(
        "scrape.arrendamientosmonserrate.fetch_page",
        return_value=_listing_page(3),
    ), mock.patch(
        "scrape.arrendamientosmonserrate.bulk_fetch", side_effect=fake_bulk
    ):
        rows = scrape(max_pages=1)

    assert [len(urls) for urls, _ in calls] == [1, 1, 1]
    assert all(workers == 1 for _, workers in calls)
    assert len(rows) == 3


def test_unresolved_details_retry_once_before_merging(monkeypatch) -> None:
    import scrape.arrendamientosmonserrate as module

    monkeypatch.setattr(module, "_DETAIL_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(module, "_LISTING_PAGE_PAUSE_SECONDS", 0)
    attempts: list[list[str]] = []

    def fake_bulk(urls, max_workers=None):
        attempts.append(list(urls))
        if len(attempts) == 1:
            return [(url, "") for url in urls]
        return [(url, _detail_html("A62")) for url in urls]

    with mock.patch(
        "scrape.arrendamientosmonserrate.fetch_page",
        return_value=_listing_page(1),
    ), mock.patch(
        "scrape.arrendamientosmonserrate.bulk_fetch", side_effect=fake_bulk
    ):
        rows = scrape(max_pages=1)

    assert len(attempts) == 2
    assert rows[0]["id"] == "MNS-A62"


def test_mostly_unresolved_details_fail_instead_of_writing_card_only_rows(
    monkeypatch,
) -> None:
    import scrape.arrendamientosmonserrate as module

    monkeypatch.setattr(module, "_DETAIL_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(module, "_LISTING_PAGE_PAUSE_SECONDS", 0)

    with mock.patch(
        "scrape.arrendamientosmonserrate.fetch_page",
        return_value=_listing_page(5),
    ), mock.patch(
        "scrape.arrendamientosmonserrate.bulk_fetch",
        return_value=[],
    ):
        try:
            scrape(max_pages=1)
        except RuntimeError as error:
            assert "unresolved" in str(error)
        else:
            raise AssertionError("Expected unresolved details to fail the portal")


def test_small_unresolved_set_drops_rows_without_synthetic_ids(monkeypatch) -> None:
    import scrape.arrendamientosmonserrate as module

    monkeypatch.setattr(module, "_DETAIL_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(module, "_LISTING_PAGE_PAUSE_SECONDS", 0)
    missing_url = "https://www.arrendamientosmonserrate.com/propiedad/p3/"

    def fake_bulk(urls, max_workers=None):
        return [
            (url, "" if url == missing_url else _detail_html("A62"))
            for url in urls
        ]

    with mock.patch(
        "scrape.arrendamientosmonserrate.fetch_page",
        return_value=_listing_page(5),
    ), mock.patch(
        "scrape.arrendamientosmonserrate.bulk_fetch", side_effect=fake_bulk
    ):
        rows = scrape(max_pages=1)

    assert len(rows) == 4
    assert all(not str(row["id"]).startswith("MNS-URL") for row in rows)
    assert all(row["id"].startswith("MNS-") for row in rows)

