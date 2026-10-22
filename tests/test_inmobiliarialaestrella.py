"""Regression tests for the Inmobiliaria La Estrella two-phase scraper."""

import argparse
import json

import pytest
from bs4 import BeautifulSoup

import scripts.scrape_inmobiliarialaestrella as cli
from scrape.inmobiliarialaestrella import (
    BASE_URL,
    COLUMNS,
    PortalDetailError,
    PortalDiscoveryError,
    _LOADER_IMAGE_SELECTOR,
    _drain_results,
    _sample_plan,
    parse_detail,
    parse_search_html,
    parse_search_report,
    scrape_cities,
)

_CODE_A = "9564"
_CODE_B = "9704"
_CODE_C = "9648"


def _cop(value: int) -> str:
    return f"${value:,}".replace(",", ".")


def _card(
    code: str,
    tipo: str = "Apartamento",
    price: int = 2700000,
    area: int = 70,
    rooms: int = 3,
    baths: int = 2,
    parking: int = 1,
    title_city: str = "ITAGUI",
    old_price: int | None = None,
) -> str:
    old = f"<del>{_cop(old_price)}</del>" if old_price else ""
    return (
        '<div class="estate_itm">'
        f'<a href="/propiedad/{tipo.casefold()}-en-arriendo-{code}"><img></a>'
        f"<h4>{tipo} en Arriendo - {title_city}</h4>"
        f"<div>{tipo}</div>"
        f'<div class="price">{old}<span>{_cop(price)}</span></div>'
        f"<div>{area} m²</div>"
        f"<div>{rooms} Alcobas</div>"
        f"<div>{baths} Baños</div>"
        f"<div>{parking} parq.</div>"
        "</div>"
    )


def _results(*cards: str, extra: str = "") -> str:
    return (
        "<html><body>"
        '<section class="results_content--list"><div class="_list">'
        f"{''.join(cards)}{extra}"
        "</div></section>"
        "</body></html>"
    )


_GOOD_RELATIONS = "http://purl.org/goodrelations/v1#"


def _detail_html(
    code: str,
    locality: str = "La Estrella",
    price: int = 2700000,
    area: int = 70,
    rooms: int = 3,
    baths: int = 2,
    parking: int = 1,
    include_parking: bool = True,
    estrato: int = 4,
    sector: str | None = "Ditaires",
    old_visible: int | None = None,
    canonical_code: str | None = None,
    operation: str = "rent",
    related_listing: dict | None = None,
    offers: list[dict] | None = None,
    listing_url: str | None = None,
    omit_address: bool = False,
    agent_locality: str | None = None,
    description_heading: str | None = None,
) -> str:
    if operation == "rent":
        name = f"Apartamento en arriendo en {locality}"
        offer: dict[str, object] = {
            "@type": "Offer",
            "price": price,
            "businessFunction": f"{_GOOD_RELATIONS}LeaseOut",
        }
    elif operation == "sale":
        name = f"Apartamento en venta en {locality}"
        offer = {
            "@type": "Offer",
            "price": price,
            "businessFunction": f"{_GOOD_RELATIONS}Sell",
        }
    else:
        name = f"Apartamento en {locality}"
        offer = {"@type": "Offer", "price": price}
    listing: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "RealEstateListing",
        "url": listing_url or f"{BASE_URL}/propiedad/inmueble-{code}",
        "name": name,
        "offers": offers if offers is not None else offer,
        "about": {
            "@type": "Apartment",
            "floorSize": {"@type": "QuantitativeValue", "value": area},
        },
        "numberOfBedrooms": rooms,
        "numberOfBathroomsTotal": baths,
        "amenityFeature": (
            [
                {
                    "@type": "LocationFeatureSpecification",
                    "name": "Parqueaderos",
                    "value": parking,
                }
            ]
            if include_parking
            else []
        ),
    }
    if not omit_address:
        listing["address"] = {
            "@type": "PostalAddress",
            "addressLocality": locality,
            "addressCountry": "CO",
        }
    if agent_locality:
        listing["provider"] = {
            "@type": "RealEstateAgent",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": agent_locality,
            },
        }
    # The real detail page carries the sector inside its primary description,
    # not in a labelled field.  A page without one uses generic lowercase
    # prose ("un sector residencial"), exactly like the live 9433 page.
    if description_heading is not None:
        heading = description_heading
    elif sector:
        heading = f"Apartamento en Arriendo – Sector {sector}, {locality}"
    else:
        heading = f"Apartamento en Arriendo – Unidad Residencial, {locality}"
    description = (
        f"<strong>{heading}</strong><br>Apartamento de aproximadamente {area} m², "
        "ubicado en un sector residencial tranquilo."
    )
    listing["description"] = description
    canonical = f"{BASE_URL}/propiedad/inmueble-{canonical_code or code}"
    extra_script = (
        f'<script type="application/ld+json">{json.dumps(related_listing)}</script>'
        if related_listing
        else ""
    )
    old_price = (
        f"<div><del>{_cop(old_visible)}</del><span>{_cop(price)}</span></div>"
        if old_visible
        else ""
    )
    return (
        "<html><head>"
        f'<link rel="canonical" href="{canonical}">'
        f'<meta property="og:url" content="{canonical}">'
        f'<script type="application/ld+json">{json.dumps(listing)}</script>'
        f"{extra_script}"
        f"<title>{name}</title>"
        "</head><body>"
        f"<h1>{name}</h1>"
        '<form class="searcher">'
        '<label for="location">Sector/Ubicación</label>'
        '<input type="text" name="location" placeholder="Busca por barrio o sitio">'
        "</form>"
        f"{old_price}"
        f"<div><span>Estrato:</span><span>{estrato}</span></div>"
        f'<div class="accordion"><p>{description}</p></div>'
        '<div class="relateds-list">'
        "<div>Estrato: 6</div><div>Sector: Wrong</div>"
        f"{_card('1111', tipo='Casa', price=900000, title_city='ENVIGADO')}"
        "</div>"
        "</body></html>"
    )


_LOADER_LOADING = (
    '<div class="property_loader">'
    '<img src="/img/loading.gif" style="width:16px;height:16px">'
    "</div>"
)
# The real site keeps the wrapper DIV mounted after the route completes and
# removes only the spinner IMG.
_LOADER_DONE = '<div class="property_loader"></div>'


def _loader_images(html: str) -> list[dict[str, object]]:
    """Render the loader selector against DOM markup the way the page would."""
    boxes: list[dict[str, object]] = []
    for image in BeautifulSoup(html, "html.parser").select(_LOADER_IMAGE_SELECTOR):
        style = str(image.get("style", "")).replace(" ", "")
        boxes.append(
            {
                "width": 0 if "width:0" in style else 16,
                "height": 0 if "height:0" in style else 16,
                "display": "none" if "display:none" in style else "block",
                "visibility": "hidden" if "visibility:hidden" in style else "visible",
            }
        )
    return boxes


class _FakeMouse:
    def __init__(self, page: "_FakePage") -> None:
        self.page = page

    def wheel(self, _x: int, _y: int) -> None:
        self.page.index = min(self.page.index + 1, len(self.page.states) - 1)


class _FakePage:
    """Minimal Playwright page double driven by explicit per-scroll states."""

    def __init__(self, states: list[list[str]], loaders: list[str]) -> None:
        assert len(states) == len(loaders)
        self.states = states
        self.loaders = loaders
        self.index = 0
        self.mouse = _FakeMouse(self)

    def evaluate(self, script: str):
        if "estate_itm" in script:
            return [{"text": "", "hrefs": [href]} for href in self.states[self.index]]
        return _loader_images(self.loaders[self.index])

    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None

    def on(self, *_args, **_kwargs) -> None:
        return None


def _hrefs(*codes: str) -> list[str]:
    return [f"/propiedad/apartamento-en-arriendo-{code}" for code in codes]


def _install_browser(monkeypatch, rendered: str, codes: tuple[str, ...]) -> None:
    def fake_fetch(_url, page_action):
        page_action(_FakePage([_hrefs(*codes)], [_LOADER_DONE]))
        return rendered

    monkeypatch.setattr(
        "scrape.inmobiliarialaestrella.stealthy_fetch_with_action", fake_fetch
    )


def _install_details(monkeypatch, details: dict[str, str]) -> list[str]:
    requested: list[str] = []

    def fake_bulk(urls, max_workers=None):
        requested.extend(urls)
        return [(url, details[url]) for url in urls]

    monkeypatch.setattr("scrape.inmobiliarialaestrella.bulk_fetch", fake_bulk)
    return requested


def test_card_code_can_come_from_visible_label() -> None:
    card = (
        '<div class="estate_itm">'
        "<div>Código: 9600</div>"
        '<a href="/propiedad/apartamento-en-arriendo-ditaires"><img></a>'
        "<h4>Apartamento en Arriendo - DITARES</h4>"
        "<div>Apartamento</div>"
        "<div>$ 2.800.000</div>"
        "<div>80 m²</div>"
        "<div>3 Alcobas</div>"
        "<div>2 Baños</div>"
        "<div>1 parq.</div>"
        "</div>"
    )

    rows = parse_search_html(_results(card))

    assert [row["id"] for row in rows] == ["LES-9600"]
    assert rows[0]["url"] == f"{BASE_URL}/propiedad/apartamento-en-arriendo-ditaires"


def test_cards_use_current_price_and_explicit_parking() -> None:
    html = _results(
        _card(_CODE_A, price=2700000, old_price=3000000, parking=2),
        extra=_card("2222", tipo="Casa", price=2300000, title_city="LA ESTRELLA"),
    )

    rows = parse_search_html(html)

    assert len(rows) == 2
    assert rows[0]["precio"] == 2700000
    assert rows[0]["parqueaderos"] == 2
    assert rows[0]["barrio"] == ""
    assert list(rows[0]) == list(COLUMNS)


def test_recommendation_cards_never_enter_results() -> None:
    recommendation = (
        '<div class="relateds-carousel">'
        + _card("3333", tipo="Casa", price=900000)
        + "</div>"
    )
    html = _results(_card(_CODE_A), extra=recommendation)

    rows = parse_search_html(html)

    assert [row["id"] for row in rows] == [f"LES-{_CODE_A}"]


def test_raw_mixed_types_do_not_collapse_to_casa() -> None:
    compound_with_generic_marker = (
        '<div class="estate_itm">'
        '<a href="/propiedad/casa-finca-en-arriendo-4005"><img></a>'
        "<h4>Casa-Finca en Arriendo - ITAGUI</h4>"
        "<div>Casa</div>"
        "<div>$ 5.000.000</div>"
        "<div>500 m²</div>"
        "</div>"
    )
    html = _results(
        _card("4001", tipo="Casa"),
        _card("4002", tipo="Casa-Finca"),
        _card("4003", tipo="Casa-Local"),
        _card("4004", tipo="Apartaestudio"),
        compound_with_generic_marker,
    )

    accepted, rejected = parse_search_report(html)

    assert {row["tipo"] for row in accepted} == {"casa", "apartaestudio"}
    assert {row["id"] for row in accepted} == {"LES-4001", "LES-4004"}
    assert rejected == {
        "4002": "unsupported-type",
        "4003": "unsupported-type",
        "4005": "unsupported-type",
    }


def test_detail_uses_jsonld_current_price_and_primary_estrato() -> None:
    html = _detail_html(
        _CODE_A,
        locality="Itagüí",
        price=2700000,
        old_visible=3000000,
        estrato=4,
        sector="Ditaires",
        related_listing={
            "@type": "RealEstateListing",
            "url": f"{BASE_URL}/propiedad/inmueble-9999",
            "address": {"addressLocality": "Envigado"},
            "offers": {"price": 5000000},
        },
    )

    detail = parse_detail(html, _CODE_A)

    assert detail["precio"] == 2700000
    assert detail["city_key"] == "itagui"
    assert detail["estrato"] == 4
    assert detail["barrio"] == "Ditaires"
    assert detail["operation"] == "rent"


def test_detail_parking_and_barrio_edge_cases() -> None:
    without_entry = _detail_html(_CODE_C, parking=0, include_parking=False, sector=None)
    explicit_zero = _detail_html(_CODE_C, parking=0, sector=None)

    omitted = parse_detail(without_entry, _CODE_C)
    explicit = parse_detail(explicit_zero, _CODE_C)

    assert omitted["parqueaderos"] == 0
    assert explicit["parqueaderos"] == 0
    assert omitted["barrio"] == ""
    assert explicit["barrio"] == ""


def test_detail_sector_comes_from_primary_description() -> None:
    html = _detail_html(_CODE_A, locality="Itagüí", sector="Ditaires")
    assert "Sector/Ubicación" in html

    detail = parse_detail(html, _CODE_A)

    assert detail["barrio"] == "Ditaires"


def test_detail_without_primary_sector_ignores_search_ui_caption() -> None:
    # The global search control is labelled "Sector/Ubicación"; the live 9433
    # page has no explicit sector, only generic "un sector residencial" prose.
    html = _detail_html(_CODE_C, locality="La Estrella", sector=None)
    assert "Sector/Ubicación" in html

    detail = parse_detail(html, _CODE_C)

    assert detail["barrio"] == ""


def test_detail_ignores_recommendation_sector() -> None:
    html = _detail_html(
        _CODE_C,
        locality="La Estrella",
        sector=None,
        related_listing={
            "@type": "RealEstateListing",
            "url": f"{BASE_URL}/propiedad/inmueble-9998",
            "description": "<strong>Apartamento – Sector Falso, Envigado</strong>",
            "address": {"addressLocality": "Envigado"},
            "offers": {"price": 1800000},
        },
    )

    detail = parse_detail(html, _CODE_C)

    assert detail["barrio"] == ""
    assert detail["city_key"] == "la-estrella"


def test_detail_documented_medellin_corregimiento_is_published() -> None:
    # Live 8187: addressLocality is the corregimiento, not the municipality.
    html = _detail_html(
        _CODE_A,
        locality="SAN ANTONIO DE PRADO",
        sector="Rosaleda",
    )

    detail = parse_detail(html, _CODE_A)

    assert detail["ciudad"] == "SAN ANTONIO DE PRADO"
    assert detail["city_key"] == "medellin"
    assert detail["barrio"] == "Rosaleda"


def test_detail_primary_heading_municipality_resolves_compound_locality() -> None:
    # Live 9454: addressLocality is "ITAGUI SANTA MARIA"; the property's own
    # title line names Itagüí, which is the authoritative primary evidence.
    html = _detail_html(
        _CODE_A,
        locality="ITAGUI SANTA MARIA",
        sector=None,
        description_heading=(
            "Apartamento en Arriendo – Edificio May, Sector Santa María, "
            "Itagüí (Piso 5)"
        ),
    )

    detail = parse_detail(html, _CODE_A)

    assert detail["ciudad"] == "ITAGUI SANTA MARIA"
    assert detail["city_key"] == "itagui"


def test_detail_heading_municipality_confirms_a_documented_alias() -> None:
    # Live 9612: the description names Medellín for a Guayabal locality.
    html = _detail_html(
        _CODE_A,
        locality="GUAYABAL",
        sector="Guayabal",
        description_heading=(
            "Apartamento en Arriendo – Urbanity, Sector Guayabal, Medellín (Piso 16)"
        ),
    )

    detail = parse_detail(html, _CODE_A)

    assert detail["city_key"] == "medellin"


def test_detail_unknown_locality_is_never_assumed_to_be_medellin() -> None:
    # Live 9695: Bariloche is an Itagüí sector.  Without primary municipality
    # evidence the label must stay unresolved instead of joining Medellín.
    html = _detail_html(_CODE_A, locality="BARILOCHE", sector=None)

    detail = parse_detail(html, _CODE_A)

    assert detail["city_key"] == "bariloche"


def test_detail_heading_municipality_must_agree_with_a_documented_alias() -> None:
    html = _detail_html(
        _CODE_A,
        locality="POBLADO",
        sector=None,
        description_heading=("Apartamento en Arriendo – Sector Falso, Itagüí (Piso 1)"),
    )

    with pytest.raises(PortalDetailError):
        parse_detail(html, _CODE_A)


def test_detail_identity_guard_rejects_other_code() -> None:
    html = _detail_html(_CODE_A)

    with pytest.raises(PortalDetailError):
        parse_detail(html, _CODE_B)


def test_loader_signal_is_the_image_not_the_persistent_wrapper() -> None:
    terminal = BeautifulSoup(_LOADER_DONE, "html.parser")
    assert terminal.select(_LOADER_IMAGE_SELECTOR) == []
    matched = BeautifulSoup(_LOADER_LOADING, "html.parser").select(
        _LOADER_IMAGE_SELECTOR
    )
    assert [tag.name for tag in matched] == ["img"]

    page = _FakePage(
        [_hrefs(_CODE_A), _hrefs(_CODE_A, _CODE_B)],
        [_LOADER_LOADING, _LOADER_DONE],
    )

    codes = _drain_results(page, batch_limit=None, tracker=None)

    assert codes == {_CODE_A, _CODE_B}


def test_discovery_fails_when_loader_image_never_disappears() -> None:
    page = _FakePage(
        [_hrefs(_CODE_A), _hrefs(_CODE_A)],
        [_LOADER_DONE, _LOADER_LOADING],
    )

    with pytest.raises(PortalDiscoveryError):
        _drain_results(page, batch_limit=None, tracker=None)


def test_hidden_loader_image_does_not_block_completion() -> None:
    hidden = (
        '<div class="property_loader">'
        '<img src="/img/loading.gif" style="width:0;height:0;display:none">'
        "</div>"
    )
    page = _FakePage(
        [_hrefs(_CODE_A), _hrefs(_CODE_A)],
        [_LOADER_LOADING, hidden],
    )

    codes = _drain_results(page, batch_limit=None, tracker=None)

    assert codes == {_CODE_A}


def test_full_discovery_is_not_capped_at_two_hundred_batches() -> None:
    codes = [str(6000 + index) for index in range(201)]
    states = [_hrefs(*codes[: index + 1]) for index in range(len(codes))]
    page = _FakePage(states, [_LOADER_DONE] * len(states))

    found = _drain_results(page, batch_limit=None, tracker=None)

    assert len(found) == len(codes)


def test_scrape_cities_groups_by_detail_municipality(monkeypatch) -> None:
    rendered = _results(
        _card(_CODE_A, title_city="ITAGUI"),
        _card(_CODE_B, title_city="ITAGUI"),
        _card(_CODE_C, tipo="Apartaestudio", title_city="LA ESTRELLA"),
    )
    _install_browser(monkeypatch, rendered, (_CODE_A, _CODE_B, _CODE_C))
    details = {
        f"{BASE_URL}/propiedad/apartamento-en-arriendo-{_CODE_A}": _detail_html(
            _CODE_A, locality="Itagüí", sector="Ditaires", price=2700000
        ),
        f"{BASE_URL}/propiedad/apartamento-en-arriendo-{_CODE_B}": _detail_html(
            _CODE_B,
            locality="La Estrella",
            sector="Ferrería",
            price=2300000,
            estrato=3,
        ),
        f"{BASE_URL}/propiedad/apartaestudio-en-arriendo-{_CODE_C}": _detail_html(
            _CODE_C,
            locality="La Estrella",
            sector=None,
            price=1700000,
            include_parking=False,
            area=50,
            rooms=2,
            estrato=3,
        ),
    }
    requested = _install_details(monkeypatch, details)

    rows = scrape_cities(["medellin", "itagui", "La Estrella"])

    assert set(rows) == {"medellin", "itagui", "la-estrella"}
    assert rows["medellin"] == []
    assert [row["id"] for row in rows["itagui"]] == [f"LES-{_CODE_A}"]
    assert {row["id"] for row in rows["la-estrella"]} == {
        f"LES-{_CODE_B}",
        f"LES-{_CODE_C}",
    }
    by_id = {row["id"]: row for row in rows["la-estrella"]}
    assert by_id[f"LES-{_CODE_B}"]["barrio"] == "Ferrería"
    assert by_id[f"LES-{_CODE_B}"]["precio"] == 2300000
    assert by_id[f"LES-{_CODE_C}"]["barrio"] == ""
    assert by_id[f"LES-{_CODE_C}"]["parqueaderos"] == 0
    assert by_id[f"LES-{_CODE_C}"]["area"] == 50
    assert len(requested) == 3
    assert all(list(row) == list(COLUMNS) for row in rows["la-estrella"])


def test_scrape_cities_publishes_verified_medellin_locality_only(monkeypatch) -> None:
    rendered = _results(
        _card(_CODE_A, title_city="SAN ANTONIO DE PRADO"),
        _card(_CODE_B, title_city="GUAYABAL"),
        _card(_CODE_C, title_city="BARILOCHE"),
    )
    _install_browser(monkeypatch, rendered, (_CODE_A, _CODE_B, _CODE_C))
    details = {
        f"{BASE_URL}/propiedad/apartamento-en-arriendo-{_CODE_A}": _detail_html(
            _CODE_A, locality="SAN ANTONIO DE PRADO", sector="Rosaleda"
        ),
        f"{BASE_URL}/propiedad/apartamento-en-arriendo-{_CODE_B}": _detail_html(
            _CODE_B,
            locality="GUAYABAL",
            sector="Guayabal",
            description_heading=(
                "Apartamento en Arriendo – Urbanity, Sector Guayabal, Medellín "
                "(Piso 16)"
            ),
        ),
        f"{BASE_URL}/propiedad/apartamento-en-arriendo-{_CODE_C}": _detail_html(
            _CODE_C, locality="BARILOCHE", sector=None
        ),
    }
    _install_details(monkeypatch, details)

    rows = scrape_cities(["medellin", "itagui"])

    assert {row["id"] for row in rows["medellin"]} == {
        f"LES-{_CODE_A}",
        f"LES-{_CODE_B}",
    }
    assert rows["itagui"] == []


def test_sale_detail_is_not_published(monkeypatch) -> None:
    rendered = _results(_card(_CODE_A, title_city="ITAGUI"))
    _install_browser(monkeypatch, rendered, (_CODE_A,))
    url = f"{BASE_URL}/propiedad/apartamento-en-arriendo-{_CODE_A}"
    _install_details(
        monkeypatch,
        {url: _detail_html(_CODE_A, locality="Itagüí", operation="sale")},
    )

    rows = scrape_cities(["itagui"])

    assert rows == {"itagui": []}


def test_unknown_operation_is_a_failure_not_a_rental_row(monkeypatch) -> None:
    rendered = _results(_card(_CODE_A, title_city="ITAGUI"))
    _install_browser(monkeypatch, rendered, (_CODE_A,))
    url = f"{BASE_URL}/propiedad/apartamento-en-arriendo-{_CODE_A}"
    _install_details(
        monkeypatch,
        {url: _detail_html(_CODE_A, locality="Itagüí", operation="unknown")},
    )

    with pytest.raises(PortalDetailError):
        scrape_cities(["itagui"])


def test_detail_operation_reads_offer_business_function() -> None:
    rent = parse_detail(_detail_html(_CODE_A, operation="rent"), _CODE_A)
    sale = parse_detail(_detail_html(_CODE_A, operation="sale"), _CODE_A)

    assert rent["operation"] == "rent"
    assert sale["operation"] == "sale"


def test_lease_out_price_wins_over_sell_offer() -> None:
    offers = [
        {
            "@type": "Offer",
            "price": 450000000,
            "businessFunction": f"{_GOOD_RELATIONS}Sell",
        },
        {
            "@type": "Offer",
            "price": 2700000,
            "businessFunction": f"{_GOOD_RELATIONS}LeaseOut",
        },
    ]

    detail = parse_detail(_detail_html(_CODE_A, offers=offers), _CODE_A)

    assert detail["precio"] == 2700000
    assert detail["operation"] == "rent"


def test_sell_price_never_prices_a_rental_listing() -> None:
    offers = [
        {
            "@type": "Offer",
            "price": 450000000,
            "businessFunction": f"{_GOOD_RELATIONS}Sell",
        },
        {
            "@type": "Offer",
            "businessFunction": f"{_GOOD_RELATIONS}LeaseOut",
        },
    ]

    with pytest.raises(PortalDetailError):
        parse_detail(_detail_html(_CODE_A, offers=offers), _CODE_A)


def test_foreign_jsonld_is_rejected_even_when_canonical_matches() -> None:
    html = _detail_html(
        _CODE_A,
        listing_url=f"{BASE_URL}/propiedad/inmueble-9999",
    )

    with pytest.raises(PortalDetailError):
        parse_detail(html, _CODE_A)


def test_agency_address_never_supplies_the_property_locality() -> None:
    html = _detail_html(
        _CODE_A,
        omit_address=True,
        agent_locality="Envigado",
    )

    with pytest.raises(PortalDetailError):
        parse_detail(html, _CODE_A)


def test_sample_mode_bounds_detail_fetches(monkeypatch) -> None:
    codes = ("5001", "5002", "5003", "5004")
    rendered = _results(*(_card(code) for code in codes))
    _install_browser(monkeypatch, rendered, codes)
    details = {
        f"{BASE_URL}/propiedad/apartamento-en-arriendo-{code}": _detail_html(
            code, locality="La Estrella", sector=None
        )
        for code in codes
    }
    requested = _install_details(monkeypatch, details)

    rows = scrape_cities(["La Estrella"], sample_only=True)

    assert len(requested) <= 3
    assert len(rows["la-estrella"]) == 3


def _url(code: str) -> str:
    return f"{BASE_URL}/propiedad/apartamento-en-arriendo-{code}"


def test_sample_mode_allocates_each_city_budget_before_fetching(monkeypatch) -> None:
    itagui_codes = ("5101", "5102", "5103", "5104", "5105", "5106")
    estrella_codes = ("5201", "5202", "5203")
    cards = [_card(code, title_city="ITAGUI") for code in itagui_codes] + [
        _card(code, title_city="LA ESTRELLA") for code in estrella_codes
    ]
    _install_browser(monkeypatch, _results(*cards), itagui_codes + estrella_codes)
    details = {
        _url(code): _detail_html(code, locality="Itagüí", sector=None)
        for code in itagui_codes
    }
    details.update(
        {
            _url(code): _detail_html(code, locality="La Estrella", sector=None)
            for code in estrella_codes
        }
    )
    requested = _install_details(monkeypatch, details)

    rows = scrape_cities(["itagui", "la-estrella"], sample_only=True)

    assert len(requested) == 6
    assert {row["id"] for row in rows["itagui"]} == {
        f"LES-{code}" for code in itagui_codes[:3]
    }
    assert {row["id"] for row in rows["la-estrella"]} == {
        f"LES-{code}" for code in estrella_codes
    }


def test_sample_plan_reserves_a_budget_per_city_without_hints() -> None:
    codes = ("5401", "5402", "5403", "5404", "5405", "5406", "5407")
    cards = parse_search_html(_results(*(_card(code) for code in codes)))

    plan = _sample_plan(cards, {}, ["itagui", "la-estrella"])

    assert [card["id"] for card in plan[:3]] == ["LES-5401", "LES-5403", "LES-5405"]
    assert [card["id"] for card in plan[3:]] == ["LES-5402", "LES-5404", "LES-5406"]


def test_detail_municipality_overrides_the_card_hint(monkeypatch) -> None:
    _install_browser(
        monkeypatch,
        _results(_card("5301", title_city="LA ESTRELLA")),
        ("5301",),
    )
    _install_details(
        monkeypatch,
        {_url("5301"): _detail_html("5301", locality="Itagüí", sector=None)},
    )

    rows = scrape_cities(["itagui"], sample_only=True)

    assert [row["id"] for row in rows["itagui"]] == ["LES-5301"]


def test_invalid_city_and_page_bound_are_rejected() -> None:
    with pytest.raises(ValueError):
        scrape_cities(["bogota"])
    with pytest.raises(ValueError):
        scrape_cities(["medellin"], max_pages=0)


def test_cli_canonicalizes_city_scope(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_scrape(**kwargs):
        captured.update(kwargs)
        return []

    def fake_run_scraper(scraper_fn, portal, args):
        captured["scope"] = args.ciudad
        scraper_fn()
        return 0

    monkeypatch.setattr(cli, "scrape", fake_scrape)
    monkeypatch.setattr(cli, "run_scraper", fake_run_scraper)
    args = argparse.Namespace(
        portal="inmobiliarialaestrella",
        output="both",
        ciudad="La Estrella",
        sample_only=True,
        max_pages=1,
        verbose=False,
    )

    assert cli.main(args) == 0
    assert captured["scope"] == "la-estrella"
    assert captured["ciudad"] == "la-estrella"
