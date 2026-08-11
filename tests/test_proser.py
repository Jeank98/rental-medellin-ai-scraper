"""Fixture-backed tests for the Proser two-phase scraper."""

import logging
import unittest
from pathlib import Path
from unittest import mock

from scrape.proserinmobiliaria import (
    COLUMNS,
    RESIDENTIAL_SOURCE_URLS,
    merge_detail,
    parse_detail_page,
    parse_search_page,
    scrape,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "proser"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestSearchParsing(unittest.TestCase):
    """Search cards provide the stable ID and rental-facing fields."""

    def test_maps_rental_offer_and_inferred_barrio(self):
        rows, pages = parse_search_page(_load("search_page_1.html"))

        self.assertEqual(pages, {1, 2, 3, 4})
        self.assertEqual(len(rows), 2)
        row = rows[0]
        self.assertEqual(list(row), COLUMNS)
        self.assertEqual(row, {
            "id": "PRO-10205313",
            "portal": "proserinmobiliaria",
            "tipo": "apartamento",
            "precio": 6900000,
            "area": 136,
            "habitaciones": 4,
            "banos": 2,
            "parqueaderos": 2,
            "estrato": 0,
            "barrio": "Poblado",
            "url": "https://proserinmobiliaria.com/apartamento-venta-poblado-medellin/10205313",
        })

    def test_marketplace_is_rejected_by_default(self):
        rows, _ = parse_search_page(_load("search_page_1.html"))

        self.assertNotIn("PRO-9483657", {row["id"] for row in rows})

    def test_fractional_bathroom_uses_documented_half_up_policy(self):
        with self.assertLogs("scrape.proserinmobiliaria", level=logging.WARNING) as logs:
            rows, _ = parse_search_page(_load("search_page_fractional.html"))

        self.assertEqual(rows[0]["banos"], 3)
        self.assertIn("ROUND_HALF_UP", " ".join(logs.output))

    def test_compound_house_type_maps_to_contract_type(self):
        html = _load("search_page_fractional.html").replace("APARTAMENTO", "CASA CAMPESTRE", 1)

        rows, _ = parse_search_page(html)

        self.assertEqual(rows[0]["tipo"], "casa")

    def test_residential_sources_use_city_type_and_rent_parameters(self):
        self.assertEqual(
            RESIDENTIAL_SOURCE_URLS,
            {
                "apartamento": "https://proserinmobiliaria.com/s/apartamento/alquiler?id_city=496&id_property_type=2&business_type%5B0%5D=for_rent",
                "casa": "https://proserinmobiliaria.com/s/casa/alquiler?id_city=496&id_property_type=1&business_type%5B0%5D=for_rent",
                "apartaestudio": "https://proserinmobiliaria.com/s/apartaestudio/alquiler?id_city=496&id_property_type=14&business_type%5B0%5D=for_rent",
            },
        )

    def test_commercial_marketplace_and_sale_only_cards_are_rejected(self):
        rows, _ = parse_search_page(_load("search_page_leakage.html"))

        self.assertEqual({row["id"] for row in rows}, {"PRO-7000001", "PRO-7000002"})
        self.assertTrue(all(row["tipo"] in {"apartamento", "casa", "apartaestudio"} for row in rows))


class TestDetailMerge(unittest.TestCase):
    """Detail pages fill fields absent from search cards."""

    def test_detail_adds_explicit_barrio_and_estrato(self):
        rows, _ = parse_search_page(_load("search_page_1.html"))
        row = next(item for item in rows if item["id"] == "PRO-10163884")

        detail = parse_detail_page(_load("detail_10163884.html"))
        merge_detail(row, detail)

        self.assertEqual(row["estrato"], 4)
        self.assertEqual(row["barrio"], "San Joaquín")
        self.assertEqual(row["url"], detail["url"])

    def test_detail_code_mismatch_does_not_replace_card_identity(self):
        rows, _ = parse_search_page(_load("search_page_1.html"))
        row = next(item for item in rows if item["id"] == "PRO-10163884")
        detail = parse_detail_page(_load("detail_10163884.html").replace("10163884", "99999999"))

        merge_detail(row, detail)

        self.assertEqual(row["id"], "PRO-10163884")
        self.assertEqual(row["estrato"], 0)


class TestTwoPhaseScrape(unittest.TestCase):
    """The public scraper performs card parsing followed by detail merging."""

    def test_scrape_fetches_details_and_returns_contract_rows(self):
        search = _load("search_page_1.html")
        detail = _load("detail_10163884.html")
        detail_sale = detail.replace("10163884", "10205313").replace("San Joaquín", "Poblado")
        with mock.patch("scrape.proserinmobiliaria.fetch_page", return_value=search) as pages, mock.patch(
            "scrape.proserinmobiliaria.bulk_fetch",
            return_value=[(
                "https://proserinmobiliaria.com/apartamento-venta-poblado-medellin/10205313",
                detail_sale,
            ), (
                "https://proserinmobiliaria.com/apartamento-alquiler-san-joaquin-medellin/10163884",
                detail,
            )],
        ) as details:
            rows = scrape(max_pages=1)

        details.assert_called_once()
        self.assertEqual(pages.call_count, 3)
        self.assertEqual(
            {call.args[0] for call in pages.call_args_list},
            {
                "https://proserinmobiliaria.com/search?id_city=496&id_property_type=2&business_type%5B0%5D=for_rent&order_by=created_at&order=desc&page=1&for_sale=0&for_rent=1&for_temporary_rent=0&for_transfer=0&lax_business_type=1",
                "https://proserinmobiliaria.com/search?id_city=496&id_property_type=1&business_type%5B0%5D=for_rent&order_by=created_at&order=desc&page=1&for_sale=0&for_rent=1&for_temporary_rent=0&for_transfer=0&lax_business_type=1",
                "https://proserinmobiliaria.com/search?id_city=496&id_property_type=14&business_type%5B0%5D=for_rent&order_by=created_at&order=desc&page=1&for_sale=0&for_rent=1&for_temporary_rent=0&for_transfer=0&lax_business_type=1",
            },
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["estrato"], 4)
        self.assertTrue(all(list(row) == COLUMNS for row in rows))

    def test_scrape_drops_rows_without_detail_evidence(self):
        with mock.patch("scrape.proserinmobiliaria.fetch_page", return_value=_load("search_page_1.html")), mock.patch(
            "scrape.proserinmobiliaria.bulk_fetch", return_value=[]
        ):
            rows = scrape(max_pages=1)

        self.assertEqual(rows, [])

    def test_scrape_never_sends_leakage_cards_to_details(self):
        search = _load("search_page_leakage.html")
        with mock.patch("scrape.proserinmobiliaria.fetch_page", return_value=search), mock.patch(
            "scrape.proserinmobiliaria.bulk_fetch", return_value=[]
        ) as details:
            scrape(max_pages=1)

        self.assertEqual(
            set(details.call_args.args[0]),
            {
                "https://proserinmobiliaria.com/apartamento-alquiler-laureles-medellin/7000001",
                "https://proserinmobiliaria.com/casa-alquiler-laureles-medellin/7000002",
            },
        )


if __name__ == "__main__":
    unittest.main()
