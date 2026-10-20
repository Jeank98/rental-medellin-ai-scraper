"""Retention tests for DB backups created by the orchestrator."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scrape.orchestrator import BACKUP_PREFIX, BACKUP_RETENTION, _prune_old_backups, backup_db


def _make_dumps(directory: Path, timestamps: list[str]) -> list[Path]:
    created = []
    for stamp in timestamps:
        path = directory / f"{BACKUP_PREFIX}{stamp}.sql"
        path.write_text("dump")
        created.append(path)
    return created


class PruneOldBackupsTests(unittest.TestCase):
    def test_keeps_only_newest_three_dumps(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _make_dumps(
                directory,
                [
                    "20260101_000000",
                    "20260102_000000",
                    "20260103_000000",
                    "20260104_000000",
                    "20260105_000000",
                ],
            )
            removed = _prune_old_backups(directory, keep=3, verbose=False)

            remaining = sorted(p.name for p in directory.glob(f"{BACKUP_PREFIX}*.sql"))
            self.assertEqual(
                remaining,
                [
                    f"{BACKUP_PREFIX}20260103_000000.sql",
                    f"{BACKUP_PREFIX}20260104_000000.sql",
                    f"{BACKUP_PREFIX}20260105_000000.sql",
                ],
            )
            self.assertEqual(len(removed), 2)

    def test_unrelated_sql_files_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _make_dumps(directory, [f"2026010{i}_000000" for i in range(1, 6)])
            other = directory / "manual_export.sql"
            other.write_text("keep me")

            _prune_old_backups(directory, keep=3, verbose=False)

            self.assertTrue(other.exists())

    def test_no_deletion_when_at_retention_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _make_dumps(directory, ["20260101_000000", "20260102_000000", "20260103_000000"])

            removed = _prune_old_backups(directory, keep=3, verbose=False)

            self.assertEqual(removed, [])
            self.assertEqual(len(list(directory.glob(f"{BACKUP_PREFIX}*.sql"))), 3)

    def test_default_retention_is_three(self):
        self.assertEqual(BACKUP_RETENTION, 3)


class BackupDbRetentionTests(unittest.TestCase):
    def test_successful_backup_prunes_to_retention_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _make_dumps(
                directory,
                ["20260101_000000", "20260102_000000", "20260103_000000"],
            )

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_text("fresh dump")

            with patch.dict(os.environ, {"DATABASE_URL": "postgresql://u:p@h:5432/db"}), patch(
                "scrape.orchestrator.subprocess.run", side_effect=fake_run
            ):
                outcome = backup_db(backup_dir=tmp, verbose=False)

            self.assertEqual(outcome["status"], "success")
            backup_path = outcome["path"]
            self.assertIsNotNone(backup_path)
            remaining = sorted(p.name for p in directory.glob(f"{BACKUP_PREFIX}*.sql"))
            self.assertEqual(len(remaining), BACKUP_RETENTION)
            self.assertIn(Path(str(backup_path)).name, remaining)
            self.assertNotIn(f"{BACKUP_PREFIX}20260101_000000.sql", remaining)

    def test_failed_backup_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _make_dumps(
                directory,
                ["20260101_000000", "20260102_000000", "20260103_000000"],
            )

            def failing_run(command, **_kwargs):
                raise subprocess.CalledProcessError(1, command)

            with patch.dict(os.environ, {"DATABASE_URL": "postgresql://u:p@h:5432/db"}), patch(
                "scrape.orchestrator.subprocess.run", side_effect=failing_run
            ):
                outcome = backup_db(backup_dir=tmp, verbose=False)

            self.assertEqual(outcome["status"], "failed")
            self.assertEqual(len(list(directory.glob(f"{BACKUP_PREFIX}*.sql"))), 3)


if __name__ == "__main__":
    unittest.main()
