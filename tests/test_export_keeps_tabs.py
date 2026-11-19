"""The data export must not delete the analysis tabs.

Resumen, Barrios and Mi búsqueda hold formulas over the data tab; the export
used to delete every sheet beyond the first, which would wipe them on each run.
"""

from pathlib import Path

EXPORT = Path("scripts/export_to_sheets.py")
REPORTS = Path("scripts/build_sheet_reports.py")


def test_export_never_deletes_sheets() -> None:
    source = EXPORT.read_text(encoding="utf-8")

    assert "deleteSheet" not in source
    assert "DATA_TAB" in source


def test_reports_script_exists_and_targets_the_data_tab() -> None:
    source = REPORTS.read_text(encoding="utf-8")

    assert 'DATA_TAB' in source
    for tab in ("Resumen", "Barrios"):
        assert tab in source
    assert "Mi búsqueda" not in source


def test_reports_formulas_use_the_spreadsheet_locale_separator() -> None:
    """Locale is es_ES, where ',' inside a formula is a parse error."""
    source = REPORTS.read_text(encoding="utf-8")

    assert "COUNTIFS({DATA_TAB}!$L$2:$L;{ref})" in source
