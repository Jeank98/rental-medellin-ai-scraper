"""Regression tests for the Lonja Inmobiliaria del Sur two-phase scraper."""

from unittest import mock

import pytest

from scrape.lonjainmobiliariadelsur import (
    COLUMNS,
    PORTAL,
    PREFIX,
    LonjaChallengeError,
    LonjaFetchError,
    LonjaIncompleteError,
    LonjaIntegrityError,
    build_search_url,
    merge_detail,
    parse_detail_page,
    parse_result_total,
    parse_search_page,
    scrape,
    scrape_cities,
)

PAGE_URL = "scrape.lonjainmobiliariadelsur.fetch_page"
DETAIL_URL = "scrape.lonjainmobiliariadelsur.bulk_fetch"


def _card(
    code: str,
    tipo: str = "Apartamento",
    price: str = "$1.500.000",
    area: int = 70,
    rooms: int = 2,
    baths: int = 2,
    location: str = "Laureles, Medellín",
    slug: str = "",
    operation: str = "arriendo",
) -> str:
    href = f"/inmueble/{slug or f'{code}-{tipo.lower()}-{operation}-medellin-laureles'}"
    return (
        '<div class="property_item">'
        f'<div class="property_head"><h3>{tipo} - {code}</h3></div>'
        f'<div class="image"><a href="{href}"><img></a></div>'
        '<div class="property_meta">'
        f"<span>{area} m<sup>2</sup></span>"
        f"<span>{rooms} Alcobas</span>"
        f"<span>{baths}.0 Baños</span>"
        "</div>"
        f'<div class="proerty_text"><h4>{location}</h4></div>'
        f'<div class="favroute2"><p>{price}</p></div>'
        "</div>"
    )


def _detail(
    code: str,
    municipio: str = "Medellín",
    barrio: str | None = "Laureles",
    estrato: int = 4,
    price: str = "$1.500.000",
    area: int = 70,
    rooms: int = 2,
    baths: int = 2,
    blocks: list[str] | None = None,
    narrative: str = "",
    operation: str | None = "Arriendo",
    tipo: str = "Apartamento",
) -> str:
    block_list = (
        blocks if blocks is not None else [f"Baños:{baths}", f"Alcobas: {rooms}"]
    )
    block_html = "".join(f"<li>{block}</li>" for block in block_list)
    barrio_row = (
        f"<tr><td><b>Barrio</b></td><td>{barrio}</td></tr>"
        if barrio is not None
        else ""
    )
    heading = (
        f"{tipo} para {operation}, Código {code}"
        if operation
        else f"{tipo}, Código {code}"
    )
    return (
        "<html><body>"
        f"<h1>{heading}</h1>"
        "<table>"
        f"<tr><td><b>Código</b></td><td>{code}</td></tr>"
        f"<tr><td><b>Municipio</b></td><td>{municipio}</td></tr>"
        f"{barrio_row}"
        f"<tr><td><b>Estrato</b></td><td>{estrato}</td></tr>"
        f"<tr><td><b>Precio</b></td><td>{price}</td></tr>"
        f"<tr><td><b>Área</b></td><td>{area} m2</td></tr>"
        "</table>"
        f"<p>{narrative}</p>"
        f'<ul class="bloques">{block_html}</ul>'
        "</body></html>"
    )


def _page(*cards: str, total: int | None = None) -> str:
    header = (
        f"<header><h2>{total} Encontrados</h2></header>" if total is not None else ""
    )
    return f"<html><body>{header}<main>{''.join(cards)}</main></body></html>"


EMPTY_PAGE = "<html><body><h2>0 Encontrados</h2></body></html>"


def _detail_pairs(search_html: str, details: dict[str, str]) -> list[tuple[str, str]]:
    return [
        (row["url"], details[row["id"].split("-", 1)[1]])
        for row in parse_search_page(search_html)
    ]


def test_build_search_url_encodes_accented_municipalities_and_classes() -> None:
    assert build_search_url(
        ["medellin", "envigado", "itagui", "la-estrella", "sabaneta"]
    ) == (
        "https://www.lonjainmobiliariadelsur.com/inmuebles/Arriendo/"
        "clases_Apartamento_Apartaestudio_Casa/"
        "municipios_Itag%C3%BC%C3%AD_Envigado_La-Estrella_Sabaneta_Medell%C3%ADn"
    )
    assert build_search_url(["la estrella"], page=2) == (
        "https://www.lonjainmobiliariadelsur.com/inmuebles/Arriendo/"
        "clases_Apartamento_Apartaestudio_Casa/municipios_La-Estrella/2"
    )
    assert build_search_url(["Medellín"]) == (
        "https://www.lonjainmobiliariadelsur.com/inmuebles/Arriendo/"
        "clases_Apartamento_Apartaestudio_Casa/municipios_Medell%C3%ADn"
    )


def test_unsupported_city_and_invalid_page_cap_are_rejected() -> None:
    with pytest.raises(ValueError):
        scrape(ciudad="bogota")
    with pytest.raises(ValueError):
        scrape_cities(["medellin"], max_pages=0)


def test_dual_prices_keep_only_the_rental_side() -> None:
    combined = "$1,500,000 - $260,000,000"
    rows = parse_search_page(_page(_card("3929", price=combined), total=1))

    assert [row["precio"] for row in rows] == [1_500_000]
    assert parse_detail_page(_detail("3929", price=combined))["precio"] == 1_500_000
    assert all(0 <= row["precio"] <= 2_147_483_647 for row in rows)


def test_mixed_source_classes_are_rejected_without_collapsing_into_casa() -> None:
    rows = parse_search_page(
        _page(
            _card("1", tipo="Apartamento"),
            _card("2", tipo="Casa-Finca"),
            _card("3", tipo="Casa-Local"),
            _card("4", tipo="Casa"),
            _card("5", tipo="Apartaestudio"),
        )
    )

    assert [(row["id"], row["tipo"]) for row in rows] == [
        (f"{PREFIX}-1", "apartamento"),
        (f"{PREFIX}-4", "casa"),
        (f"{PREFIX}-5", "apartaestudio"),
    ]


def test_duplicate_source_codes_appear_once() -> None:
    rows = parse_search_page(
        _page(
            _card("4100", area=70),
            _card("4100", area=99, slug="4100-otra-variante"),
            total=1,
        )
    )

    assert len(rows) == 1
    assert rows[0]["id"] == f"{PREFIX}-4100"
    assert rows[0]["area"] == 70


def test_encontrados_header_is_read_from_the_authentic_page_text() -> None:
    assert parse_result_total(_page(total=40)) == 40
    assert parse_result_total(_page(_card("4009"), total=1)) == 1
    assert parse_result_total(EMPTY_PAGE) == 0
    assert parse_result_total("<html><body><main></main></body></html>") is None


def test_zero_inside_a_nonzero_header_is_not_an_empty_result() -> None:
    # "40 Encontrados" contains the substring "0 Encontrados"; that must never
    # turn a cardless page into a legitimate empty city.
    with mock.patch(PAGE_URL, return_value=_page(total=40)):
        with pytest.raises(LonjaIntegrityError):
            scrape(ciudad="medellin")


def test_cardless_first_page_without_an_explicit_zero_is_a_failure() -> None:
    with mock.patch(PAGE_URL, return_value="<html><body><main></main></body></html>"):
        with pytest.raises(LonjaIntegrityError):
            scrape()


@pytest.mark.parametrize("first_total", [None, 40])
def test_cardless_page_declaring_results_is_not_an_empty_terminal(
    first_total: int | None,
) -> None:
    full = _page(*[_card(str(7000 + index)) for index in range(16)], total=first_total)
    details = _detail_pairs(
        full, {str(7000 + index): _detail(str(7000 + index)) for index in range(16)}
    )

    with (
        mock.patch(PAGE_URL, side_effect=[full, _page(total=40)]),
        mock.patch(DETAIL_URL, return_value=details),
    ):
        with pytest.raises(LonjaIncompleteError):
            scrape()


def test_cardless_terminal_without_empty_evidence_is_a_failure() -> None:
    full = _page(*[_card(str(7200 + index)) for index in range(16)])
    details = _detail_pairs(
        full, {str(7200 + index): _detail(str(7200 + index)) for index in range(16)}
    )
    with (
        mock.patch(PAGE_URL, side_effect=[full, _page()]),
        mock.patch(DETAIL_URL, return_value=details),
    ):
        with pytest.raises(LonjaIntegrityError):
            scrape()


def test_changing_declared_total_between_pages_is_rejected() -> None:
    first = _page(*[_card(str(7100 + index)) for index in range(16)], total=33)
    second = _page(_card("7300"), total=32)

    with mock.patch(PAGE_URL, side_effect=[first, second]):
        with pytest.raises(LonjaIntegrityError):
            scrape()


def test_empty_results_page_terminates_after_a_full_page() -> None:
    search = _page(*[_card(str(5100 + index)) for index in range(16)])
    details = _detail_pairs(
        search,
        {str(5100 + index): _detail(str(5100 + index)) for index in range(16)},
    )

    with (
        mock.patch(PAGE_URL, side_effect=[search, EMPTY_PAGE]) as discovery,
        mock.patch(DETAIL_URL, return_value=details),
    ):
        rows = scrape()

    assert len(rows) == 16
    assert discovery.call_count == 2


def test_declared_total_unreached_is_a_technical_failure() -> None:
    search = _page(*[_card(str(5200 + index)) for index in range(16)], total=40)

    with mock.patch(PAGE_URL, side_effect=[search, EMPTY_PAGE]):
        with pytest.raises(LonjaIncompleteError):
            scrape()


def test_page_size_is_measured_on_raw_cards_not_accepted_rows() -> None:
    # 16 rendered cards, one of them an unsupported product: the page is still
    # full, so pagination must continue instead of stopping after 15 rows.
    full = _page(
        *[_card(f"74{index:02d}") for index in range(15)],
        _card("7500", tipo="Casa-Finca"),
    )
    details = _detail_pairs(
        full, {f"74{index:02d}": _detail(f"74{index:02d}") for index in range(15)}
    )

    with (
        mock.patch(PAGE_URL, side_effect=[full, EMPTY_PAGE]) as discovery,
        mock.patch(DETAIL_URL, return_value=details),
    ):
        rows = scrape()

    assert len(rows) == 15
    assert discovery.call_count == 2


def test_rejected_class_still_counts_toward_the_declared_total() -> None:
    first = _page(
        *[_card(f"76{index:02d}") for index in range(15)],
        _card("7700", tipo="Casa-Finca"),
        total=17,
    )
    second = _page(_card("7701"), total=17)
    details = _detail_pairs(
        first, {f"76{index:02d}": _detail(f"76{index:02d}") for index in range(15)}
    ) + _detail_pairs(second, {"7701": _detail("7701")})

    with (
        mock.patch(PAGE_URL, side_effect=[first, second]) as discovery,
        mock.patch(DETAIL_URL, return_value=details),
    ):
        rows = scrape()

    assert len(rows) == 16
    assert discovery.call_count == 2


def test_duplicate_codes_do_not_inflate_page_size() -> None:
    # 16 cards, 15 unique source codes: the deduplicated page is short, so it
    # must not trigger a second listing request.
    page = _page(
        *[_card(f"78{index:02d}") for index in range(15)],
        _card("7800", slug="7800-apartamento-arriendo-medellin-otro"),
    )
    details = _detail_pairs(
        page, {f"78{index:02d}": _detail(f"78{index:02d}") for index in range(15)}
    )

    with (
        mock.patch(PAGE_URL, return_value=page) as discovery,
        mock.patch(DETAIL_URL, return_value=details),
    ):
        rows = scrape()

    assert len(rows) == 15
    assert discovery.call_count == 1


def test_repeated_pagination_aborts_instead_of_duplicating_listings() -> None:
    search = _page(*([_card(str(5000 + index)) for index in range(16)]), total=40)

    with mock.patch(PAGE_URL, side_effect=[search, search]):
        with pytest.raises(LonjaIntegrityError):
            scrape()


def test_empty_first_page_with_marker_is_a_legitimate_empty_city() -> None:
    with mock.patch(PAGE_URL, return_value=EMPTY_PAGE):
        assert scrape(ciudad="sabaneta") == []


def test_challenge_page_is_a_technical_failure() -> None:
    challenge = "<html><head><title>Just a moment...</title></head></html>"

    with mock.patch(PAGE_URL, return_value=challenge):
        with pytest.raises(LonjaChallengeError):
            scrape()


def test_detail_municipality_never_leaks_into_another_city() -> None:
    search = _page(_card("4009", location="Laureles, Medellín"), total=1)
    details = _detail_pairs(search, {"4009": _detail("4009", municipio="Sabaneta")})

    with (
        mock.patch(PAGE_URL, return_value=search),
        mock.patch(DETAIL_URL, return_value=details),
    ):
        assert scrape(ciudad="medellin") == []
        grouped = scrape_cities(["medellin", "sabaneta"])

    assert grouped["medellin"] == []
    assert [row["id"] for row in grouped["sabaneta"]] == [f"{PREFIX}-4009"]


def test_card_location_is_never_published_as_barrio() -> None:
    search = _page(_card("4012", location="Villa Paula, Itagüí"), total=1)
    details = _detail_pairs(
        search, {"4012": _detail("4012", municipio="Itagüí", barrio=None)}
    )

    with (
        mock.patch(PAGE_URL, return_value=search),
        mock.patch(DETAIL_URL, return_value=details),
    ):
        rows = scrape(ciudad="itagui")

    assert len(rows) == 1
    assert rows[0]["barrio"] == ""
    assert rows[0]["estrato"] == 4


def test_missing_detail_response_aborts_instead_of_publishing_defaults() -> None:
    search = _page(_card("4009"), total=1)

    with (
        mock.patch(PAGE_URL, return_value=search),
        mock.patch(DETAIL_URL, return_value=[]),
    ):
        with pytest.raises(LonjaFetchError):
            scrape()


def test_detail_code_mismatch_aborts_without_changing_identity() -> None:
    row = parse_search_page(_page(_card("4009"), total=1))[0]
    detail = parse_detail_page(_detail("4010"))

    with pytest.raises(LonjaIntegrityError):
        merge_detail(row, detail)

    assert row["id"] == f"{PREFIX}-4009"
    assert row["estrato"] == 0


def test_merge_detail_rejects_a_foreign_source_identity() -> None:
    row = parse_search_page(_page(_card("4009"), total=1))[0]
    foreign = dict(row, portal="escalainmobiliaria", id="ESC-4009")

    with pytest.raises(LonjaIntegrityError):
        merge_detail(foreign, parse_detail_page(_detail("4009")))


def test_narrative_parking_needs_a_structured_label() -> None:
    narrative = parse_detail_page(
        _detail(
            "3929",
            narrative="Incluye parqueadero privado, gimnasio y salón comunal",
            blocks=["Baños:2", "Alcobas: 3"],
        )
    )
    visitor = parse_detail_page(
        _detail("3929", blocks=["Baños:2", "Alcobas: 3", "Parqueadero visitantes: 3"])
    )
    structured = parse_detail_page(
        _detail("3929", blocks=["Baños:2", "Alcobas: 3", "Parqueadero: 2"])
    )

    assert narrative["parqueaderos"] == 0
    assert visitor["parqueaderos"] == 0
    assert structured["parqueaderos"] == 2


def test_sale_only_card_is_rejected_on_the_rental_route() -> None:
    rows = parse_search_page(
        _page(
            _card("9001", operation="venta", price="$260.000.000"),
            _card("9002", operation="arriendo"),
            total=2,
        )
    )

    assert [row["id"] for row in rows] == [f"{PREFIX}-9002"]


def test_dual_operation_card_and_detail_are_published_with_the_rental_price() -> None:
    combined = "$4.100.000 - $615.000.000"
    search = _page(_card("4038", operation="arriendo-o-venta", price=combined), total=1)
    details = _detail_pairs(
        search,
        {"4038": _detail("4038", operation="Arriendo o Venta", price=combined)},
    )

    with (
        mock.patch(PAGE_URL, return_value=search),
        mock.patch(DETAIL_URL, return_value=details),
    ):
        rows = scrape()

    assert len(rows) == 1
    assert rows[0]["precio"] == 4_100_000
    assert parse_detail_page(details[0][1])["operacion"] == "ambos"


def test_card_slug_without_operation_defers_to_the_detail() -> None:
    search = _page(_card("4009", slug="4009-apartamento-medellin-laureles"), total=1)
    details = _detail_pairs(search, {"4009": _detail("4009")})

    with (
        mock.patch(PAGE_URL, return_value=search),
        mock.patch(DETAIL_URL, return_value=details),
    ):
        rows = scrape()

    assert [row["id"] for row in rows] == [f"{PREFIX}-4009"]


def test_sale_only_detail_is_never_published() -> None:
    search = _page(
        _card("4009", operation="arriendo-o-venta", price="$1.500.000 - $260.000.000"),
        total=1,
    )
    details = _detail_pairs(
        search, {"4009": _detail("4009", operation="Venta", price="$260.000.000")}
    )

    with (
        mock.patch(PAGE_URL, return_value=search),
        mock.patch(DETAIL_URL, return_value=details),
    ):
        assert scrape() == []


def test_detail_without_operation_evidence_aborts() -> None:
    search = _page(_card("4009"), total=1)
    details = _detail_pairs(search, {"4009": _detail("4009", operation=None)})

    with (
        mock.patch(PAGE_URL, return_value=search),
        mock.patch(DETAIL_URL, return_value=details),
    ):
        with pytest.raises(LonjaIntegrityError):
            scrape()


def test_multi_city_scrape_groups_by_detail_municipality_once() -> None:
    search = _page(
        _card("4009", location="Suramerica, La Estrella"),
        _card("4012", location="Villa Paula, Itagüí"),
        _card("3929", location="San Francisco, Medellín"),
        total=3,
    )
    details = _detail_pairs(
        search,
        {
            "4009": _detail("4009", municipio="La Estrella", barrio="Suramerica"),
            "4012": _detail("4012", municipio="Itagüí", barrio="Villa Paula"),
            "3929": _detail("3929", municipio="Medellín", barrio="San Francisco"),
        },
    )

    with (
        mock.patch(PAGE_URL, return_value=search) as discovery,
        mock.patch(DETAIL_URL, return_value=details) as detail_fetch,
    ):
        grouped = scrape_cities(["medellin", "itagui", "La Estrella", "envigado"])

    assert set(grouped) == {"medellin", "itagui", "la-estrella", "envigado"}
    assert [row["id"] for row in grouped["itagui"]] == [f"{PREFIX}-4012"]
    assert [row["id"] for row in grouped["la-estrella"]] == [f"{PREFIX}-4009"]
    assert [row["id"] for row in grouped["medellin"]] == [f"{PREFIX}-3929"]
    assert grouped["envigado"] == []
    assert all("ciudad" not in row for rows in grouped.values() for row in rows)
    assert all(list(row) == COLUMNS for rows in grouped.values() for row in rows)
    assert all(row["portal"] == PORTAL for rows in grouped.values() for row in rows)
    discovery.assert_called_once()
    detail_fetch.assert_called_once()


def test_sample_mode_schedules_three_details_for_one_city() -> None:
    search = _page(*[_card(str(8000 + index)) for index in range(5)], total=5)
    details = _detail_pairs(
        search, {str(8000 + index): _detail(str(8000 + index)) for index in range(5)}
    )

    with (
        mock.patch(PAGE_URL, return_value=search) as discovery,
        mock.patch(DETAIL_URL, return_value=details) as detail_fetch,
    ):
        rows = scrape(sample_only=True)

    scheduled = detail_fetch.call_args.args[0]
    assert len(rows) == 3
    assert scheduled == [row["url"] for row in parse_search_page(search)[:3]]
    discovery.assert_called_once()


def test_sample_mode_schedules_bounded_details_for_each_requested_city() -> None:
    search = _page(
        _card("8100", location="Laureles, Medellín"),
        _card("8101", location="Laureles, Medellín"),
        _card("8102", location="Laureles, Medellín"),
        _card("8103", location="Laureles, Medellín"),
        _card("8200", location="Villa Paula, Itagüí"),
        _card("8201", location="Villa Paula, Itagüí"),
        _card("8202", location="Villa Paula, Itagüí"),
        _card("8203", location="Villa Paula, Itagüí"),
        _card("8300", location="Centro"),
        total=9,
    )
    details = _detail_pairs(
        search,
        {
            **{f"81{index:02d}": _detail(f"81{index:02d}") for index in range(4)},
            **{
                f"82{index:02d}": _detail(f"82{index:02d}", municipio="Itagüí")
                for index in range(4)
            },
            "8300": _detail("8300"),
        },
    )
    urls = {row["id"]: row["url"] for row in parse_search_page(search)}

    with (
        mock.patch(PAGE_URL, return_value=search),
        mock.patch(DETAIL_URL, return_value=details) as detail_fetch,
    ):
        grouped = scrape_cities(["medellin", "itagui"], sample_only=True)

    scheduled = detail_fetch.call_args.args[0]
    assert scheduled == [
        urls[f"{PREFIX}-8100"],
        urls[f"{PREFIX}-8101"],
        urls[f"{PREFIX}-8102"],
        urls[f"{PREFIX}-8200"],
        urls[f"{PREFIX}-8201"],
        urls[f"{PREFIX}-8202"],
    ]
    assert len(scheduled) == 6
    assert [row["id"] for row in grouped["medellin"]] == [
        f"{PREFIX}-8100",
        f"{PREFIX}-8101",
        f"{PREFIX}-8102",
    ]
    assert [row["id"] for row in grouped["itagui"]] == [
        f"{PREFIX}-8200",
        f"{PREFIX}-8201",
        f"{PREFIX}-8202",
    ]


def test_sample_mode_fills_missing_hint_slots_from_a_bounded_unknown_pool() -> None:
    search = _page(
        _card("8400", location="La Carola, Envigado"),
        _card("8401", location="El Dorado, Envigado"),
        _card("8500", location="Centro"),
        _card("8501", location="Centro"),
        _card("8502", location="Centro"),
        _card("8503", location="Centro"),
        _card("8504", location="Centro"),
        total=7,
    )
    details = _detail_pairs(
        search,
        {
            "8400": _detail("8400", municipio="Envigado"),
            "8401": _detail("8401", municipio="Envigado"),
            **{
                f"85{index:02d}": _detail(f"85{index:02d}", municipio="Envigado")
                for index in range(5)
            },
        },
    )
    urls = {row["id"]: row["url"] for row in parse_search_page(search)}

    with (
        mock.patch(PAGE_URL, return_value=search),
        mock.patch(DETAIL_URL, return_value=details) as detail_fetch,
    ):
        rows = scrape(ciudad="envigado", sample_only=True)

    scheduled = detail_fetch.call_args.args[0]
    assert scheduled == [
        urls[f"{PREFIX}-8400"],
        urls[f"{PREFIX}-8401"],
        urls[f"{PREFIX}-8500"],
    ]
    assert [row["id"] for row in rows] == [
        f"{PREFIX}-8400",
        f"{PREFIX}-8401",
        f"{PREFIX}-8500",
    ]
