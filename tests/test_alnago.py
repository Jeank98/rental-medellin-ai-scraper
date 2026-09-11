"""Regression tests for the current Alnago homepage card markup."""

from pathlib import Path
from unittest import mock

from scrapling import Selector

from scrape.alnago import (
    _extract_detail_fields,
    _extract_homepage_cards,
    scrape,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "alnago"


def _listing(listing_id: str, price: int) -> dict:
    return {
        "id": listing_id,
        "portal": "alnago",
        "tipo": "apartamento",
        "precio": price,
        "area": 50,
        "habitaciones": 2,
        "banos": 1,
        "parqueaderos": 0,
        "estrato": 0,
        "barrio": "Laureles",
        "url": f"https://alnago.com/es/inmueble/{listing_id.removeprefix('ALN-')}",
    }


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


def test_rejects_current_sale_cards_before_detail_enrichment() -> None:
    response = Selector(
        """
        <section>
          <a href="/en/inmueble/1">
            <span>Rent</span><span>$ 1.000.000/mo</span>
            <span>Apartamento en arriendo en Laureles</span>
            <span>Laureles, Medellín</span><span>2</span><span>1</span>
            <span>0</span><span>50 m²</span>
          </a>
          <a href="/en/inmueble/2">
            <span>Sale</span><span>$ 1.000.000/mo</span>
            <span>Apartamento en venta en Laureles</span>
            <span>Laureles, Medellín</span><span>2</span><span>1</span>
            <span>0</span><span>50 m²</span>
          </a>
        </section>
        """
    )

    assert [row["id"] for row in _extract_homepage_cards(response)] == ["ALN-1"]


def test_reuses_unchanged_details_and_fetches_only_price_misses() -> None:
    reused = _listing("ALN-1", 1_500_000)
    changed = _listing("ALN-2", 1_600_000)
    previous = {
        "ALN-1": {
            **reused,
            "tipo": "casa",
            "area": 99,
            "estrato": 6,
            "parqueaderos": 2,
        },
        "ALN-2": {**changed, "precio": 1_500_000},
    }
    fresh_detail = {
        "tipo": "apartamento",
        "area": 60,
        "estrato": 4,
        "parqueaderos": 1,
    }

    with (
        mock.patch("scrape.alnago.Fetcher.get", return_value=mock.Mock(status=200)),
        mock.patch(
            "scrape.alnago._extract_homepage_cards",
            return_value=[reused, changed],
        ),
        mock.patch("db.get_active_listings_by_id", return_value=previous) as snapshot,
        mock.patch(
            "scrape.alnago.bulk_fetch",
            return_value=[(changed["url"], "changed")],
        ) as detail_fetch,
        mock.patch(
            "scrape.alnago._extract_detail_fields",
            return_value=fresh_detail,
        ),
    ):
        rows = scrape(reuse_unchanged_details=True)

    snapshot.assert_called_once_with("alnago", "medellin")
    detail_fetch.assert_called_once_with([changed["url"]])
    by_id = {row["id"]: row for row in rows}
    assert by_id["ALN-1"]["tipo"] == "casa"
    assert by_id["ALN-1"]["area"] == 99
    assert by_id["ALN-1"]["estrato"] == 6
    assert by_id["ALN-1"]["parqueaderos"] == 2
    assert by_id["ALN-2"]["area"] == 60
    assert by_id["ALN-2"]["estrato"] == 4


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
