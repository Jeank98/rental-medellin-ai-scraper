#!/usr/bin/env python
"""Contrasta las pestañas de análisis contra un cálculo independiente.

Lee la pestaña de datos, agrupa por (ciudad, barrio normalizado) en Python y
compara avisos, medianas y porcentajes con lo que muestra la hoja. Así se
detectan fórmulas mal referenciadas o columnas desalineadas.
"""

from __future__ import annotations

import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, "scripts")

from dotenv import load_dotenv

from export_to_sheets import build_sheets_service

DATA_TAB = "Inmuebles"
MIN_LISTINGS = 10


def numbers(values: list[float]) -> list[float]:
    return [value for value in values if value and value > 0]


def main() -> int:
    load_dotenv(".env")
    service = build_sheets_service()
    spreadsheet_id = os.environ["GOOGLE_SHEET_ID"]

    rows = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{DATA_TAB}!A2:O",
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute().get("values", [])

    groups: dict[tuple[str, str], list[list]] = defaultdict(list)
    for row in rows:
        def cell(index: int):
            return row[index] if len(row) > index else ""

        city = str(cell(11) or "").strip().casefold()
        key = str(cell(14) or "").strip() or str(cell(9) or "").strip().casefold()
        if city and key:
            groups[(city, key)].append(row)

    expected = {}
    for (city, key), items in groups.items():
        if len(items) < MIN_LISTINGS:
            continue
        prices = numbers([float(i[3]) for i in items if len(i) > 3 and i[3] not in ("", None)])
        areas = numbers([float(i[4]) for i in items if len(i) > 4 and i[4] not in ("", None)])
        ratios = [
            price / area
            for price, area in zip(
                [float(i[3]) for i in items if len(i) > 4 and i[3] not in ("", None) and i[4] not in ("", None)],
                [float(i[4]) for i in items if len(i) > 4 and i[3] not in ("", None) and i[4] not in ("", None)],
            )
            if area > 0
        ]
        estratos = numbers([
            float(i[8]) for i in items
            if len(i) > 8 and i[8] not in ("", None) and 1 <= float(i[8]) <= 6
        ])
        parking = sum(
            1 for i in items if len(i) > 7 and i[7] not in ("", None) and float(i[7]) > 0
        )
        expected[(city, key)] = {
            "avisos": len(items),
            "precio": statistics.median(prices) if prices else None,
            "area": statistics.median(areas) if areas else None,
            "ratio": statistics.median(ratios) if ratios else None,
            "estrato": statistics.median(estratos) if estratos else None,
            "parking": parking / len(items),
        }

    sheet = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range="Barrios!A3:J", valueRenderOption="UNFORMATTED_VALUE"
    ).execute().get("values", [])

    problems = 0
    checked = 0
    for row in sheet:
        if len(row) < 10:
            continue
        city = str(row[0]).strip().casefold()
        key = str(row[9]).strip()
        got = {
            "avisos": row[2],
            "precio": row[3] if len(row) > 3 else None,
            "area": row[4] if len(row) > 4 else None,
            "ratio": row[5] if len(row) > 5 else None,
            "estrato": row[6] if len(row) > 6 else None,
            "parking": row[8] if len(row) > 8 else None,
        }
        want = expected.get((city, key))
        if not want:
            print(f"FALTA en el cálculo: {city}/{key}")
            problems += 1
            continue
        checked += 1
        for field, tolerance in (
            ("avisos", 0), ("precio", 1), ("area", 0.01), ("ratio", 2),
            ("estrato", 0.01), ("parking", 0.01),
        ):
            a, b = got[field], want[field]
            if a in ("", None) or b is None:
                if (a in ("", None)) != (b is None):
                    print(f"  {city}/{key} {field}: hoja={a!r} esperado={b!r}")
                    problems += 1
                continue
            if abs(float(a) - float(b)) > tolerance:
                print(f"  {city}/{key} {field}: hoja={a!r} esperado={round(float(b), 2)!r}")
                problems += 1

    # Resumen: una fila por ciudad con cuartiles.
    totals: dict[str, list[list]] = defaultdict(list)
    for row in rows:
        city = str(row[11] if len(row) > 11 else "").strip().casefold()
        if city:
            totals[city].append(row)

    summary = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range="Resumen!A3:H", valueRenderOption="UNFORMATTED_VALUE"
    ).execute().get("values", [])
    for row in summary:
        if len(row) < 8:
            continue
        city = str(row[0]).strip().casefold()
        items = totals.get(city, [])
        prices = sorted(numbers([float(i[3]) for i in items if len(i) > 3 and i[3] not in ("", None)]))
        areas = numbers([float(i[4]) for i in items if len(i) > 4 and i[4] not in ("", None)])
        ratios = sorted(
            min(9_999_999, max(0, float(i[3]) / float(i[4])))
            for i in items
            if len(i) > 4 and i[3] not in ("", None) and i[4] not in ("", None) and float(i[4]) > 0
        )
        parking = sum(1 for i in items if len(i) > 7 and i[7] not in ("", None) and float(i[7]) > 0)
        checked += 1
        want = {
            "avisos": len(items),
            "p25": statistics.quantiles(prices, n=4)[0] if len(prices) > 3 else None,
            "mediana": statistics.median(prices) if prices else None,
            "p75": statistics.quantiles(prices, n=4)[2] if len(prices) > 3 else None,
            "area": statistics.median(areas) if areas else None,
            "ratio": statistics.median(ratios) if ratios else None,
            "parking": parking / len(items) if items else None,
        }
        got = {"avisos": row[1], "p25": row[2], "mediana": row[3], "p75": row[4],
               "area": row[5], "ratio": row[6], "parking": row[7]}
        for field in want:
            a, b = got[field], want[field]
            if a in ("", None) or b is None:
                continue
            # Google's QUARTILE interpolates slightly differently than Python's
            # statistics.quantiles, so percentiles get a 1% tolerance.
            tolerance = {"parking": 0.02, "p25": 0.01, "p75": 0.01}.get(field, 2)
            limit = tolerance if tolerance >= 1 else tolerance * abs(float(b))
            if abs(float(a) - float(b)) > limit:
                print(f"  Resumen {city} {field}: hoja={a!r} esperado={round(float(b), 1)!r}")
                problems += 1

    print(f"filas contrastadas: {checked} · discrepancias: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
