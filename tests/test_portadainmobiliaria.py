"""Fixture-backed tests for the Portada Inmobiliaria REST scraper."""

import json
import unittest
from pathlib import Path
from unittest import mock

from scrape.portadainmobiliaria import (
    API_HEADERS,
    COLUMNS,
    RESIDENTIAL_TYPES,
    build_api_url,
    deduplicate_listings,
    parse_search_response,
    scrape,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "portadainmobiliaria"


def _load_fixture(name: str) -> dict:
    """Load a Portada JSON fixture."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestPortadaResponseParser(unittest.TestCase):
    """Structured API records map directly to the output contract."""

    def test_apartment_page_maps_all_contract_fields(self):
        rows = parse_search_response(
            _load_fixture("apartamento_page1.json"),
            expected_tipo="apartamento",
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(list(rows[0]), list(COLUMNS))
        self.assertEqual(
            rows[0],
            {
                "id": "POR-679-78592",
                "portal": "portadainmobiliaria",
                "tipo": "apartamento",
                "precio": 1950000,
                "area": 55,
                "habitaciones": 3,
                "banos": 2,
                "parqueaderos": 1,
                "estrato": 3,
                "barrio": "Robledo",
                "url": "https://portadainmobiliaria.com/busqueda/#/inmueble/679-78592",
            },
        )

    def test_house_and_apartaestudio_type_mappings(self):
        house = parse_search_response(
            _load_fixture("casa_page1.json"), expected_tipo="casa"
        )[0]
        studio = parse_search_response(
            _load_fixture("apartaestudio_page1.json"),
            expected_tipo="apartaestudio",
        )[0]

        self.assertEqual(house["tipo"], "casa")
        self.assertEqual(house["parqueaderos"], 2)
        self.assertEqual(studio["tipo"], "apartaestudio")
        self.assertEqual(studio["parqueaderos"], 0)

    def test_numeric_contract_fields_are_integers(self):
        rows = parse_search_response(_load_fixture("apartamento_page1.json"))

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

    def test_textual_api_error_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Don't have access"):
            parse_search_response(_load_fixture("error.json"))


class TestPortadaPagination(unittest.TestCase):
    """Type routes and page limits remain bounded and deterministic."""

    def test_api_url_uses_path_parameters_and_public_auth(self):
        url = build_api_url(1, RESIDENTIAL_TYPES["apartamento"])

        self.assertIn("/limite/1/total/12/", url)
        self.assertIn("/ciudad/25974/barrio/0/tipoInm/1/", url)
        self.assertTrue(API_HEADERS["Authorization"].startswith("Basic "))
        self.assertEqual(url.count("?"), 0)

    def test_sample_only_fetches_one_page_per_type(self):
        responses = [
            _load_fixture("apartamento_page1.json"),
            _load_fixture("casa_page1.json"),
            _load_fixture("apartaestudio_page1.json"),
        ]

        with mock.patch(
            "scrape.portadainmobiliaria.fetch_json", side_effect=responses
        ) as fetch:
            rows = scrape(sample_only=True)

        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["portal"] == "portadainmobiliaria" for row in rows))

    def test_max_pages_and_deduplication_keep_first_seen_row(self):
        responses = [
            _load_fixture("apartamento_page1.json"),
            _load_fixture("apartamento_page2.json"),
            _load_fixture("casa_page1.json"),
            _load_fixture("apartaestudio_page1.json"),
        ]

        with mock.patch(
            "scrape.portadainmobiliaria.fetch_json", side_effect=responses
        ) as fetch:
            rows = scrape(max_pages=2)

        self.assertEqual(fetch.call_count, 4)
        self.assertEqual(
            [row["id"] for row in rows],
            [
                "POR-679-78592",
                "POR-679-78569",
                "POR-679-78554",
                "POR-679-78543",
                "POR-679-78575",
            ],
        )
        self.assertEqual(rows[0]["precio"], 1950000)
        self.assertEqual(fetch.call_args_list[0].args[0], build_api_url(1, 1))
        self.assertEqual(fetch.call_args_list[1].args[0], build_api_url(2, 1))
        self.assertEqual(fetch.call_args_list[0].kwargs["headers"], API_HEADERS)

    def test_deduplicate_listings_keeps_first_row(self):
        first = parse_search_response(_load_fixture("apartamento_page1.json"))[0]
        duplicate = dict(first)
        duplicate["precio"] = 1

        rows = deduplicate_listings([first, duplicate])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["precio"], 1950000)

    def test_only_medellin_is_supported(self):
        with self.assertRaisesRegex(ValueError, "only supports Medellin"):
            scrape(ciudad="bogota")


if __name__ == "__main__":
    unittest.main()
