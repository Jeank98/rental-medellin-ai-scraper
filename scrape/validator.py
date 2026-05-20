"""
Validates extracted and normalized listing dicts.
Checks for anomalies (out-of-range, suspicious) and enforces defaults.
Works WITH normalize.py — this module only validates already-converted values.
"""

STANDARD_TIPOS = {
    'apartamento', 'casa', 'apartaestudio', 'local',
    'oficina', 'bodega', 'lote', 'finca'
}


def validate(listing: dict) -> list[str]:
    """
    Takes a listing dict. Returns list of anomaly messages (empty if clean).
    Mutates the listing in-place for correctable fields.
    """
    warnings = []

    precio = listing.get('precio', 0)
    barrio = listing.get('barrio', '')
    estrato = listing.get('estrato', 0)
    parqueaderos = listing.get('parqueaderos', 0)
    habitaciones = listing.get('habitaciones', 0)
    banos = listing.get('banos', 0)
    area = listing.get('area', 0)
    tipo = listing.get('tipo', '')
    listing_id = listing.get('id', '')
    url = listing.get('url', '')

    # --- precio corrections ---
    if precio > 0 and precio < 100000:
        warnings.append(f"precio={precio} set to 0 (below floor)")
        listing['precio'] = 0
    elif precio > 50000000:
        warnings.append(f"precio={precio} unusually high")

    # --- barrio corrections and flags ---
    if barrio:
        if 'código:' in barrio.lower() or 'codigo:' in barrio.lower():
            segments = barrio.split()
            salvaged = segments[0] if segments else ''
            warnings.append(f"barrio='{barrio}' salvaged to first segment")
            listing['barrio'] = salvaged
        # Note: empty barrio intentionally NOT flagged — valid minimal listing

    # --- flags only (no mutation) ---
    if estrato == 8:
        warnings.append(f"estrato={estrato} = 8 (commercial?)")
    elif estrato > 6:
        warnings.append(f"estrato={estrato} > 6 (source data error)")

    if parqueaderos > 10:
        warnings.append(f"parqueaderos={parqueaderos} > 10 (anomaly)")

    if habitaciones > 30:
        warnings.append(f"habitaciones={habitaciones} suspiciously high")

    if banos > 20:
        warnings.append(f"banos={banos} suspiciously high")

    if area > 10000:
        warnings.append(f"area={area} suspiciously high")

    if tipo.lower() not in STANDARD_TIPOS and tipo != '':
        warnings.append(f"tipo='{tipo}' non-standard")

    if listing_id:
        parts = listing_id.split('-', 1)
        if len(parts) != 2 or not parts[1].isdigit():
            warnings.append(f"id='{listing_id}' invalid format (expected XXX-NNNN)")

    if url and not url.startswith(('http://', 'https://')):
        warnings.append(f"url='{url}' invalid format")

    return warnings


if __name__ == '__main__':
    # Test 1: precio below floor -> corrected to 0
    listing = {
        'precio': 50000, 'area': 60, 'habitaciones': 2, 'banos': 1,
        'parqueaderos': 0, 'estrato': 3, 'barrio': 'Belen',
        'tipo': 'apartamento', 'id': 'MXB-123', 'portal': 'maxibienes',
        'url': 'https://...'
    }
    warnings = validate(listing)
    assert listing['precio'] == 0
    assert 'set to 0 (below floor)' in warnings[0]

    # Test 2: estrato > 6 flagged but NOT mutated
    listing = {
        'precio': 500000, 'area': 60, 'habitaciones': 2, 'banos': 1,
        'parqueaderos': 0, 'estrato': 7, 'barrio': 'Belen',
        'tipo': 'apartamento', 'id': 'MXB-124', 'portal': 'maxibienes',
        'url': 'https://...'
    }
    warnings = validate(listing)
    assert listing['estrato'] == 7
    assert any('> 6' in w for w in warnings)

    # Test 3: parqueaderos > 10 flagged
    listing = {
        'precio': 500000, 'area': 60, 'habitaciones': 2, 'banos': 1,
        'parqueaderos': 35, 'estrato': 3, 'barrio': 'Belen',
        'tipo': 'apartamento', 'id': 'MXB-125', 'portal': 'maxibienes',
        'url': 'https://...'
    }
    warnings = validate(listing)
    assert listing['parqueaderos'] == 35
    assert any('> 10' in w for w in warnings)

    # Test 4: clean listing -> no warnings
    listing = {
        'precio': 0, 'area': 0, 'habitaciones': 0, 'banos': 0,
        'parqueaderos': 0, 'estrato': 0, 'barrio': '', 'tipo': '',
        'id': '', 'portal': '', 'url': ''
    }
    warnings = validate(listing)
    assert warnings == []

    print("All validator tests passed!")
