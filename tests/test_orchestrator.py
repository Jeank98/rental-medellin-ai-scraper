"""Regression tests for orchestrator failure handling."""

import unittest

from scrape.orchestrator import PORTALS, validate_results


class TestOrchestratorValidation(unittest.TestCase):
    """Inventory size is informational; technical failures are blocking."""

    def test_low_but_successful_inventory_is_accepted(self):
        result = [{"portal": "zitios", "success": True, "listings": 1}]

        self.assertEqual(validate_results(result, PORTALS)["warnings"], [])

    def test_health_failure_blocks_pipeline_validation(self):
        health = [{"portal": "zitios", "healthy": False, "error": "timeout"}]

        validation = validate_results([], PORTALS, health)

        self.assertFalse(validation["passed"])
        self.assertIn("HEALTH CHECK FAILED", validation["warnings"][0])


if __name__ == "__main__":
    unittest.main()
