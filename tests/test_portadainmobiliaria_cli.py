"""CLI tests for the Portada Inmobiliaria thin wrapper."""

import argparse
import io
import json
from pathlib import Path
from unittest import mock

import scripts.scrape_portadainmobiliaria

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "portadainmobiliaria"


def _load_fixture(name: str) -> dict:
    """Load a Portada JSON fixture."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _args(**overrides: object) -> argparse.Namespace:
    """Build parsed CLI arguments for wrapper tests."""
    values: dict[str, object] = {
        "portal": "portadainmobiliaria",
        "output": "both",
        "ciudad": "medellin",
        "sample_only": True,
        "max_pages": 1,
        "verbose": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_sample_only_does_not_write_outputs():
    """The fixture-backed scraper runs without invoking writers."""
    with (
        mock.patch(
            "scrape.portadainmobiliaria.fetch_json",
            side_effect=[
                _load_fixture("apartamento_page1.json"),
                _load_fixture("casa_page1.json"),
                _load_fixture("apartaestudio_page1.json"),
            ],
        ),
        mock.patch("scrape.cli.write_to_csv") as write_csv,
        mock.patch("scrape.cli.write_to_db") as write_db,
        mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
    ):
        result = scripts.scrape_portadainmobiliaria.main(args=_args())

    assert result == 0
    write_csv.assert_not_called()
    write_db.assert_not_called()
    assert "Sample: 4 listing(s) extracted" in stdout.getvalue()


def test_zero_rows_keep_shared_cli_exit_contract():
    """The shared runner exits with code 2 when extraction returns no rows."""
    args = _args(sample_only=False, max_pages=None)

    with mock.patch("scrape.portadainmobiliaria.scrape", return_value=[]):
        try:
            scripts.scrape_portadainmobiliaria.main(args=args)
        except SystemExit as error:
            assert error.code == 2
        else:
            raise AssertionError("zero rows must raise SystemExit(2)")
