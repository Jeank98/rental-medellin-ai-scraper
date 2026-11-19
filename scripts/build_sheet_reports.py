#!/usr/bin/env python3
"""Build the analysis tabs of the shared spreadsheet.

Creates two tabs next to the data tab (``Inmuebles``):

- ``Resumen``: per-city counts, median/P25/P75 rent and median price per m²,
  plus two bar charts.
- ``Barrios``: the busiest neighbourhoods ranked by median price per m², with
  a flag for the ones we consider attractive and the share with parking.

The data tab already carries sheet filters, so there is no separate "search"
view: filtering happens there.

The tabs hold formulas that read the data tab, so a refresh only needs this
script to be run again when the neighbourhood list changes. Nothing here writes
to the database.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from export_to_sheets import DATA_TAB, build_sheets_service

CITIES = ["medellin", "envigado", "itagui", "sabaneta", "la-estrella"]
MIN_LISTINGS = 10
TOP_BARRIOS = 40


def _ensure_sheet(service, spreadsheet_id: str, title: str) -> int:
    """Return the sheetId of ``title``, creating the tab when missing."""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in meta["sheets"]:
        if sheet["properties"]["title"] == title:
            return sheet["properties"]["sheetId"]

    response = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    return response["replies"][0]["addSheet"]["properties"]["sheetId"]


def _barrio_groups(service, spreadsheet_id: str) -> list[dict]:
    """Group listings by (city, normalized barrio), like the data tab does.

    The data tab carries ``barrio_norm`` in column O, so "El Poblado", "POBLADO"
    and "Barrio Poblado" collapse into one row and the same name in two cities
    stays separate.
    """
    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{DATA_TAB}!J2:O",
    ).execute().get("values", [])

    groups: dict[tuple[str, str], dict] = {}
    for row in values:
        raw_barrio = (row[0] if row else "").strip()
        city = (row[2] if len(row) > 2 else "").strip().casefold()
        key_barrio = (row[5] if len(row) > 5 else "").strip() or raw_barrio.casefold()
        if not raw_barrio or not city:
            continue
        group = groups.setdefault(
            (city, key_barrio), {"count": 0, "names": {}, "city": city}
        )
        group["count"] += 1
        group["names"][raw_barrio] = group["names"].get(raw_barrio, 0) + 1

    ranked = sorted(groups.items(), key=lambda item: item[1]["count"], reverse=True)
    result = []
    for (city, key_barrio), group in ranked:
        if group["count"] < MIN_LISTINGS:
            continue
        display = max(group["names"].items(), key=lambda item: item[1])[0]
        result.append(
            {"ciudad": city, "barrio": display, "key": key_barrio, "avisos": group["count"]},
        )
        if len(result) >= TOP_BARRIOS:
            break
    return result


# The spreadsheet locale is es_ES, so argument separators are ';'.
def _median_formula(ref: str, value_column: str, key_column: str = "L") -> str:
    return (
        f"=ARRAYFORMULA(IF({ref}=\"\";\"\";IFERROR(MEDIAN(IF("
        f"{DATA_TAB}!${key_column}$2:${key_column}={ref};"
        f"{DATA_TAB}!${value_column}$2:${value_column}));\"\")))"
    )


def build_summary(service, spreadsheet_id: str) -> None:
    header = ["ciudad", "avisos", "precio P25", "precio mediano", "precio P75",
              "m² mediano", "$/m² mediano", "con parqueadero"]
    rows: list[list[str]] = [["Arriendos por ciudad y tipo de cambio de precio"], header]

    for city in CITIES:
        ref = f"$A{len(rows) + 1}"
        rows.append([
            city,
            f'=COUNTIFS({DATA_TAB}!$L$2:$L;{ref})',
            f'=ARRAYFORMULA(IF({ref}="";"";IFERROR(PERCENTILE(IF({DATA_TAB}!$L$2:$L={ref};{DATA_TAB}!$D$2:$D);0,25);"")))',
            _median_formula(ref, "D"),
            f'=ARRAYFORMULA(IF({ref}="";"";IFERROR(PERCENTILE(IF({DATA_TAB}!$L$2:$L={ref};{DATA_TAB}!$D$2:$D);0,75);"")))',
            f'=ARRAYFORMULA(IF({ref}="";"";IFERROR(MEDIAN(IF({DATA_TAB}!$L$2:$L={ref};{DATA_TAB}!$E$2:$E));"")))',
            f'=ARRAYFORMULA(IF({ref}="";"";IFERROR(MEDIAN(IF(({DATA_TAB}!$L$2:$L={ref})*({DATA_TAB}!$E$2:$E>0);'
            f'{DATA_TAB}!$D$2:$D/{DATA_TAB}!$E$2:$E));"")))',
            f'=IFERROR(COUNTIFS({DATA_TAB}!$L$2:$L;{ref};{DATA_TAB}!$H$2:$H;">0")/COUNTIFS({DATA_TAB}!$L$2:$L;{ref});"")',
        ])

    rows.append([])
    rows.append(["Fuente: pestaña Inmuebles. P25/P75 = cuartiles de precio; $/m² mediano evita que un "
                 "inmueble atípico distorsione la comparación entre barrios."])

    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range="Resumen!A1:H60"
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Resumen!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def build_barrios(service, spreadsheet_id: str, barrios: list[dict]) -> None:
    header = ["ciudad", "barrio", "avisos", "precio mediano", "m² mediano",
              "$/m² mediano", "estrato mediano", "atractivo", "con parqueadero", "clave"]
    rows: list[list[str]] = [
        ["Barrios con más avisos por ciudad, normalizados; atractivo = estrato mediano ≥ 4"],
        header,
    ]

    def two_keys(ref_row: int) -> str:
        return (f"({DATA_TAB}!$L$2:$L=$A{ref_row})*({DATA_TAB}!$O$2:$O=$J{ref_row})")

    for item in barrios:
        row_number = len(rows) + 1
        keys = two_keys(row_number)
        rows.append([
            item["ciudad"],
            item["barrio"],
            f'=COUNTIFS({DATA_TAB}!$L$2:$L;$A{row_number};{DATA_TAB}!$O$2:$O;$J{row_number})',
            f'=ARRAYFORMULA(IF($C{row_number}="";"";IFERROR(MEDIAN(IF({keys};{DATA_TAB}!$D$2:$D));"")))',
            f'=ARRAYFORMULA(IF($C{row_number}="";"";IFERROR(MEDIAN(IF({keys}*({DATA_TAB}!$E$2:$E>0);'
            f'{DATA_TAB}!$E$2:$E));"")))',
            f'=ARRAYFORMULA(IF($C{row_number}="";"";IFERROR(MEDIAN(IF({keys}*({DATA_TAB}!$E$2:$E>0);'
            f'{DATA_TAB}!$D$2:$D/{DATA_TAB}!$E$2:$E));"")))',
            f'=ARRAYFORMULA(IF($C{row_number}="";"";IFERROR(MEDIAN(IF({keys}*({DATA_TAB}!$I$2:$I>0);'
            f'{DATA_TAB}!$I$2:$I));"")))',
            f'=IF($G{row_number}="";"";IF($G{row_number}>=4;"sí";"no"))',
            f'=IFERROR(COUNTIFS({DATA_TAB}!$L$2:$L;$A{row_number};{DATA_TAB}!$O$2:$O;$J{row_number};'
            f'{DATA_TAB}!$H$2:$H;">0")/$C{row_number};"")',
            item["key"],
        ])

    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range="Barrios!A1:J300"
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Barrios!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def apply_number_formats(service, spreadsheet_id: str, resumen_id: int, barrios_id: int) -> None:
    """Explicit per-column formats: cell formats survive a value rewrite."""
    money = {"type": "NUMBER", "pattern": '"$"#,##0'}
    integer = {"type": "NUMBER", "pattern": "0"}
    percent = {"type": "PERCENT", "pattern": "0%"}

    def rule(sheet_id: int, column: int, number_format: dict) -> dict:
        return {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 300,
                      "startColumnIndex": column, "endColumnIndex": column + 1},
            "cell": {"userEnteredFormat": {"numberFormat": number_format}},
            "fields": "userEnteredFormat.numberFormat"}}

    requests = [
        # Resumen: ciudad | avisos | P25 | mediana | P75 | m² | $/m² | % parqueadero
        rule(resumen_id, 1, integer),
        rule(resumen_id, 2, money),
        rule(resumen_id, 3, money),
        rule(resumen_id, 4, money),
        rule(resumen_id, 5, integer),
        rule(resumen_id, 6, money),
        rule(resumen_id, 7, percent),
        # Barrios: ciudad | barrio | avisos | precio | m² | $/m² | estrato | atractivo | % parqueadero
        rule(barrios_id, 2, integer),
        rule(barrios_id, 3, money),
        rule(barrios_id, 4, integer),
        rule(barrios_id, 5, money),
        rule(barrios_id, 6, integer),
        rule(barrios_id, 8, percent),
        {"updateDimensionProperties": {
            "range": {"sheetId": barrios_id, "dimension": "COLUMNS",
                      "startIndex": 9, "endIndex": 10},
            "properties": {"hiddenByUser": True},
            "fields": "hiddenByUser"}},
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()


def build_charts(
    service, spreadsheet_id: str, resumen_id: int, barrios_id: int, barrios_rows: int
) -> None:
    """Two bar charts: median rent by city and median $/m² for the top barrios."""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    stale = [
        {"deleteEmbeddedObject": {"objectId": chart["chartId"]}}
        for sheet in meta["sheets"]
        if sheet["properties"]["sheetId"] in (resumen_id, barrios_id)
        for chart in sheet.get("charts", [])
    ]
    if stale:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": stale}
        ).execute()

    requests = [
        {"addChart": {"chart": {
            "spec": {
                "title": "Precio mediano de arriendo por ciudad",
                "basicChart": {
                    "chartType": "COLUMN",
                    "legendPosition": "NO_LEGEND",
                    "domains": [{"domain": {"sourceRange": {"sources": [{
                        "sheetId": resumen_id, "startRowIndex": 1, "endRowIndex": 6,
                        "startColumnIndex": 0, "endColumnIndex": 1}]}}}],
                    "series": [{"series": {"sourceRange": {"sources": [{
                        "sheetId": resumen_id, "startRowIndex": 1, "endRowIndex": 6,
                        "startColumnIndex": 3, "endColumnIndex": 4}]}}}],
                },
            },
            "position": {"overlayPosition": {
                "anchorCell": {"sheetId": resumen_id, "rowIndex": 12, "columnIndex": 0},
                "widthPixels": 640, "heightPixels": 380}},
        }}},
        {"addChart": {"chart": {
            "spec": {
                "title": "Precio por m² mediano — barrios con más avisos",
                "basicChart": {
                    "chartType": "BAR",
                    "legendPosition": "NO_LEGEND",
                    "domains": [{"domain": {"sourceRange": {"sources": [{
                        "sheetId": barrios_id, "startRowIndex": 1,
                        "endRowIndex": min(11, barrios_rows),
                        "startColumnIndex": 1, "endColumnIndex": 2}]}}}],
                    "series": [{"series": {"sourceRange": {"sources": [{
                        "sheetId": barrios_id, "startRowIndex": 1,
                        "endRowIndex": min(11, barrios_rows),
                        "startColumnIndex": 5, "endColumnIndex": 6}]}}}],
                },
            },
            "position": {"overlayPosition": {
                "anchorCell": {"sheetId": barrios_id,
                               "rowIndex": barrios_rows + 3, "columnIndex": 0},
                "widthPixels": 640, "heightPixels": 380}},
        }}},
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-charts", action="store_true", help="Skip chart creation")
    args = parser.parse_args()

    load_dotenv(".env")
    spreadsheet_id = os.environ["GOOGLE_SHEET_ID"]
    service = build_sheets_service()

    resumen_id = _ensure_sheet(service, spreadsheet_id, "Resumen")
    barrios_id = _ensure_sheet(service, spreadsheet_id, "Barrios")

    build_summary(service, spreadsheet_id)
    barrios = _barrio_groups(service, spreadsheet_id)
    build_barrios(service, spreadsheet_id, barrios)
    apply_number_formats(service, spreadsheet_id, resumen_id, barrios_id)
    if not args.no_charts:
        build_charts(service, spreadsheet_id, resumen_id, barrios_id, len(barrios) + 2)

    print(f"Resumen y Barrios actualizados · {len(barrios)} barrios con ≥{MIN_LISTINGS} avisos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
