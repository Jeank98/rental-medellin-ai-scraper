"""
Orchestrator module — 5-phase pipeline for scraping all 21 Colombian real
estate portals in parallel with health checks, validation, and DB backup.
"""

import concurrent.futures
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from scrape.report import compact_console_text, generate_report
from scrape.process_runner import run_with_retries
from scrape.run_report import write_json_report

RETRY_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 5.0
SHEET_TIMEOUT_SECONDS = 900

PORTALS = {
    "accrecer": {"module": "accrecer"},
    "arangotobon": {"module": "arangotobon"},
    "totalbienes": {"module": "totalbienes"},
    "maxibienes": {"module": "maxibienes"},
    "albertoalvarez": {"module": "albertoalvarez"},
    "alnago": {"module": "alnago"},
    "arrendamientosdelnorte": {"module": "arrendamientosdelnorte", "script": "adn"},
    "arrendamientoselcastillo": {"module": "arrendamientoselcastillo"},
    "arrendamientosmonserrate": {"module": "arrendamientosmonserrate", "script": "monserrate"},
    "arrendamientossantafe": {"module": "arrendamientossantafe", "script": "asf"},
    "arrendamientosvillacruz": {"module": "arrendamientosvillacruz", "script": "villacruz"},
    "coninsa": {"module": "coninsa"},
    "habitamos": {"module": "habitamos"},
    "merinohermanos": {"module": "merinohermanos"},
    "metrocasas": {"module": "metrocasas"},
    "panoramainmobiliario": {"module": "panoramainmobiliario"},
    "portadainmobiliaria": {"module": "portadainmobiliaria"},
    "proserinmobiliaria": {"module": "proserinmobiliaria"},
    "santillana": {"module": "santillana"},
    "lapalmainmobiliaria": {"module": "lapalma", "script": "lapalma"},
    "zitios": {"module": "zitios"},
}

def _script_name(portal: str) -> str:
    entry = PORTALS.get(portal, {})
    return entry.get("script", portal)

SCRAPER_RESULT_PREFIX = "SCRAPER_RESULT "


class BackupOutcome(TypedDict):
    """Stable state returned by :func:`backup_db` and persisted in reports."""

    status: Literal["success", "skipped", "failed"]
    path: str | None
    error: str | None
    reason: str | None


def _backup_outcome(
    status: Literal["success", "skipped", "failed"],
    path: str | None = None,
    error: str | None = None,
    reason: str | None = None,
) -> BackupOutcome:
    return {
        "status": status,
        "path": path,
        "error": error,
        "reason": reason,
    }


def _parse_scraper_result(output: str) -> dict:
    """Parse and validate the CLI's machine-readable result marker.

    Human-readable output is intentionally ignored.  A missing, duplicate, or
    malformed marker is an execution failure rather than an implicit zero.
    """
    marker_lines = [
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith(SCRAPER_RESULT_PREFIX)
    ]
    if not marker_lines:
        raise ValueError("missing SCRAPER_RESULT marker")
    if len(marker_lines) != 1:
        raise ValueError("multiple SCRAPER_RESULT markers")

    raw_payload = marker_lines[0][len(SCRAPER_RESULT_PREFIX):]
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"malformed SCRAPER_RESULT marker: {error.msg}") from error

    if not isinstance(payload, dict):
        raise ValueError("malformed SCRAPER_RESULT marker: expected JSON object")
    status = payload.get("status")
    portal = payload.get("portal")
    listings = payload.get("listings")
    if status not in {"success", "failed"}:
        raise ValueError("malformed SCRAPER_RESULT marker: invalid status")
    if not isinstance(portal, str) or not portal:
        raise ValueError("malformed SCRAPER_RESULT marker: invalid portal")
    if isinstance(listings, bool) or not isinstance(listings, int) or listings < 0:
        raise ValueError("malformed SCRAPER_RESULT marker: invalid listings")
    return payload


def _parse_listing_count(output: str) -> int:
    """Backward-compatible count helper backed by the structured marker."""
    return _parse_scraper_result(output)["listings"]


def health_check(portals: dict, timeout: int = 300, verbose: bool = True) -> list[dict]:
    """Run each scraper in sample-only mode to verify it works.

    All scrapers run in parallel via ThreadPoolExecutor.
    Prints progress to stdout as each portal completes.
    Returns list of {portal, healthy, listings, elapsed, error}.
    """
    results: list[dict] = []
    portal_keys = list(portals.keys())

    if verbose:
        print(f"\n{'='*50}")
        print(f"  HEALTH CHECK — {len(portal_keys)} portals")
        print(f"{'='*50}")

    def _check(portal: str) -> dict:
        script = _script_name(portal)
        if verbose:
            print(f"  ⏳ {portal:30s} checking...", end="", flush=True)
        result = run_with_retries(
            ["uv", "run", "python", f"scripts/scrape_{script}.py", "--sample-only", "--output", "csv"],
            timeout=timeout,
            max_attempts=RETRY_ATTEMPTS,
            retry_delay=RETRY_DELAY_SECONDS,
        )
        elapsed = result.elapsed
        marker: dict = {}
        marker_error: str | None = None
        try:
            marker = _parse_scraper_result(result.stdout)
            listings = marker["listings"]
        except ValueError as error:
            listings = 0
            marker_error = str(error)

        error_msg = marker_error or result.error or f"exit code {result.returncode}"
        if result.returncode != 0:
            if verbose:
                print(f"\r  ❌ {portal:30s} FAILED ({elapsed:.1f}s, {result.attempts} attempts) — {compact_console_text(error_msg, 60)}")
            return {
                "portal": portal, "healthy": False, "listings": listings,
                "status": marker.get("status"), "elapsed": elapsed,
                "attempts": result.attempts, "error": error_msg,
            }
        if marker_error or marker.get("status") != "success":
            error_msg = marker_error or marker.get("error") or "scraper reported failure"
            if verbose:
                print(f"\r  ❌ {portal:30s} FAILED ({elapsed:.1f}s) — {compact_console_text(error_msg, 60)}")
            return {
                "portal": portal, "healthy": False, "listings": listings,
                "status": marker.get("status"), "elapsed": elapsed,
                "attempts": result.attempts, "error": error_msg,
            }
        if listings == 0:
            if verbose:
                print(f"\r  ❌ {portal:30s} FAILED ({elapsed:.1f}s) — 0 listings")
            return {"portal": portal, "healthy": False, "listings": 0, "status": "success", "elapsed": elapsed, "attempts": result.attempts, "error": "0 listings returned"}
        if verbose:
            print(f"\r  ✅ {portal:30s} {listings:>4d} listings ({elapsed:.1f}s)")
        return {"portal": portal, "healthy": True, "listings": listings, "status": "success", "elapsed": elapsed, "attempts": result.attempts, "error": None}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(portal_keys)) as executor:
        futures = {executor.submit(_check, p): p for p in portal_keys}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    if verbose:
        healthy = sum(1 for r in results if r["healthy"])
        print(f"  ── {healthy}/{len(results)} healthy\n")
    return results


def parallel_scrape(
    portal_keys: list[str],
    workers: int = 4,
    ciudad: str = "medellin",
    verbose: bool = True,
    fail_fast: bool = False,
) -> list[dict]:
    """Run full scrapes for the given portals in parallel.

    Each scraper writes directly to the database via --output db.
    Prints progress to stdout as each portal completes.
    Returns one result per portal that completed or was canceled. In fail-fast
    mode, synthetic ``cancelled`` results identify submitted futures that could
    not start and portals that were never submitted after a failure.

    In fail-fast mode, keep no more than ``workers`` jobs submitted at a
    time. A replacement is submitted only for a successful completion; the
    first failed result stops new submissions and cancels pending futures.
    """
    results: list[dict] = []

    if verbose:
        print(f"\n{'='*50}")
        print(f"  PARALLEL SCRAPE — {len(portal_keys)} portals ({workers} workers)")
        print(f"{'='*50}")

    def _scrape(portal: str) -> dict:
        script = _script_name(portal)
        if verbose:
            print(f"  ⏳ {portal:30s} scraping...", end="", flush=True)
        result = run_with_retries(
            ["uv", "run", "python", f"scripts/scrape_{script}.py", "--output", "db", "--ciudad", ciudad],
            timeout=3600,
            max_attempts=RETRY_ATTEMPTS,
            retry_delay=RETRY_DELAY_SECONDS,
        )
        elapsed = result.elapsed
        marker: dict = {}
        marker_error: str | None = None
        try:
            marker = _parse_scraper_result(result.stdout)
            listings = marker["listings"]
        except ValueError as error:
            listings = 0
            marker_error = str(error)

        error_msg = marker_error or result.error or f"exit code {result.returncode}"
        if result.returncode != 0:
            if verbose:
                print(f"\r  ❌ {portal:30s} FAILED ({elapsed:.1f}s, {result.attempts} attempts) — {compact_console_text(error_msg, 60)}")
            return {
                "portal": portal, "success": False, "listings": listings,
                "status": marker.get("status"), "elapsed": elapsed,
                "attempts": result.attempts, "error": error_msg,
            }
        if marker_error or marker.get("status") != "success":
            error_msg = marker_error or marker.get("error") or "scraper reported failure"
            if verbose:
                print(f"\r  ❌ {portal:30s} FAILED ({elapsed:.1f}s) — {compact_console_text(error_msg, 60)}")
            return {
                "portal": portal, "success": False, "listings": listings,
                "status": marker.get("status"), "elapsed": elapsed,
                "attempts": result.attempts, "error": error_msg,
            }
        if verbose:
            print(f"\r  ✅ {portal:30s} {listings:>5d} listings ({_fmt_time(elapsed)})")
        return {
            "portal": portal, "success": True, "listings": listings,
            "status": "success", "elapsed": elapsed,
            "attempts": result.attempts, "error": None,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        if not fail_fast:
            futures = {executor.submit(_scrape, p): p for p in portal_keys}
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        else:
            pending: dict[concurrent.futures.Future, str] = {}
            next_portal = 0
            cancelled_results: list[dict] = []

            def _cancelled_result(portal: str, error: str) -> dict:
                return {
                    "portal": portal,
                    "success": False,
                    "cancelled": True,
                    "listings": 0,
                    "elapsed": 0.0,
                    "attempts": 0,
                    "error": error,
                }

            def _submit_next() -> bool:
                nonlocal next_portal
                if next_portal >= len(portal_keys):
                    return False
                portal = portal_keys[next_portal]
                next_portal += 1
                pending[executor.submit(_scrape, portal)] = portal
                return True

            for _ in range(min(workers, len(portal_keys))):
                _submit_next()

            failed = False
            while pending:
                done, _ = concurrent.futures.wait(
                    pending,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                completed: list[dict] = []
                for future in done:
                    portal = pending.pop(future)
                    if future.cancelled():
                        cancelled_results.append(
                            _cancelled_result(portal, "cancelled before completion")
                        )
                    else:
                        completed.append(future.result())
                results.extend(completed)

                if any(not result["success"] for result in completed):
                    failed = True
                    for future, portal in list(pending.items()):
                        if future.cancel():
                            pending.pop(future)
                            cancelled_results.append(
                                _cancelled_result(portal, "cancelled after fail-fast failure")
                            )
                    cancelled_results.extend(
                        _cancelled_result(
                            portal, "not submitted after fail-fast failure"
                        )
                        for portal in portal_keys[next_portal:]
                    )
                    next_portal = len(portal_keys)
                elif not failed:
                    for result in completed:
                        if result["success"]:
                            _submit_next()

            results.extend(cancelled_results)
    if verbose:
        attempted_results = [r for r in results if not r.get("cancelled", False)]
        successful = sum(1 for r in attempted_results if r["success"])
        cancelled = len(results) - len(attempted_results)
        suffix = f" ({cancelled} cancelled/not started)" if cancelled else ""
        print(f"  ── {successful}/{len(attempted_results)} successful{suffix}\n")
    return results


def validate_results(
    scrape_results: list[dict],
    portals: dict | None = None,
    health_results: list[dict] | None = None,
    backup_outcome: BackupOutcome | dict | None = None,
) -> dict:
    """Validate technical execution results without judging inventory size.

    A failed required backup is a blocking warning.  ``skipped`` outcomes are
    reported separately and do not fail validation by themselves.
    """
    warnings: list[str] = []

    for result in health_results or []:
        if not result.get("healthy", False):
            warnings.append(
                f"{result.get('portal', '?')}: HEALTH CHECK FAILED — "
                f"{result.get('error') or 'unknown error'}"
            )

    for r in scrape_results:
        portal = r.get("portal", "?")
        error = r.get("error")
        success = r.get("success", False)

        if not success and not r.get("cancelled", False):
            warnings.append(f"{portal}: FAILED — {error or 'unknown error'}")

    if backup_outcome and backup_outcome.get("status") == "failed":
        warnings.append(
            "backup: BACKUP FAILED — "
            f"{backup_outcome.get('error') or 'unknown error'}"
        )

    passed = len(warnings) == 0
    return {"passed": passed, "warnings": warnings}


def _clean_db_url(url: str) -> str:
    """Remove channel_binding parameter for pg_dump compatibility."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    params.pop("channel_binding", None)
    new_query = urlencode(params, doseq=True)
    clean = parsed._replace(query=new_query)
    return urlunparse(clean)


def _fmt_time(seconds: float) -> str:
    """Format seconds as human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}m {secs}s"


def _coerce_backup_outcome(
    value: BackupOutcome | dict | str | None,
    *,
    default_reason: str | None = None,
) -> BackupOutcome:
    """Normalize legacy test/adaptor return values at the pipeline seam."""
    if isinstance(value, dict):
        status = value.get("status")
        if status in {"success", "skipped", "failed"}:
            return _backup_outcome(
                status,
                value.get("path"),
                value.get("error"),
                value.get("reason") or default_reason,
            )
    if isinstance(value, str) and value:
        return _backup_outcome("success", path=value, reason=default_reason)
    return _backup_outcome("skipped", reason=default_reason)


def backup_db(
    backup_dir: str = "~/Projects/Backups",
    verbose: bool = True,
) -> BackupOutcome:
    """Run pg_dump and return an explicit success, skip, or failure outcome.

    ``path`` is the completed backup path on success and the attempted path on
    a command failure when it could be known.  Missing ``DATABASE_URL`` is an
    intentional skip, while a failed ``pg_dump`` is a required-backup failure.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return _backup_outcome(
            "skipped",
            reason="missing_database_url",
            error="DATABASE_URL not set",
        )

    dump_file: Path | None = None
    try:
        backup_path = Path(backup_dir).expanduser()
        backup_path.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        dump_file = backup_path / f"rental_scraper_{timestamp}.sql"
        clean_url = _clean_db_url(db_url)

        if verbose:
            print(f"\n{'='*50}")
            print(f"  DB BACKUP → {dump_file}")
            print(f"{'='*50}")

        subprocess.run(
            ["pg_dump", clean_url, "--no-owner", "--no-acl", "-f", str(dump_file)],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
        file_size = dump_file.stat().st_size
        if verbose:
            print(f"  ✅ Backup complete — {file_size / 1024:.0f} KB\n")
        return _backup_outcome("success", path=str(dump_file))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        if verbose:
            print(f"  ❌ Backup FAILED — {error}\n")
        return _backup_outcome(
            "failed",
            path=str(dump_file) if dump_file else None,
            error=str(error),
            reason="pg_dump_failed",
        )


def export_to_sheets(ciudad: str = "medellin", verbose: bool = True) -> dict:
    """Mirror the current DB state to Sheets after portal writes complete."""
    result = run_with_retries(
        ["uv", "run", "python", "scripts/export_to_sheets.py", "--city", ciudad],
        timeout=SHEET_TIMEOUT_SECONDS,
        max_attempts=1,
    )
    if verbose and result.returncode != 0:
        print(f"  ❌ Sheet export FAILED — {compact_console_text(result.error or 'unknown error', 60)}")
    return {
        "success": result.returncode == 0,
        "attempts": result.attempts,
        "elapsed": result.elapsed,
        "error": result.error,
    }


def run_pipeline(
    workers: int = 4,
    ciudad: str = "medellin",
    skip_backup: bool = False,
    skip_health: bool = False,
    skip_sheet: bool = False,
    report_dir: str = "runtime/scraper-runs",
    fail_fast: bool = False,
) -> int:
    """Run the full 5-phase pipeline: health → backup → scrape → validate → report.

    In fail-fast mode, a health failure aborts before backup or scraping, and a
    scrape failure skips the Sheets export.

    Returns 0 on success, 1 if validation fails.
    """
    start = time.monotonic()

    print(f"\n{'='*50}")
    print(f"  SCRAPER ORCHESTRATOR")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Workers: {workers} | Ciudad: {ciudad}")
    print(f"{'='*50}")

    # Phase 1: Health check
    health_results: list[dict] = []
    if skip_health:
        print("\n  ⏩ Health check SKIPPED\n")
        for portal in PORTALS:
            health_results.append({
                "portal": portal, "healthy": True,
                "listings": 0, "elapsed": 0.0, "error": None,
            })
    else:
        health_results = health_check(PORTALS, verbose=True)

    health_failed = fail_fast and any(
        not result.get("healthy", False) for result in health_results
    )
    scrape_results: list[dict] = []

    if health_failed:
        backup_outcome = _backup_outcome(
            "skipped",
            reason="health_abort",
            error="health check failed",
        )
        print("\n  ❌ Fail-fast: health check failed; stopping before backup and scrape\n")
    else:
        # Phase 2: Backup OLD state BEFORE scraping.
        if skip_backup:
            backup_outcome = _backup_outcome("skipped", reason="operator")
        else:
            try:
                backup_outcome = _coerce_backup_outcome(backup_db(verbose=True))
            except Exception as error:
                backup_outcome = _backup_outcome(
                    "failed",
                    error=str(error),
                    reason="backup_exception",
                )

        backup_failed = backup_outcome["status"] == "failed"
        if backup_failed:
            print(
                "\n  ❌ Required DB backup failed; stopping before scrape and Sheets\n"
            )
        else:
            # Phase 3: Parallel scrape — only healthy portals.
            healthy_portals = [
                r["portal"] for r in health_results if r.get("healthy", False)
            ]
            if healthy_portals:
                scrape_results = parallel_scrape(
                    healthy_portals,
                    workers=workers,
                    ciudad=ciudad,
                    verbose=True,
                    fail_fast=fail_fast,
                )
            else:
                print("\n  ⚠️  No healthy portals to scrape\n")

    backup_path = backup_outcome.get("path")

    # Phase 4: Validation
    validation = validate_results(
        scrape_results,
        PORTALS,
        health_results,
        backup_outcome,
    )
    scrape_failed = fail_fast and any(
        not result.get("success", False) for result in scrape_results
    )
    backup_failed = backup_outcome["status"] == "failed"

    if skip_sheet:
        sheet_result = {
            "success": True, "skipped": True, "reason": "operator",
            "attempts": 0, "elapsed": 0.0, "error": None,
        }
    elif health_failed:
        sheet_result = {
            "success": True, "skipped": True, "reason": "health_abort",
            "attempts": 0, "elapsed": 0.0, "error": None,
        }
    elif backup_failed:
        sheet_result = {
            "success": True, "skipped": True, "reason": "backup_failure",
            "attempts": 0, "elapsed": 0.0, "error": None,
        }
    elif scrape_failed:
        sheet_result = {
            "success": True, "skipped": True, "reason": "scrape_failure",
            "attempts": 0, "elapsed": 0.0, "error": None,
        }
    else:
        sheet_result = export_to_sheets(ciudad)

    if not sheet_result["success"]:
        validation["warnings"].append(
            f"sheets: EXPORT FAILED — {sheet_result.get('error') or 'unknown error'}"
        )
        validation["passed"] = False
    if validation["warnings"]:
        print(f"\n  ⚠️  Validation warnings:")
        for w in validation["warnings"]:
            print(f"     {compact_console_text(w)}")
    else:
        print(f"\n  ✅ Validation: PASSED")

    # Phase 5: Report
    total_time = time.monotonic() - start
    report = generate_report(
        health_results,
        scrape_results,
        validation,
        backup_path,
        total_time,
        sheet_result,
        backup_outcome=backup_outcome,
    )
    print(report)

    try:
        report_path = write_json_report(
            report_dir,
            {
                "health": health_results,
                "scrape": scrape_results,
                "validation": validation,
                # Keep backup_path for consumers of the original report shape.
                "backup_path": backup_path,
                "backup": backup_outcome,
                "sheet": sheet_result,
                "total_time": total_time,
            },
        )
        print(f"Execution report: {report_path}")
    except OSError as error:
        print(f"Execution report FAILED: {error}")
        validation["passed"] = False

    return 0 if validation.get("passed", False) else 1
