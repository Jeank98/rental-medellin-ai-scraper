"""Deterministic regression tests for the Arrendamientos Envigado scraper."""

import argparse
from unittest import mock

import pytest
from bs4 import BeautifulSoup

from scrape import arrendamientosenvigado as aev

BASE = "https://arrendamientosenvigadosa.com.co"


def _sitemap(*paths: str) -> str:
    entries = "".join(f"<url><loc>{BASE}{path}</loc></url>" for path in paths)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}</urlset>"
    )


def _sitemap_index(*paths: str) -> str:
    entries = "".join(f"<sitemap><loc>{BASE}{path}</loc></sitemap>" for path in paths)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}</sitemapindex>"
    )


def _slug(
    tipo: str, city: str, barrio: str, code: str, operacion: str = "arriendo"
) -> str:
    return f"{tipo}-{operacion}-{city}-{barrio}-{code}"


def _detail_html(
    *,
    code: str,
    slug: str | None = None,
    h1: str = "Apartamento en arriendo en Envigado, El Portal",
    title: str = "Apartamento en arriendo en Envigado, El Portal",
    location: str = "Envigado, El Portal",
    precio: str = "$ 2.100.000",
    area: str = "55 m²",
    habitaciones: str = "1",
    banos: str = "1",
    parqueadero: str | None = None,
    estrato: str = "4",
    include_price: bool = True,
    include_code: bool = True,
    extra: str = "",
) -> str:
    canonical = (
        f"{BASE}/inmueble/{slug or _slug('apartamento', 'envigado', 'el-portal', code)}"
    )
    specs = [
        ("Área construida", area),
        ("Habitaciones", habitaciones),
        ("Baños", banos),
        ("Estrato", estrato),
    ]
    if parqueadero is not None:
        specs.append(("Parqueadero", parqueadero))
    if include_code:
        specs.append(("Código:", code))
    price_value = (
        f'<p class="mt-1 text-[35px] leading-none font-bold text-brand">{precio}</p>'
        if precio
        else ""
    )
    price_label = (
        '<p class="text-[16.5px] text-foreground/75">Precio de arriendo</p>'
        f"{price_value}"
        if include_price
        else ""
    )
    rows = "".join(
        '<li class="flex items-center gap-3.5 py-2.5 text-[17.5px]">'
        '<span aria-hidden="true" class="grid w-8 shrink-0 place-items-center text-brand">'
        '<svg aria-hidden="true" class="h-[23px] w-auto" viewbox="0 0 24 24">'
        '<path d="M0 0h24v24H0z"></path></svg>'
        "</span>"
        f'<span class="flex-1">{label}</span>'
        f'<span class="font-medium">{value}</span>'
        "</li>"
        for label, value in specs
    )
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <link rel="canonical" href="{canonical}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:title" content="{title}">
  <meta property="og:image:alt" content="{location}">
</head>
<body>
<main>
  <h1>{h1}</h1>
  {extra}
  <div class="flex flex-1 flex-col rounded-2xl bg-white p-6 shadow-[3px_3px_10px_rgba(0,0,0,0.28)]" style="max-height:538px">
    {price_label}
    <ul class="mt-5 flex flex-1 flex-col justify-between border-t border-border pt-2">
      {rows}
    </ul>
  </div>
</main>
</body>
</html>"""


def _soft_404_html() -> str:
    return f"""<!doctype html>
<html><head>
  <title>Inmueble no disponible</title>
  <meta name="robots" content="noindex, follow">
  <link rel="canonical" href="{BASE}/">
</head><body>
  <main><p>Este inmueble ya no se encuentra disponible.</p></main>
</body></html>"""


def _noindex_challenge_html(*, canonical: str | None = None) -> str:
    link = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    return f"""<!doctype html>
<html><head>
  <title>Verificando acceso</title>
  <meta name="robots" content="noindex, follow">
  {link}
</head><body>
  <main><p>Estamos verificando tu acceso.</p></main>
</body></html>"""


def _scrape_with(sitemap: str, details: dict[str, str], ciudades, **kwargs):
    def fake_fetch(url: str) -> str:
        if url == f"{BASE}/sitemap.xml":
            return sitemap
        return ""

    fetched_batches: list[list[str]] = []

    def fake_bulk(urls, max_workers=None):
        fetched_batches.append(list(urls))
        return [(url, details.get(url, "")) for url in urls]

    with (
        mock.patch.object(aev, "_fetch_sitemap_xml", side_effect=fake_fetch),
        mock.patch.object(aev, "bulk_fetch", side_effect=fake_bulk),
    ):
        rows = aev.scrape_cities(ciudades, **kwargs)
    return rows, fetched_batches


def test_primary_ssr_metrics_map_to_all_eleven_fields():
    detail = _detail_html(code="80307")

    parsed = aev._parse_detail_page(detail, expected_code="80307")
    row = aev._to_row(parsed)

    assert tuple(row) == (
        "id",
        "portal",
        "tipo",
        "precio",
        "area",
        "habitaciones",
        "banos",
        "parqueaderos",
        "estrato",
        "barrio",
        "url",
    )
    assert "ciudad" not in row
    assert row["id"] == "AEV-80307"
    assert row["portal"] == "arrendamientosenvigado"
    assert row["tipo"] == "apartamento"
    assert row["precio"] == 2_100_000
    assert row["area"] == 55
    assert row["habitaciones"] == 1
    assert row["banos"] == 1
    assert row["parqueaderos"] == 0
    assert row["estrato"] == 4
    assert row["barrio"] == "El Portal"
    assert (
        row["url"] == f"{BASE}/inmueble/apartamento-arriendo-envigado-el-portal-80307"
    )


def test_ssr_units_accept_cop_price_and_decimal_square_meters():
    detail = _detail_html(
        code="78871",
        slug=_slug("casa", "la-estrella", "suramerica", "78871"),
        h1="Casa en arriendo en La Estrella, Suramérica",
        location="La Estrella, Suramérica",
        precio="COP 2.800.000 / mes",
        area="73,5 m²",
        habitaciones="2",
        banos="2",
        parqueadero="1",
        estrato="4",
    )

    parsed = aev._parse_detail_page(detail, expected_code="78871")

    assert parsed["precio"] == 2_800_000
    assert parsed["area"] == 73
    assert parsed["parqueaderos"] == 1
    assert parsed["municipio"] == "la-estrella"
    assert parsed["barrio"] == "Suramerica"


def test_og_image_alt_supplies_municipality_and_barrio_without_en_prefix():
    detail = _detail_html(
        code="80307",
        slug="80307",
        h1="Apartamento en arriendo",
        title="Apartamento en arriendo",
        location="Envigado, El Portal",
    )

    parsed = aev._parse_detail_page(detail, expected_code="80307")

    assert parsed["municipio"] == "envigado"
    assert parsed["barrio"] == "El Portal"


def test_og_image_alt_municipality_conflicts_with_canonical_raise():
    detail = _detail_html(
        code="80307",
        h1="Apartamento en arriendo",
        title="Apartamento en arriendo",
        location="Sabaneta, Centro",
    )

    with pytest.raises(aev.PortalParseError):
        aev._parse_detail_page(detail, expected_code="80307")


def test_omitted_parking_stays_zero_and_prose_never_infers_it():
    detail = _detail_html(
        code="80307",
        parqueadero=None,
        habitaciones="",
        banos="2",
        estrato="",
        extra=(
            "<p>Incluye parqueadero para 2 carros y zona de parqueo.</p>"
            '<ul class="amenidades">'
            "<li><span>Parqueaderos visitantes</span><span>2</span></li>"
            "</ul>"
            '<section class="relacionados"><span>Parqueaderos</span>'
            "<span>2</span></section>"
        ),
    )

    parsed = aev._parse_detail_page(detail, expected_code="80307")

    assert parsed["parqueaderos"] == 0
    assert parsed["habitaciones"] == 0
    assert parsed["banos"] == 2
    assert parsed["estrato"] == 0


def test_empty_price_row_raises_instead_of_borrowing_the_next_metric():
    detail = _detail_html(code="80307", precio="")

    with pytest.raises(aev.PortalParseError):
        aev._parse_detail_page(detail, expected_code="80307")


def test_authentic_pricecard_with_metrics_list_parses_price():
    detail = _detail_html(
        code="80317",
        precio="$7.500.000",
        area="130 m²",
        habitaciones="3",
        banos="2",
        estrato="6",
    )

    parsed = aev._parse_detail_page(detail, expected_code="80317")

    assert parsed["precio"] == 7_500_000
    assert parsed["area"] == 130
    assert parsed["habitaciones"] == 3
    assert parsed["banos"] == 2


def test_adjacent_metrics_container_never_supplies_a_price():
    soup = BeautifulSoup(
        "<div><p>Precio de arriendo</p><ul>"
        "<li><span>Área construida</span><span>130 m²</span></li>"
        "</ul></div>",
        "html.parser",
    )

    assert aev._extract_value(soup.find("p")) == ""


def test_adjacent_metric_label_never_supplies_a_price():
    soup = BeautifulSoup(
        "<div><p>Precio de arriendo</p><p>Área construida</p><p>130 m²</p></div>",
        "html.parser",
    )

    assert aev._extract_value(soup.find("p")) == ""


def test_empty_adjacent_value_cell_never_falls_through_to_the_next_row():
    soup = BeautifulSoup(
        "<div><p>Precio de arriendo</p><p></p><p>Área construida</p>"
        "<p>130 m²</p></div>",
        "html.parser",
    )

    assert aev._extract_value(soup.find("p")) == ""


def test_ssr_comment_markers_between_label_and_value_are_ignored():
    soup = BeautifulSoup(
        "<div><p>Precio de arriendo</p><!--$--><!--/$--><p>$7.500.000</p></div>",
        "html.parser",
    )

    assert aev._extract_value(soup.find("p")) == "$7.500.000"


def test_missing_room_cell_never_borrows_the_bathroom_row():
    soup = BeautifulSoup(
        "<div><p>Precio de arriendo</p><p>$7.500.000</p><ul>"
        "<li><span>Habitaciones</span></li>"
        "<li><span>Baños</span><span>2</span></li>"
        "</ul></div>",
        "html.parser",
    )

    labels = aev._collect_labels(soup)

    assert "habitaciones" not in labels
    assert labels["banos"] == "2"
    assert labels["precio"] == "$7.500.000"


def test_related_results_and_embedded_flight_json_do_not_contaminate_primary():
    detail = _detail_html(
        code="80307",
        extra=(
            '<section class="otros-resultados">'
            "<h2>Otros resultados</h2>"
            '<div class="card"><span>Precio de arriendo</span><span>$ 9.900.000</span>'
            "<span>Habitaciones</span><span>9</span></div>"
            "</section>"
            '<script>self.__next_f.push([1,"Habitaciones 9 Precio $ 9.900.000"])</script>'
        ),
    )

    parsed = aev._parse_detail_page(detail, expected_code="80307")

    assert parsed["precio"] == 2_100_000
    assert parsed["habitaciones"] == 1
    assert parsed["id"] == "AEV-80307"


def test_explicit_dead_page_is_skipped_but_malformed_page_raises():
    assert aev._parse_detail_page(_soft_404_html(), expected_code="99999999") is None

    with pytest.raises(aev.PortalParseError):
        aev._parse_detail_page(_noindex_challenge_html(), expected_code="99999999")
    with pytest.raises(aev.PortalParseError):
        aev._parse_detail_page(
            _noindex_challenge_html(canonical=f"{BASE}/"), expected_code="99999999"
        )

    malformed = _detail_html(code="80307", include_price=False)
    with pytest.raises(aev.PortalParseError):
        aev._parse_detail_page(malformed, expected_code="80307")


def test_code_guard_rejects_mismatched_primary_label_and_canonical():
    mismatched = _detail_html(code="80308")

    with pytest.raises(aev.PortalParseError):
        aev._parse_detail_page(mismatched, expected_code="80307")


def test_sale_and_unsupported_municipality_are_skipped_not_stored():
    sale = _detail_html(
        code="80400",
        slug=_slug("casa", "envigado", "el-portal", "80400", operacion="venta"),
        h1="Casa en venta en Envigado, El Portal",
        title="Casa en venta en Envigado",
    )
    assert aev._parse_detail_page(sale, expected_code="80400") is None

    outside = _detail_html(
        code="80500",
        slug=_slug("casa", "bello", "centro", "80500"),
        h1="Casa en arriendo en Bello, Centro",
        title="Casa en arriendo en Bello",
        location="Bello, Centro",
    )
    assert aev._parse_detail_page(outside, expected_code="80500") is None


def test_san_antonio_de_prado_corregimiento_is_included_in_medellin():
    detail = _detail_html(
        code="78648",
        slug="apartamento-arriendo-san-antonio-de-prado-vergel-78648",
        h1="Apartamento en arriendo",
        title="Apartamento en arriendo en San Antonio De Prado, Vergel · Cód. 78648",
        location="San Antonio De Prado, Vergel",
    )

    parsed = aev._parse_detail_page(detail, expected_code="78648")

    assert parsed is not None
    assert (parsed["municipio"], parsed["barrio"]) == ("medellin", "Vergel")


def test_bare_h1_unsupported_municipality_is_skipped_not_raised():
    # Verified source shape of
    # /inmueble/apartamento-arriendo-rionegro-fontibon-80349: the H1 is the
    # generic "Apartamento en arriendo" heading and the municipality appears
    # only in the listing title and in the og:image:alt pair.
    detail = _detail_html(
        code="80349",
        slug="apartamento-arriendo-rionegro-fontibon-80349",
        h1="Apartamento en arriendo",
        title="Apartamento en arriendo en Rionegro, Fontibon · Cód. 80349",
        location="Rionegro, Fontibon",
        precio="$ 1.700.000",
        area="53 m²",
        habitaciones="3",
        banos="2",
        parqueadero="1",
        estrato="",
    )

    assert aev._parse_detail_page(detail, expected_code="80349") is None


def test_title_only_unsupported_municipality_is_skipped_without_location_meta():
    detail = _detail_html(
        code="80308",
        slug="apartamento-arriendo-rionegro-barro-blanco-80308",
        h1="Apartamento en arriendo",
        title="Apartamento en arriendo en Rionegro, Barro Blanco · Cód. 80308",
        location="",
        precio="$ 2.700.000",
    )

    assert aev._parse_detail_page(detail, expected_code="80308") is None


def test_unsupported_municipality_never_blocks_a_requested_city_sample():
    outside = "/inmueble/apartamento-arriendo-rionegro-fontibon-80349"
    rental = "/inmueble/apartamento-arriendo-envigado-el-portal-80307"
    details = {
        f"{BASE}{outside}": _detail_html(
            code="80349",
            slug="apartamento-arriendo-rionegro-fontibon-80349",
            h1="Apartamento en arriendo",
            title="Apartamento en arriendo en Rionegro, Fontibon · Cód. 80349",
            location="Rionegro, Fontibon",
            precio="$ 1.700.000",
        ),
        f"{BASE}{rental}": _detail_html(code="80307"),
    }

    rows, batches = _scrape_with(
        _sitemap(outside, rental), details, ["envigado"], sample_only=True
    )

    fetched = [url for batch in batches for url in batch]
    assert sorted(fetched) == sorted([f"{BASE}{outside}", f"{BASE}{rental}"])
    assert [row["id"] for row in rows["envigado"]] == ["AEV-80307"]


def test_title_only_supported_municipality_is_accepted_on_a_cityless_canonical():
    detail = _detail_html(
        code="80356",
        slug="80356",
        h1="Apartamento en arriendo",
        title="Apartamento en arriendo en Medellín, Laureles · Cód. 80356",
        location="",
    )

    parsed = aev._parse_detail_page(detail, expected_code="80356")

    assert parsed["municipio"] == "medellin"
    assert parsed["barrio"] == ""


def test_page_that_states_no_municipality_still_raises_with_its_source_url():
    detail = _detail_html(
        code="80356",
        slug="80356",
        h1="Apartamento en arriendo",
        title="Apartamento en arriendo · Cód. 80356",
        location="",
    )

    with pytest.raises(aev.PortalParseError) as excinfo:
        aev._parse_detail_page(detail, expected_code="80356")

    message = str(excinfo.value)
    assert "municipality is missing" in message
    assert f"{BASE}/inmueble/80356" in message


def test_two_supported_municipalities_without_a_canonical_city_are_ambiguous():
    detail = _detail_html(
        code="80356",
        slug="80356",
        h1="Apartamento en arriendo en Envigado, Primavera",
        title="Apartamento en arriendo en Envigado, Primavera",
        location="Sabaneta, Primavera",
    )

    with pytest.raises(aev.PortalParseError) as excinfo:
        aev._parse_detail_page(detail, expected_code="80356")

    assert "ambiguous" in str(excinfo.value)


def test_canonical_and_h1_operation_disagreement_raises():
    rental_canonical_sale_h1 = _detail_html(
        code="80401",
        slug=_slug("casa", "envigado", "el-portal", "80401"),
        h1="Casa en venta en Envigado, El Portal",
    )
    with pytest.raises(aev.PortalParseError):
        aev._parse_detail_page(rental_canonical_sale_h1, expected_code="80401")

    sale_canonical_rental_h1 = _detail_html(
        code="80402",
        slug=_slug("casa", "envigado", "el-portal", "80402", operacion="venta"),
        h1="Casa en arriendo en Envigado, El Portal",
    )
    with pytest.raises(aev.PortalParseError):
        aev._parse_detail_page(sale_canonical_rental_h1, expected_code="80402")


def test_expected_code_mismatch_fails_before_sale_and_city_filters():
    sale_with_other_code = _detail_html(
        code="80400",
        slug=_slug("casa", "sabaneta", "centro", "80400", operacion="venta"),
        h1="Casa en venta en Sabaneta, Centro",
        location="Sabaneta, Centro",
    )
    with pytest.raises(aev.PortalParseError):
        aev._parse_detail_page(sale_with_other_code, expected_code="80307")


def test_mixed_casa_finca_type_is_not_collapsed_to_casa():
    detail = _detail_html(
        code="80600",
        slug=_slug("casa-finca", "envigado", "el-portal", "80600"),
        h1="Casa Finca en arriendo en Envigado, El Portal",
    )

    assert aev._parse_detail_page(detail, expected_code="80600") is None


def test_sitemap_parser_handles_namespaced_indexes_and_urlsets():
    prefixed_urlset = (
        '<sm:urlset xmlns:sm="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<sm:url><sm:loc>{BASE}/inmueble/80307</sm:loc></sm:url>"
        "</sm:urlset>"
    )
    kind, locs = aev._sitemap_kind_and_locs(prefixed_urlset)
    assert kind == "urlset"
    assert locs == [f"{BASE}/inmueble/80307"]

    kind, locs = aev._sitemap_kind_and_locs(
        '<sm:sitemapindex xmlns:sm="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<sm:sitemap><sm:loc>{BASE}/sitemap-inmuebles.xml</sm:loc></sm:sitemap>"
        "</sm:sitemapindex>"
    )
    assert kind == "sitemapindex"
    assert locs == [f"{BASE}/sitemap-inmuebles.xml"]


def test_sitemap_transport_parses_raw_xml_not_normalized_html():
    raw = _sitemap("/inmueble/80307", "/inmueble/80356")
    # The real application/xml response is normalized by Scrapling's
    # html_content into this wrapper; parsing that wrapper must never be the
    # sitemap source.
    normalized = (
        '<html><body><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{BASE}/inmueble/80307</loc></url>"
        f"<url><loc>{BASE}/inmueble/80356</loc></url>"
        "</urlset></body></html>"
    )
    response = mock.Mock(status=200, encoding="utf-8", body=raw.encode("utf-8"))
    response.html_content = normalized

    with mock.patch.object(aev.scrapling.Fetcher, "get", return_value=response):
        xml_text = aev._fetch_sitemap_xml(f"{BASE}/sitemap.xml")

    assert xml_text.startswith('<?xml version="1.0"')
    kind, locs = aev._sitemap_kind_and_locs(xml_text)
    assert kind == "urlset"
    assert locs == [f"{BASE}/inmueble/80307", f"{BASE}/inmueble/80356"]


def test_html_sitemap_response_is_a_technical_failure():
    wrapped_urlset = (
        '<html><body><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{BASE}/inmueble/80307</loc></url>"
        "</urlset></body></html>"
    )
    with pytest.raises(aev.PortalParseError):
        aev._sitemap_kind_and_locs(wrapped_urlset)

    challenge = (
        "<!doctype html><html><head><title>Verificando acceso</title></head>"
        "<body><p>Estamos verificando tu acceso.</p></body></html>"
    )
    with pytest.raises(aev.PortalParseError):
        aev._sitemap_kind_and_locs(challenge)


def test_sitemap_requires_the_sitemaps_namespace_and_absolute_locs():
    with pytest.raises(aev.PortalParseError):
        aev._sitemap_kind_and_locs(
            f"<urlset><url><loc>{BASE}/inmueble/80307</loc></url></urlset>"
        )

    with pytest.raises(aev.PortalParseError):
        aev._sitemap_kind_and_locs(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>/inmueble/80307</loc></url>"
            "</urlset>"
        )


def test_sitemap_transport_failure_raises_instead_of_empty_discovery():
    for response in (
        mock.Mock(status=503, encoding="utf-8", body=b""),
        mock.Mock(status=200, encoding="utf-8", body=b""),
    ):
        with mock.patch.object(aev.scrapling.Fetcher, "get", return_value=response):
            with pytest.raises(aev.PortalFetchError):
                aev._fetch_sitemap_xml(f"{BASE}/sitemap.xml")


def test_cityless_sitemap_entry_is_grouped_by_canonical_municipality():
    sitemap = _sitemap("/inmueble/80356", "/inmueble/80356")
    detail = _detail_html(
        code="80356",
        slug=_slug("apartamento", "envigado", "primavera", "80356"),
        h1="Apartamento en arriendo en Envigado, Primavera",
        location="Envigado, Primavera",
        precio="$ 3.800.000",
        area="120 m²",
        habitaciones="4",
        banos="3",
        estrato="2",
    )

    rows, batches = _scrape_with(
        sitemap,
        {f"{BASE}/inmueble/80356": detail},
        ["envigado"],
        sample_only=True,
    )

    assert list(rows) == ["envigado"]
    assert [row["id"] for row in rows["envigado"]] == ["AEV-80356"]
    assert rows["envigado"][0]["barrio"] == "Primavera"
    assert batches == [[f"{BASE}/inmueble/80356"]]


def test_multi_city_request_discovers_once_and_groups_by_actual_municipality():
    first = f"{BASE}/inmueble/80307"
    second = f"{BASE}/inmueble/apartamento-arriendo-sabaneta-centro-80400"
    third = f"{BASE}/inmueble/casa-arriendo-la-estrella-suramerica-78871"
    fourth = f"{BASE}/inmueble/apartamento-arriendo-medellin-laureles-80200"
    sitemap = _sitemap_index("/sitemap-envigado.xml", "/sitemap-sur.xml")
    child_a = _sitemap(
        "/inmueble/80307", "/inmueble/apartamento-arriendo-sabaneta-centro-80400"
    )
    child_b = _sitemap(
        "/inmueble/casa-arriendo-la-estrella-suramerica-78871",
        "/inmueble/apartamento-arriendo-medellin-laureles-80200",
    )
    details = {
        first: _detail_html(code="80307"),
        second: _detail_html(
            code="80400",
            slug=_slug("apartamento", "sabaneta", "centro", "80400"),
            h1="Apartamento en arriendo en Sabaneta, Centro",
            location="Sabaneta, Centro",
        ),
        third: _detail_html(
            code="78871",
            slug=_slug("casa", "la-estrella", "suramerica", "78871"),
            h1="Casa en arriendo en La Estrella, Suramérica",
            location="La Estrella, Suramérica",
            precio="$ 2.800.000",
        ),
        fourth: _detail_html(
            code="80200",
            slug=_slug("apartamento", "medellin", "laureles", "80200"),
            h1="Apartamento en arriendo en Medellín, Laureles",
            location="Medellín, Laureles",
        ),
    }

    sitemap_calls: list[str] = []

    def fake_fetch(url: str) -> str:
        sitemap_calls.append(url)
        return {
            f"{BASE}/sitemap.xml": sitemap,
            f"{BASE}/sitemap-envigado.xml": child_a,
            f"{BASE}/sitemap-sur.xml": child_b,
        }.get(url, "")

    def fake_bulk(urls, max_workers=None):
        return [(url, details.get(url, "")) for url in urls]

    with (
        mock.patch.object(aev, "_fetch_sitemap_xml", side_effect=fake_fetch),
        mock.patch.object(aev, "bulk_fetch", side_effect=fake_bulk),
    ):
        rows = aev.scrape_cities(
            ["envigado", "sabaneta", "la estrella", "medellin"], sample_only=True
        )

    assert sitemap_calls.count(f"{BASE}/sitemap.xml") == 1
    assert sitemap_calls.count(f"{BASE}/sitemap-envigado.xml") == 1
    assert sitemap_calls.count(f"{BASE}/sitemap-sur.xml") == 1
    assert {row["id"] for row in rows["envigado"]} == {"AEV-80307"}
    assert {row["id"] for row in rows["sabaneta"]} == {"AEV-80400"}
    assert {row["id"] for row in rows["la-estrella"]} == {"AEV-78871"}
    assert {row["id"] for row in rows["medellin"]} == {"AEV-80200"}


def test_wrong_source_city_never_leaks_into_requested_scope():
    path = "/inmueble/apartamento-arriendo-sabaneta-a7-80400"
    sitemap = _sitemap(path)
    detail = _detail_html(
        code="80400",
        slug=_slug("apartamento", "sabaneta", "a7", "80400"),
        h1="Apartamento en arriendo en Sabaneta, A7",
        location="Sabaneta, A7",
    )

    rows, _ = _scrape_with(sitemap, {f"{BASE}{path}": detail}, ["envigado"])

    assert rows == {"envigado": []}


def test_sale_candidates_are_not_fetched_as_rentals():
    rental = "/inmueble/apartamento-arriendo-envigado-el-portal-80307"
    sale = "/inmueble/casa-venta-envigado-el-portal-80400"
    sitemap = _sitemap(rental, sale)

    rows, batches = _scrape_with(
        sitemap,
        {f"{BASE}{rental}": _detail_html(code="80307")},
        ["envigado"],
        sample_only=True,
    )

    assert [url for batch in batches for url in batch] == [f"{BASE}{rental}"]
    assert [row["id"] for row in rows["envigado"]] == ["AEV-80307"]


def test_sample_mode_is_bounded_and_caps_three_rows_per_city():
    paths = [
        f"/inmueble/apartamento-arriendo-envigado-b{i}-{81000 + i}" for i in range(80)
    ]
    details = {
        f"{BASE}{path}": _detail_html(
            code=str(81000 + index),
            slug=_slug("apartamento", "envigado", f"b{index}", str(81000 + index)),
        )
        for index, path in enumerate(paths)
    }

    rows, batches = _scrape_with(
        _sitemap(*paths), details, ["envigado"], sample_only=True
    )

    fetched = [url for batch in batches for url in batch]
    assert len(rows["envigado"]) == 3
    assert len(fetched) == 3


def test_sample_mode_replenishes_dead_candidates_before_reporting_empty():
    paths = [
        f"/inmueble/apartamento-arriendo-envigado-b{i}-{83000 + i}" for i in range(6)
    ]
    details = {}
    for index, path in enumerate(paths):
        if index == 3:
            details[f"{BASE}{path}"] = _detail_html(
                code=str(83000 + index),
                slug=_slug("apartamento", "envigado", f"b{index}", str(83000 + index)),
            )
        else:
            details[f"{BASE}{path}"] = _soft_404_html()

    rows, _batches = _scrape_with(
        _sitemap(*paths), details, ["envigado"], sample_only=True
    )

    assert [row["id"] for row in rows["envigado"]] == ["AEV-83003"]


def test_sample_mode_empty_city_means_the_pool_was_examined():
    paths = [
        f"/inmueble/apartamento-arriendo-envigado-b{i}-{84000 + i}" for i in range(6)
    ]
    details = {f"{BASE}{path}": _soft_404_html() for path in paths}

    rows, batches = _scrape_with(
        _sitemap(*paths), details, ["envigado"], sample_only=True
    )

    fetched = [url for batch in batches for url in batch]
    assert rows == {"envigado": []}
    assert len(fetched) == len(paths)


def test_max_pages_bounds_detail_batches_without_claiming_a_snapshot():
    paths = [
        f"/inmueble/apartamento-arriendo-envigado-b{i}-{82000 + i}" for i in range(120)
    ]
    details = {
        f"{BASE}{path}": _detail_html(
            code=str(82000 + index),
            slug=_slug("apartamento", "envigado", f"b{index}", str(82000 + index)),
        )
        for index, path in enumerate(paths)
    }

    rows, batches = _scrape_with(_sitemap(*paths), details, ["envigado"], max_pages=1)

    fetched = [url for batch in batches for url in batch]
    assert len(fetched) == 100
    assert len(rows["envigado"]) == 100


def test_cli_canonicalizes_city_alias_before_shared_runner():
    import scripts.scrape_arrendamientosenvigado as cli

    args = argparse.Namespace(
        portal="arrendamientosenvigado",
        output="both",
        ciudad="La Estrella",
        sample_only=True,
        max_pages=1,
        verbose=False,
    )

    def fake_run(scraper_fn, portal=None, args=None):
        scraper_fn()
        return 0

    with (
        mock.patch.object(cli, "scrape", return_value=[]) as scrape_mock,
        mock.patch.object(cli, "run_scraper", side_effect=fake_run),
    ):
        assert cli.main(args=args) == 0

    assert args.ciudad == "la-estrella"
    assert scrape_mock.call_args.kwargs["ciudad"] == "la-estrella"
