"""Regression tests for the current Alberto Alvarez card structure."""

from unittest import mock

from scrape.albertoalvarez import parse_search_page, scrape


def test_parses_current_visible_text_result_card() -> None:
    html = """
    <div class="result-card">
      <a href="/inmuebles/detalle/arrendamientos/apartamento/AA-95022/laureles-medellin">
        Ven y disfruta de este apartamento
      </a>
      <span>Cod: AA-95022</span>
      <h3>laureles, medellín</h3>
      <span>$4.500.000</span><span>COP</span>
      <span>53</span><span>Metros</span>
      <span>2</span><span>Baños</span>
      <span>1</span><span>Alcobas</span>
    </div>
    """

    rows = parse_search_page(html, "apartamento")

    assert rows == [{
        "id": "AAL-AA-95022",
        "portal": "albertoalvarez",
        "tipo": "apartamento",
        "precio": 4500000,
        "area": 53,
        "habitaciones": 1,
        "banos": 2,
        "parqueaderos": 0,
        "estrato": 0,
        "barrio": "Laureles",
        "url": "https://albertoalvarez.com/inmuebles/detalle/arrendamientos/apartamento/AA-95022/laureles-medellin",
    }]


def test_stops_when_modern_pagination_repeats_the_last_page() -> None:
    html = """
    <div class="result-card">
      <a href="/inmuebles/detalle/arrendamientos/apartamento/AA-95022/laureles-medellin">Apartamento</a>
      <span>Cod: AA-95022</span><h3>laureles, medellín</h3>
      <span>$4.500.000</span><span>53</span><span>Metros</span>
      <span>2</span><span>Baños</span><span>1</span><span>Alcobas</span>
    </div>
    """

    with mock.patch("scrape.albertoalvarez.fetch_page", return_value=html) as fetch:
        rows = scrape(max_pages=5)

    assert len(rows) == 1
    assert fetch.call_count == 4


def test_description_with_dollar_sign_never_becomes_the_price() -> None:
    """A description containing "$1.850.000" used to be concatenated with the
    area/card numbers and produced an out-of-range integer."""
    html = """
    <div class="result-card">
      <a href="/inmuebles/detalle/arrendamientos/apartaestudio/AA-93627/centro-medellin">
        Se arrienda apartaestudio de 45m, a 1 cuadra del parque de Boston.
        Valor de Arrendamiento $1.850.000 incluida administración
      </a>
      <span>Cod: AA-93627</span>
      <h3>centro, medellín</h3>
      <span>$</span><span>1.850.000</span><span>COP</span>
      <span>45</span><span>Metros</span>
      <span>1</span><span>Baños</span>
      <span>1</span><span>Alcobas</span>
    </div>
    """

    rows = parse_search_page(html, "apartaestudio")

    assert [row["precio"] for row in rows] == [1_850_000]
    assert rows[0]["area"] == 45
    assert rows[0]["barrio"] == "Centro"


def test_out_of_range_price_skips_the_listing() -> None:
    html = """
    <div class="result-card">
      <a href="/inmuebles/detalle/arrendamientos/apartaestudio/AA-1/centro-medellin">
        Apartaestudio con excelente ubicación
      </a>
      <span>Cod: AA-1</span>
      <h3>centro, medellín</h3>
      <span>$</span><span>4.511.850.000</span><span>COP</span>
      <span>45</span><span>Metros</span>
    </div>
    """

    assert parse_search_page(html, "apartaestudio") == []


def test_search_url_paginates_with_the_page_parameter() -> None:
    """Page 1 is the bare grid; later pages only paginate with ``page``."""
    from scrape.albertoalvarez import _search_url

    assert _search_url("apartamento", "medellin", 1).endswith("?limit=9")
    assert _search_url("apartamento", "medellin", 2).endswith("?limit=9&page=2")
    assert "pag=" not in _search_url("apartamento", "medellin", 3)
