"""Regression tests for orchestrator portal thresholds."""

import unittest

from scrape.orchestrator import PORTALS, validate_results


class TestPortalThresholds(unittest.TestCase):
    """Thresholds must detect material inventory regressions."""

    def test_elcastillo_threshold_allows_drift_but_flags_material_loss(self):
        portal = "arrendamientoselcastillo"
        threshold = PORTALS[portal]["min_listings"]

        self.assertEqual(threshold, 225)
        passing = [{"portal": portal, "success": True, "listings": 225}]
        failing = [{"portal": portal, "success": True, "listings": 224}]

        self.assertEqual(validate_results(passing, PORTALS)["warnings"], [])
        self.assertEqual(len(validate_results(failing, PORTALS)["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
