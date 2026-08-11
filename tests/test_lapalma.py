"""Fixture-backed tests for the La Palma two-phase scraper."""

import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from scrape.lapalma import (
    RESIDENTIAL_TYPES,
    build_page_url,
    parse_detail_page,
    parse_search_page,
    scrape,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lapalma"
CANONICAL_COLUMNS = [
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
]


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestSearchCardParsing(unittest.TestCase):
    """Search cards expose card fields and exclude source-marked rentals."""

    def test_maps_cards_and_excludes_alquilado(self):
        rows = parse_search_page(_load("search_page.html"))

        self.assertEqual([row["id"] for row in rows], ["LPI-10255187", "LPI-10254920"])
        self.assertEqual(list(rows[0]), CANONICAL_COLUMNS)
        self.assertEqual(
            rows[0],
            {
                "id": "LPI-10255187",
                "portal": "lapalmainmobiliaria",
                "tipo": "apartamento",
                "precio": 1400000,
                "area": 40,
                "habitaciones": 2,
                "banos": 1,
                "parqueaderos": 0,
                "estrato": 0,
                "barrio": "",
                "url": "https://lapalmainmobiliaria.com.co/apartamento-arriendo-villa-hermosa-medellin/10255187",
            },
        )
        self.assertEqual(rows[1]["tipo"], "apartaestudio")
        self.assertEqual(rows[1]["banos"], 0)
        self.assertEqual(rows[1]["parqueaderos"], 0)
        self.assertNotIn("LPI-10299999", {row["id"] for row in rows})

    def test_casa_comercial_never_reaches_detail_fetching(self):
        rows = parse_search_page(_load("search_page_casa_commercial.html"))

        self.assertEqual([row["id"] for row in rows], ["LPI-10017303", "LPI-9938605"])
        self.assertEqual(rows[0]["tipo"], "")
        self.assertEqual(rows[1]["tipo"], "casa")

        with (
            mock.patch("scrape.lapalma._phase_a", return_value=rows),
            mock.patch("scrape.lapalma.bulk_fetch", return_value=[]) as bulk_mock,
        ):
            result = scrape()

        self.assertEqual([row["id"] for row in result], ["LPI-9938605"])
        self.assertEqual(
            bulk_mock.call_args.args[0],
            ["https://lapalmainmobiliaria.com.co/casa-arriendo-laureles-medellin/9938605"],
        )


class TestDetailParsing(unittest.TestCase):
    """Detail pages supply the fields absent from cards."""

    def test_extracts_explicit_estrato_and_zona(self):
        self.assertEqual(
            parse_detail_page(_load("detail_villa_hermosa.html")),
            {"estrato": 3, "barrio": "Villa Hermosa"},
        )

    def test_absent_detail_fields_are_proven_defaults(self):
        self.assertEqual(
            parse_detail_page(_load("detail_missing_fields.html")),
            {"estrato": 0, "barrio": ""},
        )


class TestTwoPhasePagination(unittest.TestCase):
    """Phase A paginates safely, then Phase B merges only detail fields."""

    def test_unions_type_sources_deduplicates_and_excludes_commercial_detail(self):
        source_pages = {
            "2": _load("search_page.html"),
            "1": _load("search_page_2.html"),
            "14": _load("search_page_commercial_leak.html"),
        }
        detail_html = {
            "https://lapalmainmobiliaria.com.co/apartamento-arriendo-villa-hermosa-medellin/10255187": _load(
                "detail_villa_hermosa.html"
            ),
            "https://lapalmainmobiliaria.com.co/casa-arriendo-laureles-medellin/9938605": _load(
                "detail_house.html"
            ),
        }

        def fetch_by_type(url: str) -> str:
            query = parse_qs(urlparse(url).query)
            return source_pages[query["id_property_type"][0]]

        with (
            mock.patch("scrape.lapalma.fetch_page", side_effect=fetch_by_type) as fetch_mock,
            mock.patch(
                "scrape.lapalma.bulk_fetch", return_value=list(detail_html.items())
            ) as bulk_mock,
        ):
            rows = scrape(max_pages=1)

        self.assertEqual(
            [row["id"] for row in rows],
            [
                "LPI-10255187",
                "LPI-10254920",
                "LPI-9938605",
                "LPI-10236679",
            ],
        )
        self.assertTrue({row["tipo"] for row in rows} <= set(RESIDENTIAL_TYPES))
        self.assertEqual(len({row["id"] for row in rows}), len(rows))

        requested_urls = [call.args[0] for call in fetch_mock.call_args_list]
        self.assertEqual(len(requested_urls), 3)
        for property_type, url in zip(RESIDENTIAL_TYPES, requested_urls):
            query = parse_qs(urlparse(url).query)
            self.assertEqual(query["id_property_type"], [{"apartamento": "2", "casa": "1", "apartaestudio": "14"}[property_type]])
            self.assertEqual(query["page"], ["1"])
            self.assertEqual(query["id_city"], ["496"])
            self.assertEqual(query["business_type[0]"], ["for_rent"])
            self.assertEqual(query["order_by"], ["created_at"])
            self.assertEqual(query["order"], ["desc"])
            self.assertEqual(query["for_sale"], ["0"])
            self.assertEqual(query["for_rent"], ["1"])
            self.assertEqual(query["for_temporary_rent"], ["0"])
            self.assertEqual(query["for_transfer"], ["0"])
            self.assertEqual(query["lax_business_type"], ["1"])

        bulk_mock.assert_called_once()
        detail_urls = bulk_mock.call_args.args[0]
        self.assertEqual(len(detail_urls), 4)
        self.assertNotIn("/10075954", " ".join(detail_urls))
        self.assertNotIn("/10299999", " ".join(detail_urls))

    def test_each_type_stream_stops_at_empty_page(self):
        def fetch_until_empty(url: str) -> str:
            query = parse_qs(urlparse(url).query)
            return _load("search_page.html") if query["page"] == ["1"] else _load("empty_page.html")

        with (
            mock.patch("scrape.lapalma.fetch_page", side_effect=fetch_until_empty) as fetch_mock,
            mock.patch("scrape.lapalma.bulk_fetch", return_value=[]),
        ):
            rows = scrape()

        self.assertEqual(len(rows), 2)
        self.assertEqual(len(fetch_mock.call_args_list), 6)

    def test_final_residential_guard_runs_before_detail_batch(self):
        residential = parse_search_page(_load("search_page.html"))[0]
        commercial = dict(residential)
        commercial.update({
            "id": "LPI-10075954",
            "tipo": "local",
            "url": "https://lapalmainmobiliaria.com.co/local-arriendo-la-candelaria-medellin/10075954",
        })

        with (
            mock.patch("scrape.lapalma._phase_a", return_value=[residential, commercial]),
            mock.patch("scrape.lapalma.bulk_fetch", return_value=[]) as bulk_mock,
        ):
            rows = scrape()

        self.assertEqual([row["id"] for row in rows], ["LPI-10255187"])
        self.assertEqual(bulk_mock.call_args.args[0], [residential["url"]])

    def test_page_url_uses_official_rental_endpoint(self):
        for property_type, property_id in {"apartamento": "2", "casa": "1", "apartaestudio": "14"}.items():
            url = build_page_url(4, property_type=property_type)
            self.assertEqual(urlparse(url).path, "/search")
            query = parse_qs(urlparse(url).query)
            self.assertEqual(query["page"], ["4"])
            self.assertEqual(query["id_property_type"], [property_id])
            self.assertEqual(query["id_city"], ["496"])
            self.assertEqual(query["business_type[0]"], ["for_rent"])


if __name__ == "__main__":
    unittest.main()
