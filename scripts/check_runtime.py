#!/usr/bin/env python3
"""Verify that every runtime dependency can be imported."""

from importlib import import_module
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


_IMPORT_CHECKS = {
    "Scrapling": (
        "scrapling",
        "curl_cffi",
        "scrapling.engines.static",
        "scrapling.fetchers.stealth_chrome",
    ),
    "DB": ("psycopg2", "dotenv"),
    "HTML": ("bs4",),
    "browser": ("playwright.sync_api",),
    "Google Sheets": (
        "google.auth.transport.requests",
        "google.oauth2.credentials",
        "googleapiclient.discovery",
        "google_auth_oauthlib.flow",
    ),
}


def _check_scrape_import_chain() -> None:
    """Import ``scrape`` while preventing its dotenv auto-load side effect."""
    dotenv = import_module("dotenv")
    load_dotenv = dotenv.load_dotenv
    dotenv.load_dotenv = lambda *_args, **_kwargs: False
    try:
        import_module("scrape")
    finally:
        dotenv.load_dotenv = load_dotenv


def main() -> int:
    missing: list[str] = []
    for component, modules in _IMPORT_CHECKS.items():
        for module_name in modules:
            try:
                import_module(module_name)
            except ImportError as error:
                missing_name = getattr(error, "name", None) or str(error)
                missing.append(f"{component}: {module_name} (missing {missing_name})")

    try:
        _check_scrape_import_chain()
    except ImportError as error:
        missing_name = getattr(error, "name", None) or str(error)
        missing.append(f"scrape import chain: scrape (missing {missing_name})")

    if missing:
        print("Runtime dependency check failed.", file=sys.stderr)
        for dependency in missing:
            print(f"Missing dependency: {dependency}", file=sys.stderr)
        print("Run `uv sync` from the project root, then retry this check.", file=sys.stderr)
        return 1

    print("Runtime dependency check passed: Scrapling, DB, HTML, browser, Google Sheets, and scrape imports are available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
