"""Regression tests for orchestrator failure handling."""

import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scrape import orchestrator
from scrape.orchestrator import (
    PORTALS,
    health_check,
    parallel_scrape,
    run_pipeline,
    validate_results,
)
from scrape.process_runner import CommandResult
from scrape.report import generate_report


class TestScriptResolution(unittest.TestCase):
    def test_script_name_uses_alias_or_portal_key(self):
        for portal, expected in (
            ("arrendamientosdelnorte", "adn"),
            ("zitios", "zitios"),
            ("unknown", "unknown"),
        ):
            with self.subTest(portal=portal):
                self.assertEqual(orchestrator._script_name(portal), expected)

    def test_health_check_builds_command_with_script_alias(self):
        result = CommandResult(
            returncode=0,
            stdout='SCRAPER_RESULT {"status":"success","portal":"arrendamientosdelnorte","listings":1}',
            stderr="",
            attempts=1,
            elapsed=0.01,
            error=None,
        )

        with patch(
            "scrape.orchestrator.run_with_retries", return_value=result
        ) as run:
            health = health_check(
                {"arrendamientosdelnorte": PORTALS["arrendamientosdelnorte"]},
                timeout=1,
                verbose=False,
            )

        run.assert_called_once()
        self.assertEqual(
            run.call_args.args[0],
            [
                "uv",
                "run",
                "python",
                "scripts/scrape_adn.py",
                "--sample-only",
                "--output",
                "csv",
            ],
        )
        self.assertEqual(health[0]["portal"], "arrendamientosdelnorte")
        self.assertTrue(health[0]["healthy"])



class TestDetailReuseDefaults(unittest.TestCase):
    def test_all_two_phase_portals_enable_detail_reuse(self):
        expected = {
            "alnago",
            "arangotobon",
            "arrendamientoselcastillo",
            "arrendamientosmonserrate",
            "arrendamientossantafe",
            "lapalmainmobiliaria",
            "panoramainmobiliario",
            "proserinmobiliaria",
            "santillana",
            "zitios",
        }

        enabled = {
            portal
            for portal, config in PORTALS.items()
            if config.get("reuse_unchanged_details")
        }

        self.assertEqual(enabled, expected)

    def test_parallel_scrape_passes_reuse_flag_only_to_enabled_portals(self):
        results = [
            CommandResult(
                returncode=0,
                stdout=(
                    'SCRAPER_RESULT {"status":"success",'
                    '"portal":"arrendamientossantafe","listings":1}'
                ),
                stderr="",
                attempts=1,
                elapsed=0.01,
                error=None,
            ),
            CommandResult(
                returncode=0,
                stdout=(
                    'SCRAPER_RESULT {"status":"success",'
                    '"portal":"maxibienes","listings":1}'
                ),
                stderr="",
                attempts=1,
                elapsed=0.01,
                error=None,
            ),
        ]

        with patch(
            "scrape.orchestrator.run_with_retries", side_effect=results
        ) as run:
            parallel_scrape(
                ["arrendamientossantafe", "maxibienes"],
                workers=1,
                verbose=False,
            )

        santafe_command, maxibienes_command = [
            call.args[0] for call in run.call_args_list
        ]
        self.assertIn("--reuse-unchanged-details", santafe_command)
        self.assertNotIn("--reuse-unchanged-details", maxibienes_command)

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
        export.assert_called_once()

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
        export.assert_called_once()


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


SECRET_DB_URL = (
    "postgresql://scraper:s3cret-pw@db.example:5432/rentals"
    "?sslmode=require&channel_binding=require"
)


def _fake_pg_dump(command, **_kwargs):
    Path(command[command.index("-f") + 1]).write_text("-- dump")
    return subprocess.CompletedProcess(command, 0)


def test_backup_db_reports_unparseable_connection_uri_without_credentials(tmp_path):
    invalid_url = "postgresql://scraper:s3cret-pw@db.example\uff1a5432/rentals"

    with (
        patch.dict("os.environ", {"DATABASE_URL": invalid_url}),
        patch("scrape.orchestrator.subprocess.run") as run,
    ):
        outcome = orchestrator.backup_db(str(tmp_path), verbose=False)

    run.assert_not_called()
    serialized = json.dumps(outcome)
    assert outcome["status"] == "failed"
    assert outcome["error"] == "DATABASE_URL could not be parsed; backup not attempted"
    assert "s3cret-pw" not in serialized
    assert "db.example" not in serialized


def test_backup_db_passes_connection_uri_only_through_child_environment(tmp_path):
    with (
        patch.dict("os.environ", {"DATABASE_URL": SECRET_DB_URL}),
        patch(
            "scrape.orchestrator.subprocess.run", side_effect=_fake_pg_dump
        ) as run,
    ):
        outcome = orchestrator.backup_db(str(tmp_path), verbose=False)

    command = run.call_args.args[0]
    child_env = run.call_args.kwargs["env"]
    assert outcome["status"] == "success"
    assert "s3cret-pw" not in " ".join(command)
    assert SECRET_DB_URL not in " ".join(command)
    assert child_env["PGDATABASE"] == (
        "postgresql://scraper:s3cret-pw@db.example:5432/rentals?sslmode=require"
    )
    assert "channel_binding" not in child_env["PGDATABASE"]


def test_backup_failure_report_never_contains_the_connection_uri(tmp_path):
    failure = subprocess.CalledProcessError(
        1,
        ["pg_dump", SECRET_DB_URL],
        output=SECRET_DB_URL,
        stderr=SECRET_DB_URL,
    )

    with (
        patch.dict("os.environ", {"DATABASE_URL": SECRET_DB_URL}),
        patch("scrape.orchestrator.subprocess.run", side_effect=failure),
    ):
        outcome = orchestrator.backup_db(str(tmp_path), verbose=False)

    serialized = json.dumps(outcome)
    assert outcome["status"] == "failed"
    assert SECRET_DB_URL not in serialized
    assert "s3cret-pw" not in serialized
    assert outcome["error"] == "pg_dump failed with exit code 1"


if __name__ == "__main__":
    unittest.main()
