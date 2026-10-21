"""City filters for the Google Sheets exporter mirror."""

import scripts.export_to_sheets as exporter


def _row(ciudad: str, **overrides) -> dict:
    row = {
        "id": f"P-{ciudad or 'none'}",
        "portal": "demo",
        "tipo": "apartamento",
        "precio": 1_500_000,
        "ciudad": ciudad,
        "status": "active",
    }
    row.update(overrides)
    return row


def _patch_rows(monkeypatch, rows: list[dict]) -> None:
    monkeypatch.setattr(exporter, "get_all", lambda: rows)


def test_cities_mirrors_several_municipalities(monkeypatch) -> None:
    _patch_rows(
        monkeypatch,
        [_row("medellin"), _row("envigado"), _row("bogota")],
    )

    rows = exporter.fetch_listings(cities=["medellin", "Envigado"])

    assert {row["ciudad"] for row in rows} == {"medellin", "envigado"}


def test_single_city_filter_still_works(monkeypatch) -> None:
    _patch_rows(monkeypatch, [_row("medellin"), _row("envigado")])

    rows = exporter.fetch_listings(city="Medellin")

    assert [row["ciudad"] for row in rows] == ["medellin"]


def test_cities_take_precedence_over_city(monkeypatch) -> None:
    _patch_rows(monkeypatch, [_row("medellin"), _row("sabaneta")])

    rows = exporter.fetch_listings(city="medellin", cities=["sabaneta"])

    assert [row["ciudad"] for row in rows] == ["sabaneta"]


def test_empty_city_rows_stay_out_of_a_city_scoped_mirror(monkeypatch) -> None:
    _patch_rows(monkeypatch, [_row("medellin"), _row("")])

    rows = exporter.fetch_listings(cities=["medellin", "envigado"])

    assert [row["ciudad"] for row in rows] == ["medellin"]


def test_inactive_rows_never_reach_the_mirror(monkeypatch) -> None:
    _patch_rows(
        monkeypatch,
        [_row("envigado"), _row("envigado", status="inactive")],
    )

    rows = exporter.fetch_listings(cities=["envigado"])

    assert len(rows) == 1
