"""
Orchestrator module — 5-phase pipeline for scraping all 18 Colombian real
estate portals in parallel with health checks, validation, and DB backup.
"""

import concurrent.futures
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from scrape.report import generate_report
from scrape.process_runner import run_with_retries
from scrape.run_report import write_json_report

RETRY_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 5.0
SHEET_TIMEOUT_SECONDS = 900

PORTALS = {
    "accrecer": {"module": "accrecer"},
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
    "proserinmobiliaria": {"module": "proserinmobiliaria"},
    "santillana": {"module": "santillana"},
    "lapalmainmobiliaria": {"module": "lapalma", "script": "lapalma"},
    "zitios": {"module": "zitios"},
}


def _script_name(portal: str) -> str:
    entry = PORTALS.get(portal, {})
    return entry.get("script", portal)


def _parse_listing_count(output: str) -> int:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Sample: "):
            # "Sample: N listing(s) extracted"
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except (ValueError, IndexError):
                    pass
        elif line.startswith("Scraped "):
            # "Scraped N listings from portal"
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except (ValueError, IndexError):
                    pass
    return 0


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
        listings = _parse_listing_count(result.stdout)
        if result.returncode != 0:
            error_msg = result.error or f"exit code {result.returncode}"
            if verbose:
                print(f"\r  ❌ {portal:30s} FAILED ({elapsed:.1f}s, {result.attempts} attempts) — {error_msg[:60]}")
            return {"portal": portal, "healthy": False, "listings": listings, "elapsed": elapsed, "attempts": result.attempts, "error": error_msg}
        if listings == 0:
            if verbose:
                print(f"\r  ❌ {portal:30s} FAILED ({elapsed:.1f}s) — 0 listings")
            return {"portal": portal, "healthy": False, "listings": 0, "elapsed": elapsed, "attempts": result.attempts, "error": "0 listings returned"}
        if verbose:
            print(f"\r  ✅ {portal:30s} {listings:>4d} listings ({elapsed:.1f}s)")
        return {"portal": portal, "healthy": True, "listings": listings, "elapsed": elapsed, "attempts": result.attempts, "error": None}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(portal_keys)) as executor:
        futures = {executor.submit(_check, p): p for p in portal_keys}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    if verbose:
        healthy = sum(1 for r in results if r["healthy"])
        print(f"  ── {healthy}/{len(results)} healthy\n")
    return results


def parallel_scrape(portal_keys: list[str], workers: int = 4, ciudad: str = "medellin", verbose: bool = True) -> list[dict]:
    """Run full scrapes for the given portals in parallel.

    Each scraper writes directly to the database via --output db.
    Prints progress to stdout as each portal completes.
    Returns list of {portal, success, listings, elapsed, error}.
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
        listings = _parse_listing_count(result.stdout)
        if result.returncode != 0:
            error_msg = result.error or f"exit code {result.returncode}"
            if verbose:
                print(f"\r  ❌ {portal:30s} FAILED ({elapsed:.1f}s, {result.attempts} attempts) — {error_msg[:60]}")
            return {"portal": portal, "success": False, "listings": listings, "elapsed": elapsed, "attempts": result.attempts, "error": error_msg}
        if verbose:
            print(f"\r  ✅ {portal:30s} {listings:>5d} listings ({_fmt_time(elapsed)})")
        return {"portal": portal, "success": True, "listings": listings, "elapsed": elapsed, "attempts": result.attempts, "error": None}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_scrape, p): p for p in portal_keys}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    if verbose:
        successful = sum(1 for r in results if r["success"])
        print(f"  ── {successful}/{len(results)} successful\n")
    return results


def validate_results(
    scrape_results: list[dict],
    portals: dict | None = None,
    health_results: list[dict] | None = None,
) -> dict:
    """Validate technical execution results without judging inventory size.

    Returns {passed: bool, warnings: [str]}.
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

        if not success:
            warnings.append(f"{portal}: FAILED — {error or 'unknown error'}")

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


def backup_db(backup_dir: str = "~/Projects/Backups", verbose: bool = True) -> str | None:
    """Run pg_dump on the DATABASE_URL and save to backup_dir.

    Strips &channel_binding=require for pg_dump compatibility.
    Returns the backup file path or None on failure.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None

    backup_path = Path(backup_dir).expanduser()
    backup_path.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    dump_file = backup_path / f"rental_scraper_{timestamp}.sql"

    clean_url = _clean_db_url(db_url)

    if verbose:
        print(f"\n{'='*50}")
        print(f"  DB BACKUP → {dump_file}")
        print(f"{'='*50}")

    try:
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
        return str(dump_file)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        if verbose:
            print(f"  ❌ Backup FAILED — {e}\n")
        return None


def export_to_sheets(ciudad: str = "medellin", verbose: bool = True) -> dict:
    """Mirror the current DB state to Sheets after portal writes complete."""
    result = run_with_retries(
        ["uv", "run", "python", "scripts/export_to_sheets.py", "--city", ciudad],
        timeout=SHEET_TIMEOUT_SECONDS,
        max_attempts=1,
    )
    if verbose and result.returncode != 0:
        print(f"  ❌ Sheet export FAILED — {result.error or 'unknown error'}")
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
) -> int:
    """Run the full 5-phase pipeline: health → backup → scrape → validate → report.

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

    # Phase 2: Backup OLD state BEFORE scraping
    backup_path: str | None = None
    if not skip_backup:
        backup_path = backup_db(verbose=True)

    # Phase 3: Parallel scrape — only healthy portals
    healthy_portals = [r["portal"] for r in health_results if r.get("healthy", False)]
    scrape_results: list[dict] = []
    if healthy_portals:
        scrape_results = parallel_scrape(healthy_portals, workers=workers, ciudad=ciudad, verbose=True)
    else:
        print("\n  ⚠️  No healthy portals to scrape\n")

    # Phase 4: Validation
    validation = validate_results(scrape_results, PORTALS, health_results)
    sheet_result = (
        {"success": True, "skipped": True, "attempts": 0, "elapsed": 0.0, "error": None}
        if skip_sheet
        else export_to_sheets(ciudad)
    )
    if not sheet_result["success"]:
        validation["warnings"].append(
            f"sheets: EXPORT FAILED — {sheet_result.get('error') or 'unknown error'}"
        )
        validation["passed"] = False
    if validation["warnings"]:
        print(f"\n  ⚠️  Validation warnings:")
        for w in validation["warnings"]:
            print(f"     {w}")
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
    )
    print(report)

    try:
        report_path = write_json_report(
            report_dir,
            {
                "health": health_results,
                "scrape": scrape_results,
                "validation": validation,
                "backup_path": backup_path,
                "sheet": sheet_result,
                "total_time": total_time,
            },
        )
        print(f"Execution report: {report_path}")
    except OSError as error:
        print(f"Execution report FAILED: {error}")
        validation["passed"] = False

    return 0 if validation.get("passed", False) else 1
