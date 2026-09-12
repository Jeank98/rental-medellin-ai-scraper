"""Regression tests for shared HTTP fetch behavior."""

from types import SimpleNamespace
from unittest import mock

from scrape.fetcher import fetch_page


def test_fetch_page_retries_rate_limits() -> None:
    fetcher = mock.Mock()
    fetcher.get.side_effect = [
        SimpleNamespace(status=429, html_content=""),
        SimpleNamespace(status=200, html_content="<html>recovered</html>"),
    ]

    with (
        mock.patch("scrape.fetcher._get_fetcher", return_value=fetcher),
        mock.patch("scrape.fetcher.time.sleep") as sleep,
    ):
        assert fetch_page("https://example.test/detail") == "<html>recovered</html>"

    assert fetcher.get.call_count == 2
    sleep.assert_called_once_with(1)
