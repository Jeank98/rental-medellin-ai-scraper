"""Focused contracts for operational-hardening seams.

These tests mock external adapters and subprocesses; they never contact portals,
PostgreSQL, Google Sheets, or OAuth services.
"""

import argparse
import io
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

import db

from scrape import orchestrator
from scrape.cli import run_scraper
from scrape.report import generate_report


@pytest.fixture
def cli_args() -> argparse.Namespace:
    return argparse.Namespace(
        portal="example",
        output="db",
        ciudad="medellin",
        sample_only=False,
        max_pages=None,
        verbose=False,
    )


def test_insert_script_passes_city_to_db_adapter(tmp_path: Path) -> None:
    """The bulk script's explicit city reaches the atomic/deactivation adapter."""
    input_path = tmp_path / "rows.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "id": "EX-1",
                    "portal": "example",
                    "tipo": "apartamento",
                    "precio": 1_000_000,
                    "area": 50,
                    "habitaciones": 2,
                    "banos": 1,
                    "parqueaderos": 0,
                    "estrato": 3,
                    "barrio": "Laureles",
                    "url": "https://example.test/EX-1",
                }
            ]
        )
    )

    cursor = mock.MagicMock()
    cursor.fetchone.return_value = (0,)
    cursor.fetchall.return_value = []
    connection = mock.MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    connection.__enter__.return_value = connection

    with (
        mock.patch.object(sys, "argv", ["insert_listings.py", str(input_path), "Medellin"]),
        mock.patch("scripts.insert_listings.test_connection", return_value=True),
        mock.patch("scripts.insert_listings.create_tables"),
        mock.patch("scripts.insert_listings.get_count", side_effect=[0, 1]),
        mock.patch("scripts.insert_listings.get_conn", return_value=connection),
        mock.patch("scripts.insert_listings.insert_listings") as insert,
    ):
        from scripts.insert_listings import main

        main()

    rows = insert.call_args.args[0]
    insert.assert_called_once_with(rows, ciudad="medellin")
    # The script's pre/post queries remain city-scoped, matching DB deactivation.
    assert cursor.execute.call_args_list[0].args[1] == ("example", "medellin")
    assert cursor.execute.call_args_list[1].args[1] == ("example", "medellin")
    assert cursor.execute.call_args_list[2].args[1] == ("example", "medellin")


def test_sheets_fetch_is_active_city_price_and_type_filtered() -> None:
    """The Sheets mirror excludes inactive and out-of-contract rows."""
    rows = [
        {"id": "active", "status": "active", "ciudad": "Medellin", "precio": 200_000, "tipo": "Apartamento"},
        {"id": "inactive", "status": "inactive", "ciudad": "Medellin", "precio": 900_000, "tipo": "casa"},
        # Legacy fixture rows without status remain active for compatibility.
        {"id": "legacy", "ciudad": "Medellin", "precio": 250_000, "tipo": "casa"},
        {"id": "wrong-city", "status": "active", "ciudad": "Bogota", "precio": 900_000, "tipo": "casa"},
        {"id": "below-min", "status": "active", "ciudad": "Medellin", "precio": 199_999, "tipo": "casa"},
        {"id": "wrong-type", "status": "active", "ciudad": "Medellin", "precio": 900_000, "tipo": "apartaestudio"},
    ]
    with mock.patch("scripts.export_to_sheets.get_all", return_value=rows):
        from scripts.export_to_sheets import fetch_listings

        result = fetch_listings(city="medellin")

    assert [row["id"] for row in result] == ["active", "legacy"]


def test_backup_db_reports_missing_configuration_as_skip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    outcome = orchestrator.backup_db(str(tmp_path), verbose=False)

    assert outcome == {
        "status": "skipped",
        "path": None,
        "error": "DATABASE_URL not set",
        "reason": "missing_database_url",
    }


def test_backup_db_reports_pg_dump_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.example/rentals?channel_binding=require")
    failure = subprocess.CalledProcessError(1, ["pg_dump"])

    with mock.patch("scrape.orchestrator.subprocess.run", side_effect=failure):
        outcome = orchestrator.backup_db(str(tmp_path), verbose=False)

    assert outcome["status"] == "failed"
    assert outcome["reason"] == "pg_dump_failed"
    assert outcome["path"].endswith(".sql")
    assert outcome["error"]


def test_failed_backup_blocks_scrape_and_sheets() -> None:
    healthy = [{"portal": "example", "healthy": True, "listings": 1}]
    failed_backup = {
        "status": "failed",
        "path": "/tmp/attempt.sql",
        "error": "pg_dump exited 1",
        "reason": "pg_dump_failed",
    }
    with (
        mock.patch("scrape.orchestrator.health_check", return_value=healthy),
        mock.patch("scrape.orchestrator.backup_db", return_value=failed_backup),
        mock.patch("scrape.orchestrator.parallel_scrape") as scrape,
        mock.patch("scrape.orchestrator.export_to_sheets") as export,
        mock.patch("scrape.orchestrator.generate_report", return_value="report"),
        mock.patch("scrape.orchestrator.write_json_report", return_value="/tmp/report.json"),
    ):
        assert orchestrator.run_pipeline(workers=1) == 1

    scrape.assert_not_called()
    export.assert_not_called()


def test_structured_result_parser_ignores_human_wording() -> None:
    output = 'Scraped zero-ish wording\nSCRAPER_RESULT {"listings": 7, "portal": "example", "status": "success"}\n'

    assert orchestrator._parse_listing_count(output) == 7
    assert orchestrator._parse_scraper_result(output)["status"] == "success"


def test_structured_result_parser_rejects_missing_or_malformed_marker() -> None:
    with pytest.raises(ValueError, match="missing SCRAPER_RESULT"):
        orchestrator._parse_scraper_result("Scraped 99 listings from example")
    with pytest.raises(ValueError, match="malformed SCRAPER_RESULT"):
        orchestrator._parse_scraper_result("SCRAPER_RESULT not-json")


def test_cli_emits_machine_result_for_sample_and_zero_rows() -> None:
    args = argparse.Namespace(
        portal="example",
        output="csv",
        ciudad="medellin",
        sample_only=True,
        max_pages=None,
        verbose=False,
    )
    row = {"id": "EX-1", "tipo": "casa", "precio": 500_000}
    with (
        mock.patch("scrape.cli.validate", return_value=[]),
        mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
    ):
        assert run_scraper(lambda: [row], args=args) == 0
    marker = next(line for line in stdout.getvalue().splitlines() if line.startswith("SCRAPER_RESULT "))
    assert json.loads(marker.removeprefix("SCRAPER_RESULT ")) == {
        "listings": 1,
        "portal": "example",
        "status": "success",
    }

    with (
        mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        mock.patch("sys.stderr", new_callable=io.StringIO),
        pytest.raises(SystemExit) as raised,
    ):
        run_scraper(lambda: [], args=args)
    assert raised.value.code == 2
    assert '"status": "failed"' in stdout.getvalue()


def test_lazy_scrape_import_defers_adapters() -> None:
    code = (
        "import sys; import scrape; "
        "assert 'scrape.fetcher' not in sys.modules; "
        "assert 'scrape.db_writer' not in sys.modules; "
        "assert callable(scrape.normalize_price)"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_report_distinguishes_failed_backup() -> None:
    report = generate_report(
        [], [], {"passed": False, "warnings": ["backup failed"]}, None, 0,
        backup_outcome={"status": "failed", "error": "pg_dump exited 1"},
    )
    assert "BACKUP: FAILED" in report
