"""A completed crawl with no inventory must not stop or fail the run."""

import argparse
from unittest import mock

import scrape.cli as cli


def _args(allow_empty: bool) -> argparse.Namespace:
    return argparse.Namespace(
        portal="demo",
        output="db",
        ciudad="medellin",
        sample_only=False,
        max_pages=None,
        verbose=False,
        allow_empty=allow_empty,
    )


def test_empty_with_allow_empty_exits_zero_and_writes_nothing(capsys) -> None:
    with mock.patch.object(cli, "write_to_db") as write:
        code = cli.run_scraper(lambda: [], args=_args(True))

    assert code == 0
    write.assert_not_called()
    assert '"status": "empty"' in capsys.readouterr().out


def test_empty_without_allow_empty_still_fails() -> None:
    try:
        cli.run_scraper(lambda: [], args=_args(False))
    except SystemExit as exit_signal:
        assert exit_signal.code == 2
    else:  # pragma: no cover - the guard must raise
        raise AssertionError("empty result without --allow-empty must fail")
