"""Shared normalization functions for Colombian real estate rental listings.

Every field normalizer takes a raw value (string, int, or None) and returns
the standardized type: int for numeric fields, str for text fields.
"""

TIPO_MAPPING = {
    # Spanish
    'apartamento': 'apartamento',
    'apto': 'apartamento',
    'departamento': 'apartamento',
    'casa': 'casa',
    'apartaestudio': 'apartaestudio',
    'local': 'local',
    'comercial': 'local',
    'oficina': 'oficina',
    'bodega': 'bodega',
    'lote': 'lote',
    'terreno': 'lote',
    'finca': 'finca',
    'hacienda': 'finca',
    # English
    'apartment': 'apartamento',
    'department': 'apartamento',
    'house': 'casa',
    'studio': 'apartaestudio',
    'commercial': 'local',
    'office': 'oficina',
    'warehouse': 'bodega',
    'lot': 'lote',
    'farm': 'finca',
}

_GARAJE_TEXTO = {
    'si': 1,
    'si.': 1,
    'sí': 1,
    'cubierto': 1,
    'semicubierto': 1,
    'zona de parqueo': 1,
    'descubierto': 1,
    'doble': 2,
    'doble en paralelo': 2,
    'doble lineal': 2,
    'no': 0,
    'no.': 0,
    'sin garaje': 0,
    'sin': 0,
    '': 0,
}

_ESTRATO_ROMAN = {
    'i': 1,
    'ii': 2,
    'iii': 3,
    'iv': 4,
    'v': 5,
    'vi': 6,
}


def normalize_price(raw) -> int:
    if raw is None:
        return 0
    s = str(raw).strip()
    if not s:
        return 0
    if 'consultar precio' in s.lower():
        return 0
    first = s.split('/')[0].strip()
    digits = ''.join(c for c in first if c.isdecimal())
    if not digits:
        return 0
    return int(digits)


def normalize_tipo(raw) -> str:
    if not raw:
        return ''
    s = str(raw).strip()
    lower = s.lower()
    if lower in TIPO_MAPPING:
        return TIPO_MAPPING[lower]
    if '-' in s:
        first = s.split('-')[0].strip().lower()
        if first in TIPO_MAPPING:
            return TIPO_MAPPING[first]
        return first
    return s.lower()


def normalize_estrato(raw) -> int:
    if raw is None:
        return 0
    if isinstance(raw, int):
        if raw == 8:
            return 0
        return raw
    s = str(raw).strip()
    if not s:
        return 0
    lower = s.lower()
    if lower in _ESTRATO_ROMAN:
        return _ESTRATO_ROMAN[lower]
    if lower in ('comercial', 'commercial'):
        return 0
    if s.isdigit():
        v = int(s)
        if v == 8:
            return 0
        return v
    return 0


def normalize_garaje(raw) -> int:
    if raw is None:
        return 0
    if isinstance(raw, int):
        return raw
    s = str(raw).strip()
    lower = s.lower()
    if lower in _GARAJE_TEXTO:
        return _GARAJE_TEXTO[lower]
    if s.isdigit():
        return int(s)
    return 0


def normalize_barrio(raw) -> str:
    if not raw:
        return ''
    s = str(raw).strip()
    if s.lower().startswith('barrio:'):
        s = s[len('barrio:'):].strip()
    if ' - ' in s:
        s = s.rsplit(' - ', 1)[-1]
    if ',' in s:
        s = s.rsplit(',', 1)[-1].strip()
    return s.title().strip()


def normalize_url(raw, base_url='') -> str:
    if not raw:
        return ''
    s = str(raw).strip()
    if s.startswith('/') and base_url:
        return base_url.rstrip('/') + '/' + s.lstrip('/')
    return s


if __name__ == '__main__':
    assert normalize_price('$ 1.450.000') == 1450000
    assert normalize_price('$1,600,000') == 1600000
    assert normalize_price('Consultar precio') == 0
    assert normalize_price('$800.000 / $1.200.000') == 800000
    assert normalize_price('$5.400.000') == 5400000
    assert normalize_tipo('APARTAMENTO') == 'apartamento'
    assert normalize_tipo('Casa-Local') == 'casa'
    assert normalize_tipo('Department') == 'apartamento'
    assert normalize_tipo('ApartaEstudio') == 'apartaestudio'
    assert normalize_estrato('V') == 5
    assert normalize_estrato('IV') == 4
    assert normalize_estrato('Comercial') == 0
    assert normalize_estrato(3) == 3
    assert normalize_estrato(8) == 0
    assert normalize_garaje('Cubierto') == 1
    assert normalize_garaje('Doble en paralelo') == 2
    assert normalize_garaje('No') == 0
    assert normalize_garaje('Zona de parqueo') == 1
    assert normalize_barrio('Barrio: Loreto') == 'Loreto'
    assert normalize_barrio('MEDELLIN - BELEN') == 'Belen'
    assert normalize_barrio('EL POBLADO') == 'El Poblado'
    print("All normalization tests passed!")
