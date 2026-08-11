"""Fixture-backed tests for the Total Bienes one-phase scraper."""

import unittest
from pathlib import Path
from unittest import mock

from scrape.totalbienes import (
    CANONICAL_PAGE_URLS,
    RESIDENTIAL_TYPE_URLS,
    RESIDENTIAL_TYPES,
    deduplicate_listings,
    filter_residential_listings,
    parse_search_page,
    scrape,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "totalbienes"
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


def _load_fixture(name: str) -> str:
    """Load a Total Bienes HTML fixture."""
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestTotalBienesCardParser(unittest.TestCase):
    """Card parsing covers residential, mixed-offer, and sparse cards."""

    def test_page_one_maps_all_contract_fields(self):
        listings = parse_search_page(_load_fixture("page1.html"))

        self.assertEqual(len(listings), 3)
        for row in listings:
            self.assertEqual(list(row), CANONICAL_COLUMNS)
        self.assertEqual(
            listings[0],
            {
                "id": "TB-1305",
                "portal": "totalbienes",
                "tipo": "apartamento",
                "precio": 2400000,
                "area": 65,
                "habitaciones": 3,
                "banos": 2,
                "parqueaderos": 1,
                "estrato": 4,
                "barrio": "Calasanz",
                "url": "https://totalbienes.com/property/1305",
            },
        )

    def test_mixed_offer_uses_rental_price(self):
        row = parse_search_page(_load_fixture("page1.html"))[1]

        self.assertEqual(row["id"], "TB-1220")
        self.assertEqual(row["precio"], 5600000)
        self.assertEqual(row["tipo"], "apartamento")

    def test_non_residential_missing_bedrooms_is_zero(self):
        row = parse_search_page(_load_fixture("page1.html"))[2]

        self.assertEqual(row["id"], "TB-1403")
        self.assertEqual(row["tipo"], "local")
        self.assertEqual(row["habitaciones"], 0)
        self.assertEqual(row["parqueaderos"], 0)
        self.assertEqual(row["banos"], 1)

    def test_numeric_contract_fields_are_integers(self):
        rows = parse_search_page(_load_fixture("page1.html"))

        for row in rows:
            for field in (
                "precio",
                "area",
                "habitaciones",
                "banos",
                "parqueaderos",
                "estrato",
            ):
                self.assertIsInstance(row[field], int)

    def test_aria_labels_supply_icon_only_fields(self):
        row = parse_search_page(_load_fixture("aria_card.html"))[0]

        self.assertEqual(row["habitaciones"], 3)
        self.assertEqual(row["banos"], 2)
        self.assertEqual(row["parqueaderos"], 1)
        self.assertEqual(row["area"], 65)
        self.assertEqual(row["estrato"], 4)


class TestTotalBienesPagination(unittest.TestCase):
    """The scraper unions residential routes with numbered city routes."""

    def test_residential_type_urls_are_official_and_ordered(self):
        self.assertEqual(
            RESIDENTIAL_TYPE_URLS,
            (
                "https://totalbienes.com/arriendo-apartamentos-medellin",
                "https://totalbienes.com/arriendo-casas-medellin",
                "https://totalbienes.com/arriendo-apartaestudios-medellin",
            ),
        )
        self.assertEqual(RESIDENTIAL_TYPES, {"apartamento", "casa", "apartaestudio"})

    def test_canonical_urls_are_literal_and_ordered(self):
        self.assertEqual(
            CANONICAL_PAGE_URLS,
            (
                "https://totalbienes.com/properties/medellin",
                "https://totalbienes.com/properties/medellin/pagina/2",
            ),
        )

    def test_scrape_unions_type_routes_and_numbered_pages(self):
        apartments = _load_fixture("apartments.html")
        houses = _load_fixture("houses.html")
        apartaestudios = _load_fixture("apartaestudios.html")
        page1 = _load_fixture("page1.html")
        page2 = _load_fixture("page2.html")

        with mock.patch(
            "scrape.totalbienes.fetch_page",
            side_effect=[
                apartments,
                houses,
                apartaestudios,
                page1,
                page2,
            ],
        ) as fetch:
            rows = scrape()

        expected_urls = [*RESIDENTIAL_TYPE_URLS, *CANONICAL_PAGE_URLS]
        self.assertEqual(
            fetch.call_args_list, [mock.call(url) for url in expected_urls]
        )
        self.assertEqual(
            [row["id"] for row in rows],
            ["TB-1305", "TB-1220", "TB-1165", "TB-1278", "TB-1215"],
        )
        self.assertTrue(
            all("load" not in call.args[0].lower() for call in fetch.call_args_list)
        )
        self.assertTrue(all(row["tipo"] in RESIDENTIAL_TYPES for row in rows))

    def test_sample_only_keeps_type_sources_and_first_numbered_page(self):
        fixtures = [
            _load_fixture("apartments.html"),
            _load_fixture("houses.html"),
            _load_fixture("apartaestudios.html"),
            _load_fixture("page1.html"),
        ]

        with mock.patch("scrape.totalbienes.fetch_page", side_effect=fixtures) as fetch:
            rows = scrape(sample_only=True)

        self.assertEqual(
            fetch.call_args_list,
            [
                mock.call(url)
                for url in [
                    *RESIDENTIAL_TYPE_URLS,
                    CANONICAL_PAGE_URLS[0],
                ]
            ],
        )
        self.assertEqual(len(rows), 4)

    def test_max_pages_limits_numbered_boundary(self):
        fixtures = [
            _load_fixture("apartments.html"),
            _load_fixture("houses.html"),
            _load_fixture("apartaestudios.html"),
            _load_fixture("page1.html"),
        ]

        with mock.patch("scrape.totalbienes.fetch_page", side_effect=fixtures) as fetch:
            rows = scrape(max_pages=1)

        self.assertEqual(
            fetch.call_args_list,
            [
                mock.call(url)
                for url in [
                    *RESIDENTIAL_TYPE_URLS,
                    CANONICAL_PAGE_URLS[0],
                ]
            ],
        )
        self.assertEqual(len(rows), 4)

    def test_non_residential_types_are_excluded_before_output(self):
        rows = parse_search_page(_load_fixture("non_residential.html"))

        self.assertEqual([row["tipo"] for row in rows], ["local", "oficina", "bodega"])
        self.assertEqual(filter_residential_listings(rows), [])

    def test_duplicate_ids_keep_first_seen_row(self):
        page1_rows = parse_search_page(_load_fixture("page1.html"))
        page2_rows = parse_search_page(_load_fixture("page2.html"))
        duplicate = dict(page1_rows[0])
        duplicate["precio"] = 1

        rows = deduplicate_listings(page1_rows + page2_rows + [duplicate])

        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["precio"], 2400000)
        self.assertEqual(
            [row["id"] for row in rows],
            [
                "TB-1305",
                "TB-1220",
                "TB-1403",
                "TB-1215",
                "TB-1165",
            ],
        )


if __name__ == "__main__":
    unittest.main()
