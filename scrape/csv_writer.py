import csv
import os

COLUMNS = [
    'id', 'portal', 'tipo', 'precio', 'area',
    'habitaciones', 'banos', 'parqueaderos', 'estrato',
    'barrio', 'url'
]

NUMERIC_COLS = {'precio', 'area', 'habitaciones', 'banos', 'parqueaderos', 'estrato'}

INVALID_MARKERS = {'N/A', 'null', 'None', '-1', 'nan', 'NA', 'n/a', 'none'}


def _sanitize_value(key, value):
    if value is None:
        return 0 if key in NUMERIC_COLS else ''
    if isinstance(value, str) and value.strip() in INVALID_MARKERS:
        return 0 if key in NUMERIC_COLS else ''
    if key in NUMERIC_COLS:
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0
    return '' if value == '' else str(value)


def write_to_csv(rows, portal, ciudad='medellin'):
    os.makedirs('results', exist_ok=True)
    filename = f'results/{portal}_arriendos_{ciudad}.csv'

    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        csv.writer(f).writerow(COLUMNS)
        writer = csv.DictWriter(f, fieldnames=COLUMNS,
                                quoting=csv.QUOTE_NONNUMERIC)
        for row in rows:
            sanitized = {
                col: _sanitize_value(col, row.get(col)) for col in COLUMNS
            }
            writer.writerow(sanitized)

    return os.path.abspath(filename)
