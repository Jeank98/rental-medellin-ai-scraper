"""Credential selection for the Google Sheets exporter.

The export used to depend only on a user OAuth token, which needs a browser to
renew. These tests pin the two additions: a service-account credential path and
a fixed OAuth callback port for headless re-authorization.
"""

import pytest

import scripts.export_to_sheets as exporter


def test_oauth_port_defaults_to_a_random_port(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_OAUTH_PORT", raising=False)

    assert exporter._oauth_port() == 0


def test_oauth_port_honours_a_fixed_port(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_PORT", "8765")

    assert exporter._oauth_port() == 8765


def test_oauth_port_rejects_a_non_numeric_value(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_PORT", "ocho")

    with pytest.raises(SystemExit):
        exporter._oauth_port()


def test_oauth_port_rejects_an_out_of_range_value(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_PORT", "70000")

    with pytest.raises(SystemExit):
        exporter._oauth_port()


def test_service_account_is_optional(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)

    assert exporter._service_account_credentials() is None


def test_missing_service_account_file_fails_loudly(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(tmp_path / "nope.json"))

    with pytest.raises(SystemExit):
        exporter._service_account_credentials()


def test_invalid_service_account_json_fails_loudly(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{not json")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)

    with pytest.raises(SystemExit):
        exporter._service_account_credentials()
