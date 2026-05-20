"""
Orchestrator module — 5-phase pipeline for scraping all 12 Colombian real
estate portals in parallel with health checks, validation, and DB backup.
"""

import concurrent.futures
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from scrape.report import generate_report

PORTALS = {
    "maxibienes": {"module": "maxibienes", "min_listings": 30},
    "albertoalvarez": {"module": "albertoalvarez", "min_listings": 50},
    "alnago": {"module": "alnago", "min_listings": 5},
    "arrendamientosdelnorte": {"module": "arrendamientosdelnorte", "min_listings": 100, "script": "adn"},
    "arrendamientosmonserrate": {"module": "arrendamientosmonserrate", "min_listings": 20, "script": "monserrate"},
    "arrendamientossantafe": {"module": "arrendamientossantafe", "min_listings": 30, "script": "asf"},
    "arrendamientosvillacruz": {"module": "arrendamientosvillacruz", "min_listings": 30, "script": "villacruz"},
    "coninsa": {"module": "coninsa", "min_listings": 150},
    "habitamos": {"module": "habitamos", "min_listings": 100},
    "merinohermanos": {"module": "merinohermanos", "min_listings": 70},
    "metrocasas": {"module": "metrocasas", "min_listings": 5},
    "santillana": {"module": "santillana", "min_listings": 30},
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


def health_check(portals: dict, timeout: int = 300) -> list[dict]:
    """Run each scraper in sample-only mode to verify it works.

    All scrapers run in parallel via ThreadPoolExecutor.
    Returns list of {portal, healthy, listings, elapsed, error}.
    """
    results: list[dict] = []
    portal_keys = list(portals.keys())

    def _check(portal: str) -> dict:
        script = _script_name(portal)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                ["uv", "run", "python", f"scripts/scrape_{script}.py", "--sample-only", "--output", "csv"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = time.monotonic() - start
            listings = _parse_listing_count(proc.stdout)
            if proc.returncode != 0:
                error_msg = proc.stderr[:200].strip() if proc.stderr else f"exit code {proc.returncode}"
                return {"portal": portal, "healthy": False, "listings": listings, "elapsed": elapsed, "error": error_msg}
            if listings == 0:
                return {"portal": portal, "healthy": False, "listings": 0, "elapsed": elapsed, "error": "0 listings returned"}
            return {"portal": portal, "healthy": True, "listings": listings, "elapsed": elapsed, "error": None}
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            return {"portal": portal, "healthy": False, "listings": 0, "elapsed": elapsed, "error": "timeout"}
        except Exception as e:
            elapsed = time.monotonic() - start
            return {"portal": portal, "healthy": False, "listings": 0, "elapsed": elapsed, "error": str(e)[:200]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(portal_keys)) as executor:
        futures = {executor.submit(_check, p): p for p in portal_keys}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    return results


def parallel_scrape(portal_keys: list[str], workers: int = 4, ciudad: str = "medellin") -> list[dict]:
    """Run full scrapes for the given portals in parallel.

    Each scraper writes directly to the database via --output db.
    Uses ThreadPoolExecutor(max_workers=workers) for concurrency.
    Returns list of {portal, success, listings, elapsed, error}.
    """
    results: list[dict] = []

    def _scrape(portal: str) -> dict:
        script = _script_name(portal)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                ["uv", "run", "python", f"scripts/scrape_{script}.py", "--output", "db", "--ciudad", ciudad],
                capture_output=True,
                text=True,
                timeout=3600,
            )
            elapsed = time.monotonic() - start
            listings = _parse_listing_count(proc.stdout)
            if proc.returncode != 0:
                error_msg = proc.stderr[:200].strip() if proc.stderr else f"exit code {proc.returncode}"
                return {"portal": portal, "success": False, "listings": listings, "elapsed": elapsed, "error": error_msg}
            return {"portal": portal, "success": True, "listings": listings, "elapsed": elapsed, "error": None}
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            return {"portal": portal, "success": False, "listings": 0, "elapsed": elapsed, "error": "timeout"}
        except Exception as e:
            elapsed = time.monotonic() - start
            return {"portal": portal, "success": False, "listings": 0, "elapsed": elapsed, "error": str(e)[:200]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_scrape, p): p for p in portal_keys}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    return results


def validate_results(scrape_results: list[dict], portals: dict) -> dict:
    """Validate scrape results against minimum listing thresholds.

    Returns {passed: bool, warnings: [str]}.
    """
    warnings: list[str] = []

    for r in scrape_results:
        portal = r.get("portal", "?")
        listings = r.get("listings", 0)
        min_listings = portals.get(portal, {}).get("min_listings", 0)
        error = r.get("error")
        success = r.get("success", False)

        if not success:
            warnings.append(f"{portal}: FAILED — {error or 'unknown error'}")
        elif listings < min_listings:
            warnings.append(f"{portal}: {listings} listings (min {min_listings})")

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


def backup_db(backup_dir: str = "~/Projects/Backups") -> str | None:
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

    try:
        subprocess.run(
            ["pg_dump", clean_url, "--no-owner", "--no-acl", "-f", str(dump_file)],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
        return str(dump_file)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def run_pipeline(
    workers: int = 4,
    ciudad: str = "medellin",
    skip_backup: bool = False,
    skip_health: bool = False,
) -> int:
    """Run the full 5-phase pipeline: health → backup → scrape → validate → report.

    Returns 0 on success, 1 if validation fails.
    """
    start = time.monotonic()

    # Phase 1: Health check
    health_results: list[dict] = []
    if skip_health:
        for portal in PORTALS:
            health_results.append({
                "portal": portal, "healthy": True,
                "listings": 0, "elapsed": 0.0, "error": None,
            })
    else:
        health_results = health_check(PORTALS)

    # Phase 2: Backup OLD state BEFORE scraping
    backup_path: str | None = None
    if not skip_backup:
        backup_path = backup_db()

    # Phase 3: Parallel scrape — only healthy portals
    healthy_portals = [r["portal"] for r in health_results if r.get("healthy", False)]
    scrape_results: list[dict] = []
    if healthy_portals:
        scrape_results = parallel_scrape(healthy_portals, workers=workers, ciudad=ciudad)

    # Phase 4: Validation
    validation = validate_results(scrape_results, PORTALS)

    # Phase 5: Report
    total_time = time.monotonic() - start
    report = generate_report(health_results, scrape_results, validation, backup_path, total_time)
    print(report)

    return 0 if validation.get("passed", False) else 1
