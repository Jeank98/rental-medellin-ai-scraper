"""Tests for fixed-width report rendering."""

import unittest

from scrape.report import TOTAL_WIDTH, generate_report


class TestReportDiagnostics(unittest.TestCase):
    """Long subprocess diagnostics stay readable without mutating results."""

    def test_long_multiline_errors_are_compact_in_report_only(self):
        stderr = "Traceback (most recent call last):\n" + ("detailed traceback line\n" * 40)
        health = [{"portal": "example", "healthy": False, "error": stderr}]
        scrape = [{"portal": "example", "success": False, "error": stderr}]
        validation = {"passed": False, "warnings": [f"example: FAILED — {stderr}"]}

        report = generate_report(health, scrape, validation, None, 0.0)

        self.assertIn("Traceback (most recent call", report)
        self.assertIn("…", report)
        self.assertTrue(all(len(line) == TOTAL_WIDTH for line in report.splitlines()))
        self.assertEqual(health[0]["error"], stderr)
        self.assertEqual(scrape[0]["error"], stderr)
        self.assertEqual(validation["warnings"], [f"example: FAILED — {stderr}"])
    def test_summary_excludes_cancelled_portals_from_db_count(self):
        scrape = [
            {"portal": "one", "success": True, "listings": 3},
            {
                "portal": "two",
                "success": False,
                "cancelled": True,
                "listings": 0,
                "error": "not submitted after fail-fast failure",
            },
        ]

        report = generate_report([], scrape, {"passed": False, "warnings": []}, None, 0.0)

        self.assertIn("DB UPDATE: 3 listings across 1 portals", report)
        self.assertNotIn("across 2 portals", report)


if __name__ == "__main__":
    unittest.main()
