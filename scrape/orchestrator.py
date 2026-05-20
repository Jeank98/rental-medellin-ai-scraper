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
                if verbose:
                    print(f"\r  ❌ {portal:30s} FAILED ({elapsed:.1f}s) — {error_msg[:60]}")
                return {"portal": portal, "healthy": False, "listings": listings, "elapsed": elapsed, "error": error_msg}
            if listings == 0:
                if verbose:
                    print(f"\r  ❌ {portal:30s} FAILED ({elapsed:.1f}s) — 0 listings")
                return {"portal": portal, "healthy": False, "listings": 0, "elapsed": elapsed, "error": "0 listings returned"}
            if verbose:
                print(f"\r  ✅ {portal:30s} {listings:>4d} listings ({elapsed:.1f}s)")
            return {"portal": portal, "healthy": True, "listings": listings, "elapsed": elapsed, "error": None}
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            if verbose:
                print(f"\r  ❌ {portal:30s} TIMEOUT ({elapsed:.1f}s)")
            return {"portal": portal, "healthy": False, "listings": 0, "elapsed": elapsed, "error": "timeout"}
        except Exception as e:
            elapsed = time.monotonic() - start
            if verbose:
                print(f"\r  ❌ {portal:30s} ERROR ({elapsed:.1f}s)")
            return {"portal": portal, "healthy": False, "listings": 0, "elapsed": elapsed, "error": str(e)[:200]}

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
                if verbose:
                    print(f"\r  ❌ {portal:30s} FAILED ({elapsed:.1f}s) — {error_msg[:60]}")
                return {"portal": portal, "success": False, "listings": listings, "elapsed": elapsed, "error": error_msg}
            if verbose:
                print(f"\r  ✅ {portal:30s} {listings:>5d} listings ({_fmt_time(elapsed)})")
            return {"portal": portal, "success": True, "listings": listings, "elapsed": elapsed, "error": None}
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            if verbose:
                print(f"\r  ❌ {portal:30s} TIMEOUT ({elapsed:.1f}s)")
            return {"portal": portal, "success": False, "listings": 0, "elapsed": elapsed, "error": "timeout"}
        except Exception as e:
            elapsed = time.monotonic() - start
            if verbose:
                print(f"\r  ❌ {portal:30s} ERROR ({elapsed:.1f}s)")
            return {"portal": portal, "success": False, "listings": 0, "elapsed": elapsed, "error": str(e)[:200]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_scrape, p): p for p in portal_keys}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    if verbose:
        successful = sum(1 for r in results if r["success"])
        print(f"  ── {successful}/{len(results)} successful\n")
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
    validation = validate_results(scrape_results, PORTALS)
    if validation["warnings"]:
        print(f"\n  ⚠️  Validation warnings:")
        for w in validation["warnings"]:
            print(f"     {w}")
    else:
        print(f"\n  ✅ Validation: PASSED")

    # Phase 5: Report
    total_time = time.monotonic() - start
    report = generate_report(health_results, scrape_results, validation, backup_path, total_time)
    print(report)

    return 0 if validation.get("passed", False) else 1
