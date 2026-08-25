"""CLI and registry tests for Panorama Inmobiliario."""

import argparse
import io
import unittest
from unittest import mock

import scripts.scrape_panoramainmobiliario as panorama_cli
from scrape.cli import create_parser
from scrape.orchestrator import PORTALS


class TestRegistry(unittest.TestCase):
    def test_portal_is_registered(self):
        self.assertEqual(
            PORTALS["panoramainmobiliario"],
            {"module": "panoramainmobiliario"},
        )

    def test_cli_default_uses_contract_portal_name(self):
        args = create_parser("panoramainmobiliario", "test").parse_args([])
        self.assertEqual(args.portal, "panoramainmobiliario")


class TestSampleOnly(unittest.TestCase):
    def test_sample_only_does_not_write_outputs(self):
        args = argparse.Namespace(
            portal="panoramainmobiliario",
            output="both",
            ciudad="medellin",
            sample_only=True,
            max_pages=1,
            verbose=False,
        )
        with (
            mock.patch(
                "scripts.scrape_panoramainmobiliario.scrape",
                return_value=[
                    {
                        "id": "PAN-1",
                        "portal": "panoramainmobiliario",
                        "tipo": "apartamento",
                        "precio": 1000000,
                        "area": 50,
                        "habitaciones": 2,
                        "banos": 1,
                        "parqueaderos": 0,
                        "estrato": 3,
                        "barrio": "Laureles",
                        "url": "https://panoramainmobiliario.co/apartamento/1",
                    }
                ],
            ),
            mock.patch("scrape.cli.write_to_csv") as csv_mock,
            mock.patch("scrape.cli.write_to_db") as db_mock,
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            result = panorama_cli.main(args=args)

        self.assertEqual(result, 0)
        csv_mock.assert_not_called()
        db_mock.assert_not_called()
        self.assertIn("Sample: 1 listing(s) extracted", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
