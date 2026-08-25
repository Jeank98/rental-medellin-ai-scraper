"""Fixture-backed tests for the Panorama two-phase scraper."""

import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from scrape.panoramainmobiliario import (
    COLUMNS,
    RESIDENTIAL_TYPES,
    _phase_a,
    build_page_url,
    merge_detail,
    parse_detail_page,
    parse_search_page,
    scrape,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "panoramainmobiliario"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestSearchParsing(unittest.TestCase):
    def test_discards_prices_outside_postgres_integer_range_only(self):
        with self.assertLogs("scrape.panoramainmobiliario", level="WARNING") as logs:
            rows = parse_search_page(_load("search_price_bounds.html"), "apartamento")

        self.assertEqual(
            [row["id"] for row in rows],
            ["PAN-9000203", "PAN-9000204"],
        )
        self.assertEqual([row["precio"] for row in rows], [2500000, 2147483647])
        self.assertIn("PAN-9000201", "\n".join(logs.output))
        self.assertIn("-100000", "\n".join(logs.output))
        self.assertIn("PAN-10306045", "\n".join(logs.output))
        self.assertIn("6108000000", "\n".join(logs.output))

    def test_filtered_source_type_is_authoritative_over_title_and_alt(self):
        rows = parse_search_page(_load("search_casa.html"), "casa")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tipo"], "casa")
        self.assertEqual(rows[0]["id"], "PAN-8528202")
        self.assertEqual(rows[0]["precio"], 3562000)
        self.assertEqual(list(rows[0]), COLUMNS)

    def test_selects_rent_price_when_card_also_has_sale_price(self):
        row = parse_search_page(_load("search_apartamento.html"), "apartamento")[0]

        self.assertEqual(row["precio"], 4480000)
        self.assertEqual(row["area"], 70)
        self.assertEqual(row["habitaciones"], 2)
        self.assertEqual(row["banos"], 2)
        self.assertEqual(row["parqueaderos"], 1)

    def test_rejects_non_residential_card_from_filtered_stream(self):
        rows = parse_search_page(_load("search_leakage.html"), "apartamento")

        self.assertEqual([row["id"] for row in rows], ["PAN-9000002"])
        self.assertTrue(all(row["tipo"] in RESIDENTIAL_TYPES for row in rows))


class TestDetailParsing(unittest.TestCase):
    def test_extracts_structured_barrio_estrato_and_type(self):
        detail = parse_detail_page(_load("detail_apartaestudio.html"))

        self.assertEqual(detail["tipo"], "apartaestudio")
        self.assertEqual(detail["estrato"], 4)
        self.assertEqual(detail["barrio"], "Aliadas")
        self.assertEqual(detail["area"], 40)

    def test_comercial_estrato_is_a_genuine_zero(self):
        detail = parse_detail_page(_load("detail_comercial.html"))

        self.assertEqual(detail["tipo"], "apartaestudio")
        self.assertEqual(detail["estrato"], 0)
        self.assertEqual(detail["barrio"], "Centro")

    def test_merge_fills_detail_fields_without_trusting_title_metadata(self):
        row = parse_search_page(_load("search_casa.html"), "casa")[0]
        detail = parse_detail_page(_load("detail_casa.html"))

        self.assertTrue(merge_detail(row, detail))
        self.assertEqual(row["tipo"], "casa")
        self.assertEqual(row["estrato"], 3)
        self.assertEqual(row["barrio"], "San Bernardo")


class TestTwoPhaseScrape(unittest.TestCase):
    def test_retries_transient_empty_house_page_and_keeps_full_response(self):
        attempts = {}

        def fetch(url: str) -> str:
            query = parse_qs(urlparse(url).query)
            property_type = query["id_property_type"][0]
            attempts[property_type] = attempts.get(property_type, 0) + 1
            if property_type == "1":
                return (
                    _load("empty_page.html")
                    if attempts[property_type] == 1
                    else _load("search_casa_full.html")
                )
            return _load("empty_page.html")

        with mock.patch("scrape.panoramainmobiliario.fetch_page", side_effect=fetch):
            rows = _phase_a("medellin", max_pages=1, verbose=False)

        house_rows = [row for row in rows if row["tipo"] == "casa"]
        self.assertEqual(len(house_rows), 12)
        self.assertEqual(attempts["1"], 2)
        self.assertEqual(len({row["id"] for row in house_rows}), 12)

    def test_retries_genuine_short_page_then_stops_without_next_page(self):
        calls = []

        def fetch(url: str) -> str:
            query = parse_qs(urlparse(url).query)
            calls.append(url)
            return _load("search_casa.html") if query["id_property_type"] == ["1"] else _load("empty_page.html")

        with mock.patch("scrape.panoramainmobiliario.fetch_page", side_effect=fetch):
            rows = _phase_a("medellin", max_pages=None, verbose=False)

        house_calls = [
            url
            for url in calls
            if parse_qs(urlparse(url).query)["id_property_type"] == ["1"]
        ]
        self.assertEqual(len([row for row in rows if row["tipo"] == "casa"]), 1)
        self.assertEqual(len(house_calls), 2)
        self.assertFalse(any("page=2" in url for url in house_calls))

    def test_build_page_url_contains_verified_filters(self):
        for property_type, property_id in {
            "apartaestudio": "14",
            "apartamento": "2",
            "casa": "1",
        }.items():
            query = parse_qs(urlparse(build_page_url(4, property_type=property_type)).query)
            self.assertEqual(query["id_city"], ["496"])
            self.assertEqual(query["id_property_type"], [property_id])
            self.assertEqual(query["business_type[0]"], ["for_rent"])
            self.assertEqual(query["page"], ["4"])

    def test_scrape_unions_three_type_streams_deduplicates_and_merges_details(self):
        pages = {
            "14": _load("search_apartaestudio.html"),
            "2": _load("search_apartamento.html"),
            "1": _load("search_casa.html"),
        }
        details = {
            "https://panoramainmobiliario.co/apartaestudio-alquiler-aliadas-medellin/8170174": _load("detail_apartaestudio.html"),
            "https://panoramainmobiliario.co/apartaestudio-alquiler-centro-medellin/8542364": _load("detail_comercial.html"),
            "https://panoramainmobiliario.co/apartamento-alquiler-envigado-las-cumbres-medellin/8597793": _load("detail_apartamento.html"),
            "https://panoramainmobiliario.co/casa-alquiler-san-bernardo-medellin/8528202": _load("detail_casa.html"),
        }

        def fetch(url: str) -> str:
            query = parse_qs(urlparse(url).query)
            return pages[query["id_property_type"][0]] if query["page"] == ["1"] else _load("empty_page.html")

        with (
            mock.patch("scrape.panoramainmobiliario.fetch_page", side_effect=fetch) as fetch_mock,
            mock.patch(
                "scrape.panoramainmobiliario.bulk_fetch",
                return_value=list(details.items()),
            ) as bulk_mock,
        ):
            rows = scrape(max_pages=1)

        self.assertEqual(
            [row["id"] for row in rows],
            ["PAN-8170174", "PAN-8542364", "PAN-8597793", "PAN-8528202"],
        )
        self.assertEqual(len({row["id"] for row in rows}), len(rows))
        self.assertTrue(all(row["tipo"] in RESIDENTIAL_TYPES for row in rows))
        self.assertEqual(next(row for row in rows if row["id"] == "PAN-8170174")["estrato"], 4)
        self.assertEqual(next(row for row in rows if row["id"] == "PAN-8170174")["barrio"], "Aliadas")
        self.assertEqual(fetch_mock.call_count, 6)
        self.assertEqual(set(bulk_mock.call_args.args[0]), set(details))


if __name__ == "__main__":
    unittest.main()
