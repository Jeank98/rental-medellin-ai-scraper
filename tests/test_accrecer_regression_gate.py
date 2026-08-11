"""Unit tests for the regression gate's logic — synthetic fixtures only.

These test the gate's internal comparison, validation, and hashing logic
using synthetic JSON data — no live portals or network needed.
"""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

# Import the gate module for its helper functions
sys_path = str(Path(__file__).resolve().parent)
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)

from accrecer_regression_gate import (  # type: ignore[import-untyped]
    cmd_compare,
    cmd_verify_protected,
    EXPECTED_PORTALS_13,
    RESULT_EXPECTED_KEYS,
)


class TestKeysExact(unittest.TestCase):
    """Given the expected portal list, then it matches the current 13-key registry."""

    def test_expected_portals_match_current_registry(self):
        from scrape.orchestrator import PORTALS
        actual = sorted(PORTALS.keys())
        expected = sorted(EXPECTED_PORTALS_13)
        self.assertEqual(actual, expected,
                         "EXPECTED_PORTALS_13 must match scrape.orchestrator.PORTALS")


class TestHealthResultSchema(unittest.TestCase):
    """Given a health result dict, then it has exactly the required keys."""

    def test_valid_health_result(self):
        result = {"portal": "test", "healthy": True, "listings": 10,
                  "elapsed": 1.5, "error": None}
        self.assertEqual(set(result.keys()), RESULT_EXPECTED_KEYS)

    def test_missing_key_detected(self):
        result = {"portal": "test", "healthy": True, "listings": 10, "elapsed": 1.5}
        self.assertNotEqual(set(result.keys()), RESULT_EXPECTED_KEYS)


class TestCompareBaselinePost(unittest.TestCase):
    """Given synthetic baseline + post health JSON, then compare catches regressions."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, name: str, data: dict) -> str:
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as fh:
            json.dump(data, fh)
        return path

    def test_all_healthy_remains_healthy(self):
        """Given all portals healthy in both, then compare passes."""
        baseline = {
            "portal_a": {"portal": "portal_a", "healthy": True, "listings": 10, "elapsed": 1.0, "error": None},
            "portal_b": {"portal": "portal_b", "healthy": True, "listings": 20, "elapsed": 2.0, "error": None},
        }
        post = dict(baseline)  # identical — all still healthy
        bpath = self._write("baseline.json", baseline)
        ppath = self._write("post.json", post)

        import argparse
        ns = argparse.Namespace(baseline=bpath, post=ppath, new_portal=None)
        rc = cmd_compare(ns)
        self.assertEqual(rc, 0, "Identical healthy snapshots must pass")

    def test_healthy_to_unhealthy_fails(self):
        """Given a baseline-healthy portal becomes unhealthy, then compare fails."""
        baseline = {
            "portal_a": {"portal": "portal_a", "healthy": True, "listings": 10, "elapsed": 1.0, "error": None},
        }
        post = {
            "portal_a": {"portal": "portal_a", "healthy": False, "listings": 0, "elapsed": 30.0, "error": "timeout"},
        }
        bpath = self._write("baseline_hu.json", baseline)
        ppath = self._write("post_hu.json", post)

        import argparse
        ns = argparse.Namespace(baseline=bpath, post=ppath, new_portal=None)
        rc = cmd_compare(ns)
        self.assertNotEqual(rc, 0, "Healthy-to-unhealthy must fail")

    def test_already_unhealthy_not_a_regression(self):
        """Given a portal was already unhealthy at baseline, it passes."""
        baseline = {
            "portal_a": {"portal": "portal_a", "healthy": False, "listings": 0, "elapsed": 30.0, "error": "timeout"},
        }
        post = dict(baseline)  # still unhealthy — consistent
        bpath = self._write("baseline_au.json", baseline)
        ppath = self._write("post_au.json", post)

        import argparse
        ns = argparse.Namespace(baseline=bpath, post=ppath, new_portal=None)
        rc = cmd_compare(ns)
        self.assertEqual(rc, 0, "Already-unhealthy portals don't block compare")

    def test_new_portal_missing_fails(self):
        """Given a new portal not in post, then compare fails."""
        baseline = {
            "portal_a": {"portal": "portal_a", "healthy": True, "listings": 10, "elapsed": 1.0, "error": None},
        }
        post = dict(baseline)
        bpath = self._write("baseline_np.json", baseline)
        ppath = self._write("post_np.json", post)

        import argparse
        ns = argparse.Namespace(baseline=bpath, post=ppath, new_portal="missing_portal")
        rc = cmd_compare(ns)
        self.assertNotEqual(rc, 0, "Missing new portal must fail")

    def test_new_portal_unhealthy_fails(self):
        """Given new portal exists but is unhealthy, then compare fails."""
        baseline = {
            "portal_a": {"portal": "portal_a", "healthy": True, "listings": 10, "elapsed": 1.0, "error": None},
        }
        post = {
            "portal_a": {"portal": "portal_a", "healthy": True, "listings": 10, "elapsed": 1.0, "error": None},
            "new": {"portal": "new", "healthy": False, "listings": 0, "elapsed": 5.0, "error": "0 listings returned"},
        }
        bpath = self._write("baseline_nu.json", baseline)
        ppath = self._write("post_nu.json", post)

        import argparse
        ns = argparse.Namespace(baseline=bpath, post=ppath, new_portal="new")
        rc = cmd_compare(ns)
        self.assertNotEqual(rc, 0, "Unhealthy new portal must fail")

    def test_missing_portal_from_post_fails(self):
        """Given a portal in baseline but missing from post, then compare fails."""
        baseline = {
            "portal_a": {"portal": "portal_a", "healthy": True, "listings": 10, "elapsed": 1.0, "error": None},
            "portal_b": {"portal": "portal_b", "healthy": True, "listings": 20, "elapsed": 2.0, "error": None},
        }
        post = {
            "portal_a": {"portal": "portal_a", "healthy": True, "listings": 10, "elapsed": 1.0, "error": None},
        }
        bpath = self._write("baseline_miss.json", baseline)
        ppath = self._write("post_miss.json", post)

        import argparse
        ns = argparse.Namespace(baseline=bpath, post=ppath, new_portal=None)
        rc = cmd_compare(ns)
        self.assertNotEqual(rc, 0, "Missing portal from post must fail")


class TestVerifyProtected(unittest.TestCase):
    """Given synthetic manifest files, then verify-protected catches changes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, name: str, content: str) -> str:
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as fh:
            fh.write(content)
        return path

    def _make_manifest(self, files: dict[str, dict], paths: list[str] | None = None) -> str:
        if paths is None:
            paths = list(files.keys())
        doc = {"paths": paths, "files": files}
        path = os.path.join(self.tmpdir, "manifest.json")
        with open(path, "w") as fh:
            json.dump(doc, fh)
        return path

    def test_added_file_fails(self):
        """Given a new file not in manifest, then verify-protected fails."""
        subdir = os.path.join(self.tmpdir, "protected_dir")
        os.makedirs(subdir, exist_ok=True)
        Path(subdir, "tracked.txt").write_text("hello world\n")
        Path(subdir, "untracked.txt").write_text("extra file not in manifest\n")

        import hashlib
        manifest_files = {
            "protected_dir/tracked.txt": {
                "rel_path": "protected_dir/tracked.txt",
                "sha256": hashlib.sha256(b"hello world\n").hexdigest(),
                "diff_binary": "",
            }
        }
        manifest = self._make_manifest(manifest_files, paths=["protected_dir"])

        import argparse
        ns = argparse.Namespace(manifest=manifest)

        old_cwd = os.getcwd()
        os.chdir(self.tmpdir)
        try:
            import accrecer_regression_gate as gate
            saved_root = gate.REPO_ROOT
            gate.REPO_ROOT = Path(self.tmpdir)

            try:
                rc = cmd_verify_protected(ns)
                self.assertNotEqual(rc, 0, "New file not in manifest must fail")
            finally:
                gate.REPO_ROOT = saved_root
        finally:
            os.chdir(old_cwd)


class TestSHA256Consistency(unittest.TestCase):
    """Given the same file content, then SHA-256 is deterministic."""

    def test_same_content_same_hash(self):
        content = b"test content that should hash consistently\n"
        h1 = hashlib.sha256(content).hexdigest()
        h2 = hashlib.sha256(content).hexdigest()
        self.assertEqual(h1, h2)

    def test_different_content_different_hash(self):
        h1 = hashlib.sha256(b"content A").hexdigest()
        h2 = hashlib.sha256(b"content B").hexdigest()
        self.assertNotEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
