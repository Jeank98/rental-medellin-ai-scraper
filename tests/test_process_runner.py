"""Tests for technical command retries."""

import subprocess
import unittest
from unittest import mock

from scrape.process_runner import run_with_retries


class TestProcessRunner(unittest.TestCase):
    """Retries recover transient failures without retrying success."""

    def test_retries_failed_command_then_returns_success(self):
        failure = subprocess.CompletedProcess([], 1, "", "temporary failure")
        success = subprocess.CompletedProcess([], 0, "ok", "")

        with mock.patch("scrape.process_runner.subprocess.run", side_effect=[failure, success]), mock.patch(
            "scrape.process_runner.time.sleep"
        ) as sleep:
            result = run_with_retries(["command"], timeout=10, max_attempts=2, retry_delay=3)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.attempts, 2)
        sleep.assert_called_once_with(3)

    def test_exhausted_timeout_is_reported_as_failure(self):
        timeout = subprocess.TimeoutExpired(["command"], 10)

        with mock.patch("scrape.process_runner.subprocess.run", side_effect=timeout), mock.patch(
            "scrape.process_runner.time.sleep"
        ):
            result = run_with_retries(["command"], timeout=10, max_attempts=2, retry_delay=0)

        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.error, "timeout")
        self.assertEqual(result.attempts, 2)

    def test_exhausted_failure_preserves_full_stderr(self):
        stderr = " ".join(["detailed failure output"] * 80)
        failure = subprocess.CompletedProcess([], 1, "", stderr)

        with mock.patch("scrape.process_runner.subprocess.run", return_value=failure):
            result = run_with_retries(["command"], timeout=10, max_attempts=1)

        self.assertEqual(result.error, stderr)
        self.assertEqual(result.stderr, stderr)
