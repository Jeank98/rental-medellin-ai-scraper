"""Regression tests for the Escala Inmobiliaria REST scraper."""

import argparse
import io
from unittest import mock

import pytest

import scripts.scrape_escalainmobiliaria as escalainmobiliaria_cli
from scrape.escalainmobiliaria import (
    COLUMNS,
    build_page_url,
    parse_search_response,
    scrape,
    scrape_cities,
)


def _rental(codigo="900101", **overrides):
    """Build one realistic source record for the synthetic API page."""
    record = {
        "codigo": codigo,
        "tipo": "Apartamento",
        "operacion": "Arriendo",
        "ciudad": "Medellín",
        "barrio": "El Poblado",
        "precio": 2850000,
        "area": 92.5,
        "habitaciones": 3,
        "banos": 2,
        "parqueadero": 1,
        "estrato": 5,
    }
    record.update(overrides)
    return record


def _page(records, total=None):
    """Build one API page; total defaults to the number of returned records."""
    return {
        "propiedades": records,
        "total": len(records) if total is None else total,
    }


def test_rental_record_maps_all_eleven_contract_fields():
    rows = parse_search_response(_page([_rental()]), "medellin")

    assert list(rows[0]) == list(COLUMNS)
    assert rows[0] == {
        "id": "ESC-900101",
        "portal": "escalainmobiliaria",
        "tipo": "apartamento",
        "precio": 2850000,
        "area": 92,
        "habitaciones": 3,
        "banos": 2,
        "parqueaderos": 1,
        "estrato": 5,
        "barrio": "El Poblado",
        "url": "https://escalainmobiliaria.com.co/propiedad/900101",
    }


def test_source_scope_guards_reject_sale_wrong_city_and_mixed_types():
    records = [
        _rental("1"),
        _rental("2", operacion="Venta"),
        _rental("3", ciudad="Envigado"),
        _rental("4", ciudad=496),
        _rental("5", tipo="Casa-Finca"),
        _rental("6", tipo="Local"),
        _rental("7", tipo="Apartaestudio"),
    ]

    rows = parse_search_response(_page(records), "Medellín")

    assert [row["id"] for row in rows] == ["ESC-1", "ESC-4", "ESC-7"]
    assert [row["tipo"] for row in rows] == [
        "apartamento",
        "apartamento",
        "apartaestudio",
    ]
    # The same numeric city id is out of scope for Envigado and must not leak.
    assert parse_search_response(_page([_rental("8", ciudad=496)]), "envigado") == []
    assert (
        parse_search_response(_page([_rental("9", ciudad="Envigado")]), "envigado")[0][
            "id"
        ]
        == "ESC-9"
    )


def test_missing_and_text_values_normalize_to_contract_defaults():
    record = {
        "codigo": "77",
        "tipo": "Casa",
        "operacion": "Arriendo",
        "ciudad": "Sabaneta",
    }
    row = parse_search_response(_page([record]), "sabaneta")[0]

    assert row["precio"] == 0
    assert row["area"] == 0
    assert row["habitaciones"] == 0
    assert row["banos"] == 0
    assert row["parqueaderos"] == 0
    assert row["estrato"] == 0
    assert row["barrio"] == ""

    converted = parse_search_response(
        _page(
            [
                _rental(
                    "78",
                    area="73.9",
                    habitaciones="4",
                    banos=None,
                    parqueadero="No",
                    estrato="4",
                )
            ]
        ),
        "medellin",
    )[0]
    assert converted["area"] == 73
    assert converted["habitaciones"] == 4
    assert converted["banos"] == 0
    assert converted["parqueaderos"] == 0
    assert converted["estrato"] == 4
    assert (
        parse_search_response(_page([_rental("79", tipo=14)]), "medellin")[0]["tipo"]
        == "apartaestudio"
    )


def test_page_url_uses_numeric_city_zero_based_page_and_bounded_limit():
    assert build_page_url(496, 0) == (
        "https://escalainmobiliaria.com.co/api/v2/propiedades"
        "?ciudad=496&limite=100&pagina=0"
    )
    assert "pagina=7" in build_page_url(416, 7, 3)
    with pytest.raises(ValueError):
        build_page_url(496, 0, 101)
    with pytest.raises(ValueError):
        build_page_url(496, -1)


def test_pagination_ends_on_empty_page_after_last_record():
    pages = [
        _page([_rental("1"), _rental("2")], total=3),
        _page([_rental("3")], total=3),
        _page([], total=3),
    ]
    with (
        mock.patch("scrape.escalainmobiliaria.PAGE_SIZE", 2),
        mock.patch("scrape.escalainmobiliaria.fetch_json", side_effect=pages) as fetch,
    ):
        rows = scrape("medellin")

    assert [row["id"] for row in rows] == ["ESC-1", "ESC-2", "ESC-3"]
    assert fetch.call_count == 3


def test_live_total_drift_between_pages_is_not_a_pagination_failure():
    """The API recomputes ``total`` per request; insertions shift records down.

    Live shape (Medellín, 2026-10-22): page 0 reported 569, page 1 reported 570
    and repeated the previous page's last code, page 2 reported 571, the last
    data page carried the remainder, then an empty page ended the crawl.
    """
    pages = [
        _page([_rental("1"), _rental("2")], total=4),
        _page([_rental("2"), _rental("3")], total=5),
        _page([_rental("4"), _rental("5")], total=5),
        _page([], total=5),
    ]
    with (
        mock.patch("scrape.escalainmobiliaria.PAGE_SIZE", 2),
        mock.patch("scrape.escalainmobiliaria.fetch_json", side_effect=pages) as fetch,
    ):
        rows = scrape("medellin")

    assert [row["id"] for row in rows] == ["ESC-1", "ESC-2", "ESC-3", "ESC-4", "ESC-5"]
    assert fetch.call_count == 4


def test_filtered_source_records_still_count_toward_pagination_progress():
    """Sale, wrong-city and commercial rows are filtered but still advance progress."""
    pages = [
        _page(
            [
                _rental("1"),
                _rental("2", operacion="Venta"),
                _rental("3", ciudad="Envigado"),
                _rental("4", tipo="Local"),
            ],
            total=4,
        ),
        _page([], total=4),
    ]
    with mock.patch("scrape.escalainmobiliaria.fetch_json", side_effect=pages) as fetch:
        rows = scrape("medellin")

    assert [row["id"] for row in rows] == ["ESC-1"]
    assert fetch.call_count == 2


def test_missing_or_unusable_source_code_is_integrity_failure():
    """A malformed record must fail, never satisfy completeness as empty output."""
    alone = _page([_rental(codigo=None)], total=1)
    with mock.patch("scrape.escalainmobiliaria.fetch_json", return_value=alone):
        with pytest.raises(RuntimeError, match="usable codigo"):
            scrape("medellin")

    mixed = _page([_rental("1"), _rental(codigo="   ")], total=2)
    with mock.patch("scrape.escalainmobiliaria.fetch_json", return_value=mixed):
        with pytest.raises(RuntimeError, match="usable codigo"):
            scrape("medellin")

    unusable = _page([_rental("2"), _rental(codigo=900101.5)], total=2)
    with pytest.raises(RuntimeError, match="usable codigo"):
        parse_search_response(unusable, "medellin")


def test_pagination_detects_repeated_page_and_premature_empty_page():
    with (
        mock.patch("scrape.escalainmobiliaria.PAGE_SIZE", 2),
        mock.patch(
            "scrape.escalainmobiliaria.fetch_json",
            side_effect=[
                _page([_rental("1"), _rental("2")], total=4),
                _page([_rental("1"), _rental("2")], total=4),
            ],
        ),
    ):
        with pytest.raises(RuntimeError, match="repeated page"):
            scrape("medellin")

    with (
        mock.patch("scrape.escalainmobiliaria.PAGE_SIZE", 2),
        mock.patch(
            "scrape.escalainmobiliaria.fetch_json",
            side_effect=[
                _page([_rental("1"), _rental("2")], total=4),
                _page([], total=4),
            ],
        ),
    ):
        with pytest.raises(RuntimeError, match="ended early"):
            scrape("medellin")


def test_pagination_rejects_more_records_than_any_reported_total():
    with mock.patch("scrape.escalainmobiliaria.fetch_json") as fetch:
        fetch.return_value = _page([_rental("1"), _rental("2"), _rental("3")], total=2)
        with pytest.raises(RuntimeError, match="reported a total of at most 2"):
            scrape("medellin")


def test_full_walk_fails_when_records_are_lost_between_pages():
    """A full crawl must see at least the smallest total the API reported."""
    pages = [
        _page([_rental("1"), _rental("2")], total=5),
        _page([_rental("3")], total=5),
        _page([], total=5),
    ]
    with (
        mock.patch("scrape.escalainmobiliaria.PAGE_SIZE", 2),
        mock.patch("scrape.escalainmobiliaria.fetch_json", side_effect=pages),
    ):
        with pytest.raises(RuntimeError, match="ended early"):
            scrape("medellin")


def test_stale_empty_page_total_cannot_lower_the_completeness_floor():
    """A cached empty page reporting ``total=0`` must not excuse lost records."""
    pages = [
        _page([_rental("1"), _rental("2")], total=5),
        _page([_rental("3")], total=5),
        _page([], total=0),
    ]
    with (
        mock.patch("scrape.escalainmobiliaria.PAGE_SIZE", 2),
        mock.patch("scrape.escalainmobiliaria.fetch_json", side_effect=pages),
    ):
        with pytest.raises(RuntimeError, match="ended early"):
            scrape("medellin")


def test_empty_first_page_with_non_zero_total_is_inconsistent():
    with mock.patch(
        "scrape.escalainmobiliaria.fetch_json",
        side_effect=[_page([], total=571)],
    ):
        with pytest.raises(RuntimeError, match="empty page 0 while reporting total"):
            scrape("medellin")


def test_declared_upstream_failure_and_missing_payload_are_retried():
    """Live evidence: HTTP 200 carries an error/detail payload, no propiedades."""
    pages = [
        None,
        {
            "error": "No se pudieron cargar las propiedades",
            "detail": "The operation was aborted due to timeout",
        },
        _page([_rental("1")], total=1),
        _page([], total=1),
    ]
    with (
        mock.patch("scrape.escalainmobiliaria.fetch_json", side_effect=pages) as fetch,
        mock.patch("scrape.escalainmobiliaria._PAGE_RETRY_DELAY_SECONDS", 0),
    ):
        rows = scrape("medellin")

    assert [row["id"] for row in rows] == ["ESC-1"]
    assert fetch.call_count == 4


def test_persistent_page_failure_names_the_city_and_page():
    failure = {
        "error": "No se pudieron cargar las propiedades",
        "detail": "The operation was aborted due to timeout",
    }
    with (
        mock.patch(
            "scrape.escalainmobiliaria.fetch_json", return_value=failure
        ) as fetch,
        mock.patch("scrape.escalainmobiliaria._PAGE_RETRY_DELAY_SECONDS", 0),
    ):
        with pytest.raises(RuntimeError, match="city 496 page 0"):
            scrape("medellin")

    assert fetch.call_count == 3


def test_pagination_rejects_invalid_payloads():
    with pytest.raises(RuntimeError, match="invalid payload"):
        parse_search_response({"message": "Unauthorized", "total": 0}, "medellin")
    with pytest.raises(RuntimeError, match="valid total"):
        parse_search_response({"propiedades": []}, "medellin")
    with pytest.raises(RuntimeError, match="no JSON object"):
        parse_search_response(None, "medellin")


def test_sample_and_max_pages_bound_pagination_without_claiming_complete():
    pages = [_page([_rental("1"), _rental("2")], total=6)]
    with (
        mock.patch("scrape.escalainmobiliaria.PAGE_SIZE", 2),
        mock.patch("scrape.escalainmobiliaria.fetch_json", side_effect=pages) as fetch,
    ):
        assert [row["id"] for row in scrape("medellin", sample_only=True)] == [
            "ESC-1",
            "ESC-2",
        ]
    assert fetch.call_count == 1

    with (
        mock.patch("scrape.escalainmobiliaria.PAGE_SIZE", 2),
        mock.patch("scrape.escalainmobiliaria.fetch_json", side_effect=pages) as fetch,
    ):
        assert len(scrape("medellin", max_pages=1)) == 2
    assert fetch.call_count == 1

    with pytest.raises(ValueError):
        scrape("medellin", max_pages=0)


def test_scrape_cities_groups_requested_cities_and_fetches_each_once():
    urls: list[str] = []

    def fake_fetch(url):
        urls.append(url)
        return _page([], total=0)

    with mock.patch("scrape.escalainmobiliaria.fetch_json", side_effect=fake_fetch):
        result = scrape_cities(["Medellín", "medellin", "ITAGÜÍ", "la estrella"])

    assert list(result) == ["medellin", "itagui", "la-estrella"]
    assert result == {"medellin": [], "itagui": [], "la-estrella": []}
    assert len(urls) == 3
    assert any("ciudad=496" in url for url in urls)
    assert any("ciudad=389" in url for url in urls)
    assert any("ciudad=416" in url for url in urls)
    with pytest.raises(ValueError):
        scrape_cities(["bogota"])


def test_cli_canonicalizes_city_before_shared_writer_scope():
    row = parse_search_response(_page([_rental()]), "medellin")[0]
    args = argparse.Namespace(
        portal="escalainmobiliaria",
        output="both",
        ciudad="Itagüí",
        sample_only=True,
        max_pages=1,
        verbose=False,
    )

    with (
        mock.patch(
            "scrape.escalainmobiliaria.scrape", return_value=[row]
        ) as scrape_mock,
        mock.patch("sys.stdout", new_callable=io.StringIO),
    ):
        assert escalainmobiliaria_cli.main(args=args) == 0

    scrape_mock.assert_called_once_with(
        ciudad="itagui", sample_only=True, max_pages=1, verbose=False
    )
    assert args.ciudad == "itagui"
