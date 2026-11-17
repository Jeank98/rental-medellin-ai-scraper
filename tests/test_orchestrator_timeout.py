"""A stalled portal must not hold a worker for an hour."""

from scrape.orchestrator import PORTAL_TIMEOUT_SECONDS


def test_portal_timeout_is_bounded() -> None:
    assert 0 < PORTAL_TIMEOUT_SECONDS <= 1800
