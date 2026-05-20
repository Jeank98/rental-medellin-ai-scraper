#!/usr/bin/env python3
"""Run all portal scrapers with health check, parallel execution, validation, DB backup, and report."""
import sys
sys.path.insert(0, '.')

import argparse
import logging
from scrape.orchestrator import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Run all 12 portal scrapers with orchestration")
    parser.add_argument("--workers", type=int, default=4, help="Max concurrent scrapers (default: 4)")
    parser.add_argument("--ciudad", default="medellin", help="City filter")
    parser.add_argument("--skip-backup", action="store_true", help="Skip DB backup phase")
    parser.add_argument("--skip-health", action="store_true", help="Skip health check (run all scrapers)")
    parser.add_argument("--verbose", action="store_true", help="Detailed logging")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO)

    print("Starting scraper orchestrator...")
    exit_code = run_pipeline(
        workers=args.workers,
        ciudad=args.ciudad,
        skip_backup=args.skip_backup,
        skip_health=args.skip_health,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
