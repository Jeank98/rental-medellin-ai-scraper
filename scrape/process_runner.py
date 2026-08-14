"""Retryable subprocess execution for the scraper orchestrator."""

from dataclasses import dataclass
import subprocess
import time
from collections.abc import Sequence


@dataclass(frozen=True)
class CommandResult:
    """Result of a command after its retry policy has been exhausted."""

    returncode: int
    stdout: str
    stderr: str
    attempts: int
    elapsed: float
    error: str | None


def _as_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def run_with_retries(
    command: Sequence[str],
    timeout: int,
    max_attempts: int = 2,
    retry_delay: float = 5.0,
) -> CommandResult:
    """Run a command and retry technical failures without changing its input."""
    started = time.monotonic()
    attempts = max(1, max_attempts)
    last_stdout = ""
    last_stderr = ""
    last_error: str | None = None
    last_returncode = 1

    for attempt in range(1, attempts + 1):
        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            last_returncode = completed.returncode
            last_stdout = _as_text(completed.stdout)
            last_stderr = _as_text(completed.stderr)
            last_error = None
            if completed.returncode == 0:
                return CommandResult(
                    completed.returncode,
                    last_stdout,
                    last_stderr,
                    attempt,
                    time.monotonic() - started,
                    None,
                )
        except subprocess.TimeoutExpired as error:
            last_returncode = 124
            last_stdout = _as_text(error.stdout)
            last_stderr = _as_text(error.stderr)
            last_error = "timeout"
        except OSError as error:
            last_returncode = 127
            last_error = str(error)

        if attempt < attempts:
            time.sleep(retry_delay)

    error = last_error or last_stderr[:200].strip() or f"exit code {last_returncode}"
    return CommandResult(
        last_returncode,
        last_stdout,
        last_stderr,
        attempts,
        time.monotonic() - started,
        error,
    )
