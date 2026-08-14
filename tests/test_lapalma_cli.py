"""CLI and registry tests for La Palma."""

import argparse
import io
import unittest
from pathlib import Path
from unittest import mock

import scripts.scrape_lapalma
from scrape.cli import create_parser
from scrape.orchestrator import PORTALS

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lapalma"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestRegistry(unittest.TestCase):
    """The portal is available to the shared orchestrator."""

    def test_lapalma_registration(self):
        self.assertEqual(
            PORTALS["lapalmainmobiliaria"],
            {"module": "lapalma", "script": "lapalma"},
        )

    def test_cli_default_uses_contract_portal_name(self):
        args = create_parser("lapalmainmobiliaria", "test").parse_args([])
        self.assertEqual(args.portal, "lapalmainmobiliaria")


class TestSampleOnly(unittest.TestCase):
    """Sample mode validates rows without writing output files."""

    def test_sample_only_does_not_write(self):
        args = argparse.Namespace(
            portal="lapalmainmobiliaria",
            output="both",
            ciudad="medellin",
            sample_only=True,
            max_pages=1,
            verbose=False,
        )

        with (
            mock.patch(
                "scrape.lapalma.fetch_page", return_value=_load("search_page.html")
            ),
            mock.patch("scrape.lapalma.bulk_fetch", return_value=[]),
            mock.patch("scrape.cli.write_to_csv") as csv_mock,
            mock.patch("scrape.cli.write_to_db") as db_mock,
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            scripts.scrape_lapalma.main(args=args)

        csv_mock.assert_not_called()
        db_mock.assert_not_called()
        self.assertIn("Sample: 2 listing(s) extracted", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
