"""RSC fixture parser tests for Acrecer — STRICT TDD.

These tests validate the parsing contract BEFORE the scraper exists.
They WILL FAIL red until Todo 2 implements scrape/accrecer.py.

DO NOT change these tests to make them pass. The tests define the
contract. The implementation must satisfy them.
"""

import json
import unittest
from pathlib import Path

# This import FAILS until scrape/accrecer.py is created (Todo 2).
# That is CORRECT — red test first.
from scrape.accrecer import parse_rsc_payload  # noqa: F401 — will raise ImportError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "accrecer"


def _load_fixture(name: str) -> str:
    with open(FIXTURES / name, encoding="utf-8") as fh:
        return fh.read()


# ── Full record ─────────────────────────────────────────────────────

class TestParseFullRecord(unittest.TestCase):
    """Given a complete Acrecer RSC fixture, when parsed, then all 11 columns are populated."""

    def test_full_record_maps_all_columns(self):
        """Given a full record fixture, when extracted, then all 11 columns match expected values."""
        html = _load_fixture("full_record.html")
        listings = parse_rsc_payload(html)

        self.assertEqual(len(listings), 1, "Should extract exactly 1 listing")

        row = listings[0]
        expected = {
            "id": "AC-12345",
            "portal": "accrecer",
            "tipo": "apartamento",
            "precio": 1500000,
            "area": 80,
            "habitaciones": 3,
            "banos": 2,
            "parqueaderos": 1,
            "estrato": 4,
            "barrio": "Laureles",
            "url": "https://www.acrecer.com/inmueble/AC-12345",
        }
        # Verify column order
        self.assertEqual(list(row.keys()), list(expected.keys()), "Column order must match spec")
        self.assertEqual(row, expected, "All fields must match expected normalized values")


class TestFullRecordTypes(unittest.TestCase):
    """Given a full record, when checking field types, then numerics are int."""

    def test_numeric_fields_are_integers(self):
        html = _load_fixture("full_record.html")
        listings = parse_rsc_payload(html)
        row = listings[0]

        self.assertIsInstance(row["precio"], int, "precio must be int")
        self.assertIsInstance(row["area"], int, "area must be int")
        self.assertIsInstance(row["habitaciones"], int, "habitaciones must be int")
        self.assertIsInstance(row["banos"], int, "banos must be int")
        self.assertIsInstance(row["parqueaderos"], int, "parqueaderos must be int")
        self.assertIsInstance(row["estrato"], int, "estrato must be int")

    def test_text_fields_are_strings(self):
        html = _load_fixture("full_record.html")
        listings = parse_rsc_payload(html)
        row = listings[0]

        self.assertIsInstance(row["id"], str, "id must be str")
        self.assertIsInstance(row["portal"], str, "portal must be str")
        self.assertIsInstance(row["tipo"], str, "tipo must be str")
        self.assertIsInstance(row["barrio"], str, "barrio must be str")
        self.assertIsInstance(row["url"], str, "url must be str")


# ── Missing fields ──────────────────────────────────────────────────

class TestParseMissingBathsGarages(unittest.TestCase):
    """Given an RSC fixture without rooms.baths and garages, when parsed, then defaults to 0."""

    def test_missing_baths_defaults_to_zero(self):
        html = _load_fixture("missing_baths_garages.html")
        listings = parse_rsc_payload(html)
        row = listings[0]

        self.assertEqual(row["banos"], 0, "Missing rooms.baths must default to 0")
        self.assertEqual(row["parqueaderos"], 0, "Missing householdFeatures.garages must default to 0")

    def test_missing_baths_still_present_column(self):
        html = _load_fixture("missing_baths_garages.html")
        listings = parse_rsc_payload(html)
        row = listings[0]

        self.assertIn("banos", row, "banos column must always be present")
        self.assertIn("parqueaderos", row, "parqueaderos column must always be present")

    def test_present_fields_still_extracted(self):
        html = _load_fixture("missing_baths_garages.html")
        listings = parse_rsc_payload(html)
        row = listings[0]

        self.assertEqual(row["id"], "AC-67890")
        self.assertEqual(row["tipo"], "casa")
        self.assertEqual(row["precio"], 1200000)
        self.assertEqual(row["area"], 120)
        self.assertEqual(row["habitaciones"], 4)
        self.assertEqual(row["estrato"], 3)
        self.assertEqual(row["barrio"], "Belén")


# ── Parking: private only ───────────────────────────────────────────

class TestParkingPrivateOnly(unittest.TestCase):
    """Given the full record has visitorParking=4, when extracted, then parqueaderos is only garages=1."""

    def test_visitor_parking_excluded(self):
        html = _load_fixture("full_record.html")
        listings = parse_rsc_payload(html)
        row = listings[0]

        self.assertEqual(row["parqueaderos"], 1,
                         "parqueaderos must be householdFeatures.garages only, NOT garages+visitor")


# ── Roman stratum ───────────────────────────────────────────────────

class TestRomanStratumNormalization(unittest.TestCase):
    """Given Roman numeral stratum values, when normalized, then mapped to ints."""

    def test_iv_stratum_becomes_4(self):
        html = _load_fixture("full_record.html")
        listings = parse_rsc_payload(html)
        row = listings[0]
        self.assertEqual(row["estrato"], 4)

    def test_iii_stratum_becomes_3(self):
        html = _load_fixture("missing_baths_garages.html")
        listings = parse_rsc_payload(html)
        row = listings[0]
        self.assertEqual(row["estrato"], 3)

    def test_ii_stratum_becomes_2(self):
        html = _load_fixture("mojibake_location.html")
        listings = parse_rsc_payload(html)
        row = listings[0]
        self.assertEqual(row["estrato"], 2)


# ── Mojibake cleanup ────────────────────────────────────────────────

class TestMojibakeLocationCleanup(unittest.TestCase):
    """Given mojibake/corrupted location text, when parsed, then rendered cleanly."""

    def test_mojibake_sector_cleaned(self):
        html = _load_fixture("mojibake_location.html")
        listings = parse_rsc_payload(html)
        row = listings[0]

        # sectorName is "\ud83c\udf06 Bello Horizonte" — should be rendered
        self.assertIn("Bello", row["barrio"],
                      f"barrio should contain cleaned sector text, got: {row['barrio']!r}")

    def test_barrio_not_empty(self):
        html = _load_fixture("mojibake_location.html")
        listings = parse_rsc_payload(html)
        row = listings[0]

        self.assertTrue(len(row["barrio"]) > 0, "barrio must not be empty for this fixture")


# ── Missing mandatory fields ────────────────────────────────────────

class TestMissingMandatoryFields(unittest.TestCase):
    """Given a record missing code or rentValue, when parsed, then skipped with warning."""

    def test_record_without_code_skipped(self):
        html = _load_fixture("missing_mandatory.html")
        listings = parse_rsc_payload(html)

        ids = {row["id"] for row in listings}
        self.assertNotIn("AC-", ids, "Record without code must not produce an empty-ID listing")
        # The valid record with code="AC-99999" should still be extracted
        self.assertIn("AC-99999", ids, "Valid record must still be extracted")

    def test_record_without_rentvalue_skipped(self):
        html = _load_fixture("missing_mandatory.html")
        listings = parse_rsc_payload(html)

        # The first record has rentValue=0 (missing), should be skipped
        # Only AC-99999 should survive
        self.assertEqual(len(listings), 1, "Only the valid record should survive")
        self.assertEqual(listings[0]["id"], "AC-99999")


# ── Absent RSC payload ──────────────────────────────────────────────

class TestAbsentRscPayload(unittest.TestCase):
    """Given HTML with no RSC payload, when parsed, then returns empty."""

    def test_no_rsc_returns_empty_list(self):
        html = _load_fixture("no_rsc.html")
        listings = parse_rsc_payload(html)
        self.assertEqual(listings, [], "No RSC payload should yield empty list")


# ── Absent searchResults ────────────────────────────────────────────

class TestAbsentSearchResults(unittest.TestCase):
    """Given RSC payload without searchResults, when parsed, then returns empty."""

    def test_no_search_results_returns_empty(self):
        html = _load_fixture("no_search_results.html")
        listings = parse_rsc_payload(html)
        self.assertEqual(listings, [], "No searchResults should yield empty list")


# ── Zero results ────────────────────────────────────────────────────

class TestZeroResults(unittest.TestCase):
    """Given RSC payload with empty searchResults array, when parsed, then returns empty."""

    def test_empty_search_results_returns_empty(self):
        html = _load_fixture("zero_results.html")
        listings = parse_rsc_payload(html)
        self.assertEqual(listings, [], "Empty searchResults should yield empty list")


# ── Column order contract ───────────────────────────────────────────

class TestColumnOrder(unittest.TestCase):
    """Every fixture output must have the canonical 11-column order."""

    CANONICAL = ["id", "portal", "tipo", "precio", "area",
                 "habitaciones", "banos", "parqueaderos", "estrato",
                 "barrio", "url"]

    def test_full_record_column_order(self):
        html = _load_fixture("full_record.html")
        listings = parse_rsc_payload(html)
        self.assertEqual(list(listings[0].keys()), self.CANONICAL)

    def test_missing_fields_column_order(self):
        html = _load_fixture("missing_baths_garages.html")
        listings = parse_rsc_payload(html)
        self.assertEqual(list(listings[0].keys()), self.CANONICAL)


if __name__ == "__main__":
    unittest.main()
