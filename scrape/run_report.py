"""Persistent JSON reports for automated scraper runs."""

from datetime import datetime, timezone
import json
from pathlib import Path


def write_json_report(report_dir: str, payload: dict) -> str:
    """Write one timestamped, atomically replaced execution report."""
    directory = Path(report_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    report_path = directory / f"scrape_{timestamp:%Y%m%dT%H%M%SZ}.json"
    report_payload = {
        "created_at": timestamp.isoformat(),
        **payload,
    }
    temporary_path = report_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(report_payload, indent=2, ensure_ascii=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(report_path)
    return str(report_path)
