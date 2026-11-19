#!/usr/bin/env python3
"""Build the analysis tabs of the shared spreadsheet.

Creates two tabs next to the data tab (``Inmuebles``):

- ``Resumen``: per-city counts, median/P25/P75 rent and median price per m²,
  plus two bar charts.
- ``Barrios``: the busiest neighbourhoods ranked by median price per m², with
  a flag for the ones we consider attractive and the share with parking.

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
ATTRACTIVE = {
    "laureles", "estadio", "suramericana", "calasanz", "la america", "floresta",
    "belen", "cristobal", "las vegas", "jardines", "el portal", "cumbres",
    "lomas del escobero", "prados de sabaneta", "aves maria", "las lomitas",
    "suramerica", "ditaires", "la aldea", "toledo",
}
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


def _barrio_counts(service, spreadsheet_id: str) -> list[tuple[str, int]]:
    """Neighbourhoods with enough listings, most listed first."""
    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{DATA_TAB}!J2:J",
    ).execute().get("values", [])
    counts: dict[str, int] = {}
    for row in values:
        name = (row[0] if row else "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [item for item in ranked if item[1] >= MIN_LISTINGS][:TOP_BARRIOS]


# The spreadsheet locale is es_ES, so argument separators are ';'.
SEP = ";"


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


def build_barrios(service, spreadsheet_id: str, barrios: list[tuple[str, int]]) -> None:
    header = ["barrio", "avisos", "precio mediano", "m² mediano", "$/m² mediano",
              "atractivo", "con parqueadero"]
    rows: list[list[str]] = [["Barrios con más avisos, ordenados por $/m² mediano"], header]

    for name, _count in barrios:
        ref = f"$A{len(rows) + 1}"
        rows.append([
            name,
            f'=COUNTIFS({DATA_TAB}!$J$2:$J;{ref})',
            _median_formula(ref, "D", "J"),
            _median_formula(ref, "E", "J"),
            f'=ARRAYFORMULA(IF({ref}="";"";IFERROR(MEDIAN(IF(({DATA_TAB}!$J$2:$J={ref})*({DATA_TAB}!$E$2:$E>0);'
            f'{DATA_TAB}!$D$2:$D/{DATA_TAB}!$E$2:$E));"")))',
            "sí" if name.strip().casefold() in ATTRACTIVE else "",
            f'=IFERROR(COUNTIFS({DATA_TAB}!$J$2:$J;{ref};{DATA_TAB}!$H$2:$H;">0")/COUNTIFS({DATA_TAB}!$J$2:$J;{ref});"")',
        ])

    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range="Barrios!A1:G300"
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Barrios!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def build_busqueda(service, spreadsheet_id: str) -> None:
    """A parameterised view: the filters the owner actually uses."""
    rows = [
        ["Mi búsqueda", ""],
        ["ciudad", "medellin"],
        ["precio máximo", 4000000],
        ["habitaciones mínimas", 3],
        ["m² mínimos", 70],
        ["con parqueadero", "no"],
        [],
        ["Resultados: se actualizan al cambiar los parámetros"],
        ["id", "portal", "tipo", "precio", "m²", "hab", "baños", "parqueadero",
         "estrato", "barrio", "url", "ciudad", "status", "fecha"],
        ['=IFERROR(SORT(FILTER({t}!A2:N;({t}!L2:L=B2)*({t}!D2:D<=B3)*({t}!F2:F>=B4)*({t}!E2:E>=B5)*'
         'IF(B6="sí";{t}!H2:H>0;{t}!A2:A<>""));4;FALSE);"sin resultados")'.format(t=DATA_TAB)],
    ]
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range="Mi búsqueda!A1:N40"
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Mi búsqueda!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def apply_number_formats(service, spreadsheet_id: str, resumen_id: int, barrios_id: int) -> None:
    money = {"type": "NUMBER", "pattern": '"$"#,##0'}
    per_m2 = {"type": "NUMBER", "pattern": '"$"#,##0'}
    percent = {"type": "PERCENT", "pattern": "0%"}
    requests = [
        {"repeatCell": {
            "range": {"sheetId": resumen_id, "startRowIndex": 1, "endRowIndex": 7,
                      "startColumnIndex": 2, "endColumnIndex": 5},
            "cell": {"userEnteredFormat": {"numberFormat": money}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {
            "range": {"sheetId": resumen_id, "startRowIndex": 1, "endRowIndex": 7,
                      "startColumnIndex": 6, "endColumnIndex": 7},
            "cell": {"userEnteredFormat": {"numberFormat": per_m2}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {
            "range": {"sheetId": resumen_id, "startRowIndex": 1, "endRowIndex": 7,
                      "startColumnIndex": 7, "endColumnIndex": 8},
            "cell": {"userEnteredFormat": {"numberFormat": percent}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {
            "range": {"sheetId": barrios_id, "startRowIndex": 1, "endRowIndex": 300,
                      "startColumnIndex": 2, "endColumnIndex": 4},
            "cell": {"userEnteredFormat": {"numberFormat": money}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {
            "range": {"sheetId": barrios_id, "startRowIndex": 1, "endRowIndex": 300,
                      "startColumnIndex": 4, "endColumnIndex": 5},
            "cell": {"userEnteredFormat": {"numberFormat": per_m2}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {
            "range": {"sheetId": barrios_id, "startRowIndex": 1, "endRowIndex": 300,
                      "startColumnIndex": 6, "endColumnIndex": 7},
            "cell": {"userEnteredFormat": {"numberFormat": percent}}, "fields": "userEnteredFormat.numberFormat"}},
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()


def build_charts(service, spreadsheet_id: str, resumen_id: int, barrios_id: int) -> None:
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
            "position": {"overlayPosition": {"anchorCell": {
                "sheetId": resumen_id, "rowIndex": 9, "columnIndex": 0}}},
        }}},
        {"addChart": {"chart": {
            "spec": {
                "title": "Precio por m² mediano — barrios con más avisos",
                "basicChart": {
                    "chartType": "BAR",
                    "legendPosition": "NO_LEGEND",
                    "domains": [{"domain": {"sourceRange": {"sources": [{
                        "sheetId": barrios_id, "startRowIndex": 1, "endRowIndex": 6,
                        "startColumnIndex": 0, "endColumnIndex": 1}]}}}],
                    "series": [{"series": {"sourceRange": {"sources": [{
                        "sheetId": barrios_id, "startRowIndex": 1, "endRowIndex": 6,
                        "startColumnIndex": 4, "endColumnIndex": 5}]}}}],
                },
            },
            "position": {"overlayPosition": {"anchorCell": {
                "sheetId": barrios_id, "rowIndex": 9, "columnIndex": 8}}},
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
    _ensure_sheet(service, spreadsheet_id, "Mi búsqueda")

    build_summary(service, spreadsheet_id)
    barrios = _barrio_counts(service, spreadsheet_id)
    build_barrios(service, spreadsheet_id, barrios)
    build_busqueda(service, spreadsheet_id)
    apply_number_formats(service, spreadsheet_id, resumen_id, barrios_id)
    if not args.no_charts:
        build_charts(service, spreadsheet_id, resumen_id, barrios_id)

    print(f"Resumen y Barrios actualizados · {len(barrios)} barrios con ≥{MIN_LISTINGS} avisos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
