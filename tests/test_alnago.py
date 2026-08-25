"""Regression tests for the current Alnago homepage card markup."""

from pathlib import Path

from scrapling import Selector

from scrape.alnago import _extract_detail_fields, _extract_homepage_cards


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "alnago"


def test_extracts_current_homepage_cards_without_article_elements() -> None:
    response = Selector((FIXTURES / "homepage_cards.html").read_text(encoding="utf-8"))

    rows = _extract_homepage_cards(response)

    assert [row["id"] for row in rows] == ["ALN-10302885", "ALN-10314121"]
    assert [row["tipo"] for row in rows] == ["apartamento", "apartamento"]
    assert [row["precio"] for row in rows] == [1600000, 3100000]
    assert [row["habitaciones"] for row in rows] == [2, 3]
    assert [row["banos"] for row in rows] == [2, 2]
    assert [row["parqueaderos"] for row in rows] == [0, 1]
    assert [row["area"] for row in rows] == [50, 55]
    assert [row["barrio"] for row in rows] == ["El Carmelo", "San Diego"]


def test_detail_parser_uses_structured_plural_garages_before_feature_text() -> None:
    detail = """
    <main>
      <div>Garajes</div>
      <div>1</div>
      <h2>Características externas</h2>
      <div>Garaje</div>
      <div>Gimnasio</div>
    </main>
    """

    assert _extract_detail_fields(detail)["parqueaderos"] == 1
