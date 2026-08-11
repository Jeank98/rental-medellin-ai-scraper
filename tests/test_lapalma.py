"""Fixture-backed tests for the La Palma two-phase scraper."""

import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from scrape.lapalma import (
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

    def test_preserves_filters_deduplicates_and_stops_at_empty_page(self):
        search_pages = [
            _load("search_page.html"),
            _load("search_page_2.html"),
            _load("empty_page.html"),
        ]
        detail_html = {
            "https://lapalmainmobiliaria.com.co/apartamento-arriendo-villa-hermosa-medellin/10255187": _load(
                "detail_villa_hermosa.html"
            ),
            "https://lapalmainmobiliaria.com.co/casa-arriendo-laureles-medellin/9938605": _load(
                "detail_house.html"
            ),
        }

        with (
            mock.patch(
                "scrape.lapalma.fetch_page", side_effect=search_pages
            ) as fetch_mock,
            mock.patch(
                "scrape.lapalma.bulk_fetch", return_value=list(detail_html.items())
            ) as bulk_mock,
        ):
            rows = scrape(sample_only=True)

        self.assertEqual(
            [row["id"] for row in rows],
            [
                "LPI-10255187",
                "LPI-10254920",
                "LPI-9938605",
            ],
        )
        self.assertEqual(rows[0]["estrato"], 3)
        self.assertEqual(rows[0]["barrio"], "Villa Hermosa")
        self.assertEqual(rows[1]["estrato"], 0)
        self.assertEqual(rows[1]["barrio"], "")
        self.assertEqual(rows[2]["estrato"], 5)
        self.assertEqual(rows[2]["barrio"], "Laureles")
        self.assertEqual(len({row["id"] for row in rows}), len(rows))

        requested_urls = [call.args[0] for call in fetch_mock.call_args_list]
        self.assertEqual(len(requested_urls), 3)
        for page, url in enumerate(requested_urls, start=1):
            query = parse_qs(urlparse(url).query)
            self.assertEqual(query["page"], [str(page)])
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
        self.assertEqual(len(detail_urls), 3)

    def test_page_url_uses_official_rental_endpoint(self):
        url = build_page_url(4)
        self.assertEqual(urlparse(url).path, "/search")
        self.assertEqual(parse_qs(urlparse(url).query)["page"], ["4"])


if __name__ == "__main__":
    unittest.main()
