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
