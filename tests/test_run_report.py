"""Tests for persistent JSON execution reports."""

import json
import tempfile
import unittest
from pathlib import Path

from scrape.run_report import write_json_report


class TestRunReport(unittest.TestCase):
    """Reports are readable by Hermes and survive process completion."""

    def test_writes_timestamped_json_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(write_json_report(directory, {"validation": {"passed": True}}))
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["validation"]["passed"], True)
        self.assertTrue(path.name.startswith("scrape_"))

    def test_preserves_long_errors_in_json(self):
        error = "detailed stderr output " * 80
        with tempfile.TemporaryDirectory() as directory:
            path = Path(write_json_report(directory, {"scrape": [{"error": error}]}))
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["scrape"][0]["error"], error)
