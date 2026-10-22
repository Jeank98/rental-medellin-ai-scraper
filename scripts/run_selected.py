#!/usr/bin/env python3
"""Run the south-of-Medellin portals for the canonical five-city scope.

Full mode is intentionally conservative: every requested portal is scraped
once for every requested city and validated in memory, a database backup must
succeed, only then are the per-portal/per-city snapshots replaced atomically,
and the unfiltered Sheets mirror is refreshed last.  Sample mode makes no
credential, backup, CSV, database, or Sheets calls.

Usage::

    uv run python scripts/run_selected.py
    uv run python scripts/run_selected.py --sample-only --max-pages 2
    uv run python scripts/run_selected.py --cities medellin "la estrella"
    uv run python scripts/run_selected.py --portals lonjainmobiliariadelsur --skip-sheet

The default scope is all four portals and all five canonical cities
(``la-estrella`` is the existing storage key for La Estrella).
"""

import argparse
import concurrent.futures
import importlib
import sys
from typing import Callable

sys.path.insert(0, ".")

from scrape import orchestrator
from scrape.cities import CITY_LABELS, resolve_city
from scrape.run_report import write_json_report

SELECTED_PORTALS = (
    "escalainmobiliaria",
    "arrendamientosenvigado",
    "inmobiliarialaestrella",
    "lonjainmobiliariadelsur",
)
DEFAULT_CITIES = tuple(CITY_LABELS)
MAX_WORKERS = 4
DEFAULT_REPORT_DIR = "runtime/scraper-runs"

ROW_FIELDS = frozenset(
    {
        "id",
        "portal",
        "tipo",
        "precio",
        "area",
        "habitaciones",
        "banos",
        "parqueaderos",
        "estrato",
        "barrio",
        "url",
    }
)
INT_FIELDS = ("precio", "area", "habitaciones", "banos", "parqueaderos", "estrato")
TEXT_FIELDS = ("id", "portal", "tipo", "barrio", "url")


def _load_portal_module(portal: str):
    """Import one portal module lazily and require the shared batch interface."""
    config = orchestrator.PORTALS[portal]
    module = importlib.import_module(f"scrape.{config['module']}")
    if not callable(getattr(module, "scrape_cities", None)):
        raise RuntimeError(f"{portal} does not expose scrape_cities")
    return module


def _load_environment() -> None:
    """Load ``.env`` only for full runs, never for sample mode."""
    from dotenv import load_dotenv

    load_dotenv()


def _write_portal_city(rows: list[dict], portal: str, ciudad: str) -> int:
    """Import the existing DB writer only when a full run actually writes."""
    from scrape.db_writer import write_to_db

    return write_to_db(rows, portal, ciudad=ciudad)


def _canonical_cities(values: list[str] | None) -> list[str]:
    """Resolve the requested cities; only ``None`` means the default scope."""
    if values is None:
        return list(DEFAULT_CITIES)
    if not values:
        raise ValueError(
            "cities must not be empty; omit it to use the five-city default"
        )
    cities: list[str] = []
    for value in values:
        key = resolve_city(value)
        if key not in cities:
            cities.append(key)
    return cities


def _canonical_portals(values: list[str] | None) -> list[str]:
    """Resolve the requested portals; only ``None`` means the default scope."""
    if values is None:
        return list(SELECTED_PORTALS)
    if not values:
        raise ValueError("portals must not be empty; omit it to use all four portals")
    unknown = [value for value in values if value not in SELECTED_PORTALS]
    if unknown:
        raise ValueError(f"unsupported portal(s): {', '.join(unknown)}")
    portals: list[str] = []
    for value in values:
        if value not in portals:
            portals.append(value)
    return portals


def _validate_rows(portal: str, city: str, rows: object) -> list[dict]:
    """Reject any batch that could be written under the wrong scope."""
    if not isinstance(rows, list):
        raise ValueError(f"{portal}/{city}: expected a list of rows")
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{portal}/{city}: row {index} is not an object")
        if set(row) != ROW_FIELDS:
            unexpected = sorted(set(row) - ROW_FIELDS)
            missing = sorted(ROW_FIELDS - set(row))
            raise ValueError(
                f"{portal}/{city}: row {index} fields mismatch "
                f"(unexpected={unexpected}, missing={missing})"
            )
        for field in TEXT_FIELDS:
            if not isinstance(row[field], str):
                raise ValueError(f"{portal}/{city}: row {index} {field} is not text")
        for field in INT_FIELDS:
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{portal}/{city}: row {index} {field} is not an int")
        if not row["id"].strip():
            raise ValueError(f"{portal}/{city}: row {index} has an empty id")
        if row["portal"] != portal:
            raise ValueError(
                f"{portal}/{city}: row {index} belongs to {row['portal']!r}"
            )
        if row["id"] in seen_ids:
            raise ValueError(f"{portal}/{city}: duplicate id {row['id']!r}")
        seen_ids.add(row["id"])
    return rows


def _validate_batches(
    portal: str, cities: list[str], result: object
) -> dict[str, list[dict]]:
    """Require exactly the requested city keys, each with a validated batch."""
    if not isinstance(result, dict):
        raise ValueError(f"{portal}: scrape_cities returned {type(result).__name__}")
    missing = [city for city in cities if city not in result]
    extra = [city for city in result if city not in cities]
    if missing or extra:
        raise ValueError(
            f"{portal}: city scope mismatch (missing={missing}, unexpected={extra})"
        )
    return {city: _validate_rows(portal, city, result[city]) for city in cities}


def _validate_global_ids(
    portals: list[str],
    cities: list[str],
    batches: dict[str, dict[str, list[dict]]],
) -> None:
    """Reject an id shared by two portal/city batches.

    ``listings.id`` is the table's single primary key and the upsert rewrites
    ``ciudad``, so the same id in two batches means the later snapshot would
    silently move the earlier listing into another city while both writes
    report success.
    """
    owner: dict[str, tuple[str, str]] = {}
    for portal in portals:
        for city in cities:
            for row in batches[portal][city]:
                row_id = row["id"]
                previous = owner.get(row_id)
                if previous is not None:
                    raise ValueError(
                        f"duplicate id {row_id!r} across portal/city batches: "
                        f"{previous[0]}/{previous[1]} and {portal}/{city}"
                    )
                owner[row_id] = (portal, city)


def _summary(portal: str, cities: list[str], batches: dict[str, list[dict]]) -> dict:
    city_counts = {city: len(batches[city]) for city in cities}
    return {
        "portal": portal,
        "status": "success",
        "cities": city_counts,
        "total": sum(city_counts.values()),
        "error": None,
    }


def _collect_portal(
    portal: str,
    cities: list[str],
    *,
    sample_only: bool,
    max_pages: int | None,
    verbose: bool,
    loader: Callable,
) -> tuple[dict, dict[str, list[dict]]]:
    module = loader(portal)
    raw = module.scrape_cities(
        cities,
        sample_only=sample_only,
        max_pages=max_pages,
        verbose=verbose,
    )
    batches = _validate_batches(portal, cities, raw)
    return _summary(portal, cities, batches), batches


def _collect_all(
    portals: list[str],
    cities: list[str],
    *,
    sample_only: bool,
    max_pages: int | None,
    verbose: bool,
    workers: int,
    loader: Callable,
) -> tuple[list[dict], dict[str, dict[str, list[dict]]]]:
    """Scrape every portal once, keeping deterministic result ordering."""
    results: dict[str, dict] = {}
    batches: dict[str, dict[str, list[dict]]] = {}

    def _run(portal: str):
        return _collect_portal(
            portal,
            cities,
            sample_only=sample_only,
            max_pages=max_pages,
            verbose=verbose,
            loader=loader,
        )

    worker_count = min(workers, len(portals))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {pool.submit(_run, portal): portal for portal in portals}
        for future, portal in futures.items():
            try:
                summary, portal_batches = future.result()
            except Exception as error:
                city_counts = {city: 0 for city in cities}
                results[portal] = {
                    "portal": portal,
                    "status": "failed",
                    "cities": city_counts,
                    "total": 0,
                    "error": f"{type(error).__name__}: {error}",
                }
            else:
                results[portal] = summary
                batches[portal] = portal_batches
    return [results[portal] for portal in portals], batches


def _write_batches(
    portals: list[str],
    cities: list[str],
    batches: dict[str, dict[str, list[dict]]],
    writer: Callable,
) -> tuple[list[dict], str | None]:
    """Replace each non-empty portal+city snapshot, stopping at first failure."""
    writes: list[dict] = []
    for portal in portals:
        for city in cities:
            rows = batches[portal][city]
            if not rows:
                writes.append(
                    {
                        "portal": portal,
                        "ciudad": city,
                        "rows": 0,
                        "inserted": 0,
                        "status": "empty",
                    }
                )
                continue
            try:
                inserted = writer(rows, portal, ciudad=city)
            except Exception as error:
                writes.append(
                    {
                        "portal": portal,
                        "ciudad": city,
                        "rows": len(rows),
                        "inserted": 0,
                        "status": "failed",
                    }
                )
                return (
                    writes,
                    f"{portal}/{city}: write raised {type(error).__name__}: {error}",
                )
            if isinstance(inserted, bool) or not isinstance(inserted, int):
                writes.append(
                    {
                        "portal": portal,
                        "ciudad": city,
                        "rows": len(rows),
                        "inserted": 0,
                        "status": "failed",
                    }
                )
                return writes, f"{portal}/{city}: writer did not return a count"
            if inserted != len(rows):
                writes.append(
                    {
                        "portal": portal,
                        "ciudad": city,
                        "rows": len(rows),
                        "inserted": inserted,
                        "status": "failed",
                    }
                )
                return writes, (
                    f"{portal}/{city}: wrote {inserted}/{len(rows)} rows; "
                    "previous snapshot preserved"
                )
            writes.append(
                {
                    "portal": portal,
                    "ciudad": city,
                    "rows": len(rows),
                    "inserted": inserted,
                    "status": "written",
                }
            )
    return writes, None


def _backup_status(outcome: object) -> str:
    if isinstance(outcome, dict):
        return str(outcome.get("status") or "unknown")
    if isinstance(outcome, str) and outcome:
        return "success"
    return "skipped"


def _print_summary(report: dict) -> None:
    print(f"\nMode: {report['mode']}")
    print(f"Portals: {', '.join(report['portals']) or '(none)'}")
    print(f"Cities: {', '.join(report['cities']) or '(none)'}")
    for result in report["results"]:
        counts = ", ".join(
            f"{city}={count}" for city, count in result["cities"].items()
        )
        print(
            f"  {result['portal']}: {result['status']} total={result['total']} ({counts})"
        )
        if result["error"]:
            print(f"    error: {result['error']}")
    if report["backup"] is not None:
        print(
            f"Backup: {report['backup'].get('status')} {report['backup'].get('path') or ''}".rstrip()
        )
    if report["writes"]:
        written = sum(entry["inserted"] for entry in report["writes"])
        snapshots = sum(1 for entry in report["writes"] if entry["status"] == "written")
        empty_entries = [
            entry for entry in report["writes"] if entry["status"] == "empty"
        ]
        print(
            f"DB writes: {snapshots} snapshot(s), {written} listing(s), {len(empty_entries)} empty city skip(s)"
        )
        for entry in empty_entries:
            print(
                f"  empty city: {entry['portal']}/{entry['ciudad']} "
                "(no rows; existing snapshot retained)"
            )
    if report["sheet"] is not None:
        if report["sheet"].get("skipped"):
            print(f"Sheets: skipped ({report['sheet'].get('reason')})")
        else:
            print(
                f"Sheets: {'updated' if report['sheet'].get('success') else 'failed'}"
            )
    for error in report["errors"]:
        print(f"Error: {error}", file=sys.stderr)
    if report.get("report_path"):
        print(f"Execution report: {report['report_path']}")
    print(f"Status: {report['status']} (exit {report['exit_code']})")


def _finish(report: dict, report_dir: str, report_writer: Callable) -> dict:
    """Persist the structured report; a write failure fails the run."""
    payload = {key: value for key, value in report.items() if key != "report_path"}
    try:
        report["report_path"] = report_writer(report_dir, payload)
    except OSError as error:
        report["status"] = "failed"
        report["exit_code"] = 1
        report["errors"].append(f"report write failed: {error}")
    return report


def run_selected(
    *,
    portals: list[str] | None = None,
    cities: list[str] | None = None,
    sample_only: bool = False,
    max_pages: int | None = None,
    workers: int = MAX_WORKERS,
    skip_sheet: bool = False,
    report_dir: str = DEFAULT_REPORT_DIR,
    verbose: bool = False,
    loader: Callable = _load_portal_module,
    environment_loader: Callable = _load_environment,
    backup: Callable = orchestrator.backup_db,
    writer: Callable = _write_portal_city,
    exporter: Callable = orchestrator.export_to_sheets,
    report_writer: Callable = write_json_report,
) -> dict:
    """Run the selected portals and return the structured execution report.

    ``exit_code`` is 0 on success, 1 for a technical failure, and 2 for invalid
    arguments.  No database or Sheets call happens before every requested
    portal/city batch has been collected and validated.
    """
    report: dict = {
        "mode": "sample" if sample_only else "full",
        "status": "failed",
        "portals": [],
        "cities": [],
        "max_pages": max_pages,
        "results": [],
        "backup": None,
        "writes": [],
        "sheet": None,
        "errors": [],
        "exit_code": 2,
    }

    try:
        report["cities"] = _canonical_cities(cities)
        report["portals"] = _canonical_portals(portals)
        if isinstance(workers, bool) or not isinstance(workers, int):
            raise ValueError("workers must be an integer")
        if not 1 <= workers <= MAX_WORKERS:
            raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
        if max_pages is not None:
            if not isinstance(max_pages, int) or isinstance(max_pages, bool):
                raise ValueError("max-pages must be an integer")
            if max_pages <= 0:
                raise ValueError("max-pages must be positive")
            if not sample_only:
                raise ValueError(
                    "max-pages is a sample cap; full runs need complete batches "
                    "(use --sample-only or drop --max-pages)"
                )
    except ValueError as error:
        report["errors"].append(str(error))
        return report

    results, batches = _collect_all(
        report["portals"],
        report["cities"],
        sample_only=sample_only,
        max_pages=max_pages,
        verbose=verbose,
        workers=workers,
        loader=loader,
    )
    report["results"] = results
    failures = [result for result in results if result["status"] != "success"]
    if failures:
        report["errors"].extend(
            f"{result['portal']}: {result['error']}" for result in failures
        )
        report["exit_code"] = 1
        return _finish(report, report_dir, report_writer)

    try:
        _validate_global_ids(report["portals"], report["cities"], batches)
    except ValueError as error:
        report["errors"].append(str(error))
        report["exit_code"] = 1
        return _finish(report, report_dir, report_writer)

    if sample_only:
        report["status"] = "success"
        report["exit_code"] = 0
        return _finish(report, report_dir, report_writer)

    try:
        environment_loader()
    except Exception as error:
        report["errors"].append(
            f"environment load failed: {type(error).__name__}: {error}"
        )
        report["exit_code"] = 1
        return _finish(report, report_dir, report_writer)
    try:
        backup_outcome = backup(verbose=verbose)
    except Exception as error:
        # Only the type name is persisted: a URL parse error embeds the
        # connection netloc, credentials included, in its message.
        backup_outcome = {
            "status": "failed",
            "path": None,
            "error": f"database backup raised {type(error).__name__}",
            "reason": "backup_exception",
        }
    report["backup"] = (
        backup_outcome
        if isinstance(backup_outcome, dict)
        else {
            "status": _backup_status(backup_outcome),
            "path": None,
            "error": None,
            "reason": None,
        }
    )
    if _backup_status(report["backup"]) != "success":
        report["errors"].append(
            f"required DB backup did not succeed: {report['backup'].get('status')}"
        )
        report["exit_code"] = 1
        return _finish(report, report_dir, report_writer)

    writes, write_error = _write_batches(
        report["portals"], report["cities"], batches, writer
    )
    report["writes"] = writes
    if write_error:
        report["errors"].append(write_error)
        report["exit_code"] = 1
        return _finish(report, report_dir, report_writer)

    if skip_sheet:
        report["sheet"] = {"skipped": True, "reason": "operator"}
    else:
        try:
            sheet_outcome = exporter(verbose=verbose)
        except Exception as error:
            sheet_outcome = {
                "success": False,
                "error": f"{type(error).__name__}: {error}",
            }
        report["sheet"] = (
            sheet_outcome
            if isinstance(sheet_outcome, dict)
            else {"success": bool(sheet_outcome)}
        )
        if not report["sheet"].get("success"):
            report["errors"].append(
                f"Sheets export failed: {report['sheet'].get('error') or 'unknown error'}"
            )
            report["exit_code"] = 1
            report["status"] = "failed"
            return _finish(report, report_dir, report_writer)

    report["status"] = "success"
    report["exit_code"] = 0
    return _finish(report, report_dir, report_writer)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape the four southern rental portals for canonical cities. "
            "Full runs require a successful DB backup before writing and "
            "refresh the unfiltered Sheets mirror afterwards."
        )
    )
    parser.add_argument(
        "--portals",
        nargs="+",
        choices=SELECTED_PORTALS,
        default=None,
        metavar="PORTAL",
        help=f"Portals to run (default: all of {', '.join(SELECTED_PORTALS)})",
    )
    parser.add_argument(
        "--cities",
        nargs="+",
        default=None,
        metavar="CITY",
        help=(
            "Cities to run, as keys, accented labels, or hyphenated aliases "
            '(default: all five; quote "la estrella")'
        ),
    )
    parser.add_argument(
        "--sample-only",
        action="store_true",
        help="Collect bounded sample batches and make no backup/DB/CSV/Sheets calls",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        metavar="N",
        help="Sample-mode page cap; rejected for full runs",
    )
    parser.add_argument(
        "--workers",
        type=int,
        choices=range(1, MAX_WORKERS + 1),
        default=MAX_WORKERS,
        help=f"Concurrent portal collections, 1-{MAX_WORKERS} (default: {MAX_WORKERS})",
    )
    parser.add_argument(
        "--skip-sheet",
        action="store_true",
        help="Skip the post-write Sheets mirror refresh",
    )
    parser.add_argument(
        "--report-dir",
        default=DEFAULT_REPORT_DIR,
        help=f"Directory for timestamped JSON reports (default: {DEFAULT_REPORT_DIR})",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Detailed scrape logging"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_selected(
        portals=args.portals,
        cities=args.cities,
        sample_only=args.sample_only,
        max_pages=args.max_pages,
        workers=args.workers,
        skip_sheet=args.skip_sheet,
        report_dir=args.report_dir,
        verbose=args.verbose,
    )
    _print_summary(report)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
