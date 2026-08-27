"""Regression tests for orchestrator failure handling."""

import unittest
from unittest.mock import patch

from scrape import orchestrator
from scrape.orchestrator import PORTALS, parallel_scrape, run_pipeline, validate_results
from scrape.report import generate_report


class _FakeFuture:
    def __init__(self, portal: str, result: dict):
        self.portal = portal
        self._result = result
        self._done = False
        self._cancelled = False

    def result(self) -> dict:
        return self._result

    def cancel(self) -> bool:
        if self._done:
            return False
        self._cancelled = True
        return True

    def cancelled(self) -> bool:
        return self._cancelled


class _FakeExecutor:
    def __init__(self, results: dict[str, dict]):
        self.results = results
        self.futures: list[_FakeFuture] = []
        self.submitted: list[str] = []
        self.active_counts: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def submit(self, _function, portal: str) -> _FakeFuture:
        self.active_counts.append(
            sum(not future._done and not future._cancelled for future in self.futures)
        )
        future = _FakeFuture(
            portal,
            {"portal": portal, **self.results[portal]},
        )
        self.futures.append(future)
        self.submitted.append(portal)
        return future


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


class TestFailFastScrape(unittest.TestCase):
    def test_stops_submitting_after_failure_with_bounded_workers(self):
        success = {"success": True, "listings": 1}
        failure = {"success": False, "listings": 0, "error": "portal failed"}
        executor = _FakeExecutor(
            {"first": success, "second": failure, "third": success, "fourth": success}
        )
        completion_order = iter(["first", "second", "third"])

        def complete_one(futures, return_when):
            self.assertEqual(return_when, orchestrator.concurrent.futures.FIRST_COMPLETED)
            by_portal = {future.portal: future for future in futures}
            future = by_portal[next(completion_order)]
            future._done = True
            return {future}, set()

        with patch(
            "scrape.orchestrator.concurrent.futures.ThreadPoolExecutor",
            return_value=executor,
        ), patch(
            "scrape.orchestrator.concurrent.futures.wait",
            side_effect=complete_one,
        ):
            results = parallel_scrape(
                ["first", "second", "third", "fourth"],
                workers=2,
                fail_fast=True,
                verbose=False,
            )

        self.assertEqual(executor.submitted, ["first", "second", "third"])
        self.assertLessEqual(max(executor.active_counts), 2)
        self.assertEqual(
            [result["portal"] for result in results],
            ["first", "second", "third", "fourth"],
        )
        self.assertFalse(results[1]["success"])
        cancelled = [result for result in results if result.get("cancelled")]
        self.assertEqual({result["portal"] for result in cancelled}, {"third", "fourth"})
        self.assertTrue(all(result["error"] for result in cancelled))
        self.assertEqual(validate_results(cancelled, PORTALS)["warnings"], [])
        report = generate_report(
            [],
            results,
            validate_results(results, PORTALS),
            None,
            0.0,
        )
        self.assertIn("third", report)
        self.assertIn("fourth", report)
        self.assertTrue(executor.futures[-1].cancelled())


class TestFailFastPipeline(unittest.TestCase):
    def test_scrape_failure_skips_sheets_export(self):
        health = [{"portal": "zitios", "healthy": True, "listings": 1}]
        scrape = [{"portal": "zitios", "success": False, "listings": 0, "error": "failed"}]

        with patch("scrape.orchestrator.health_check", return_value=health), patch(
            "scrape.orchestrator.backup_db", return_value="/tmp/backup.sql"
        ), patch(
            "scrape.orchestrator.parallel_scrape", return_value=scrape
        ) as parallel, patch(
            "scrape.orchestrator.export_to_sheets"
        ) as export, patch(
            "scrape.orchestrator.generate_report", return_value="report"
        ), patch(
            "scrape.orchestrator.write_json_report", return_value="/tmp/report.json"
        ):
            exit_code = run_pipeline(workers=1, fail_fast=True)

        self.assertEqual(exit_code, 1)
        parallel.assert_called_once_with(
            ["zitios"],
            workers=1,
            ciudad="medellin",
            verbose=True,
            fail_fast=True,
        )
        export.assert_not_called()

    def test_all_success_fail_fast_still_exports_sheets(self):
        health = [{"portal": "zitios", "healthy": True, "listings": 1}]
        scrape = [{"portal": "zitios", "success": True, "listings": 1}]
        sheet = {"success": True, "attempts": 1, "elapsed": 0.1, "error": None}

        with patch("scrape.orchestrator.health_check", return_value=health), patch(
            "scrape.orchestrator.backup_db", return_value="/tmp/backup.sql"
        ), patch(
            "scrape.orchestrator.parallel_scrape", return_value=scrape
        ), patch(
            "scrape.orchestrator.export_to_sheets", return_value=sheet
        ) as export, patch(
            "scrape.orchestrator.generate_report", return_value="report"
        ), patch(
            "scrape.orchestrator.write_json_report", return_value="/tmp/report.json"
        ):
            exit_code = run_pipeline(workers=1, fail_fast=True)

        self.assertEqual(exit_code, 0)
        export.assert_called_once_with("medellin")

    def test_non_fail_fast_scrape_failure_still_exports_sheets(self):
        health = [{"portal": "zitios", "healthy": True, "listings": 1}]
        scrape = [{"portal": "zitios", "success": False, "listings": 0, "error": "failed"}]
        sheet = {"success": True, "attempts": 1, "elapsed": 0.1, "error": None}

        with patch("scrape.orchestrator.health_check", return_value=health), patch(
            "scrape.orchestrator.backup_db", return_value="/tmp/backup.sql"
        ), patch(
            "scrape.orchestrator.parallel_scrape", return_value=scrape
        ), patch(
            "scrape.orchestrator.export_to_sheets", return_value=sheet
        ) as export, patch(
            "scrape.orchestrator.generate_report", return_value="report"
        ), patch(
            "scrape.orchestrator.write_json_report", return_value="/tmp/report.json"
        ):
            exit_code = run_pipeline(workers=1, fail_fast=False)

        self.assertEqual(exit_code, 1)
        export.assert_called_once_with("medellin")


    def test_health_failure_stops_before_backup_and_scrape(self):
        health = [{"portal": "zitios", "healthy": False, "listings": 0, "error": "timeout"}]

        with patch("scrape.orchestrator.health_check", return_value=health), patch(
            "scrape.orchestrator.backup_db"
        ) as backup, patch(
            "scrape.orchestrator.parallel_scrape"
        ) as parallel, patch(
            "scrape.orchestrator.export_to_sheets"
        ) as export, patch(
            "scrape.orchestrator.generate_report", return_value="report"
        ), patch(
            "scrape.orchestrator.write_json_report", return_value="/tmp/report.json"
        ):
            exit_code = run_pipeline(workers=1, fail_fast=True)

        self.assertEqual(exit_code, 1)
        backup.assert_not_called()
        parallel.assert_not_called()
        export.assert_not_called()


if __name__ == "__main__":
    unittest.main()
