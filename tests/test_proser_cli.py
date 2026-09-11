"""CLI wrapper tests for Proser."""

import argparse
import io
import unittest
from unittest import mock

import scripts.scrape_proserinmobiliaria as proser_cli
from tests.test_proser import _load


class TestSampleOnlyNoWrite(unittest.TestCase):
    """The shared CLI must not write outputs in sample-only mode."""

    def test_sample_only_uses_real_scraper_without_writers(self):
        args = argparse.Namespace(
            portal="proserinmobiliaria",
            output="both",
            ciudad="medellin",
            sample_only=True,
            max_pages=1,
            verbose=False,
        )
        search = _load("search_page_1.html")
        detail = _load("detail_10163884.html")
        detail_sale = detail.replace("10163884", "10205313").replace("San Joaquín", "Poblado")
        with mock.patch("scrape.proserinmobiliaria.fetch_page", return_value=search), mock.patch(
            "scrape.proserinmobiliaria.bulk_fetch",
            return_value=[(
                "https://proserinmobiliaria.com/apartamento-venta-poblado-medellin/10205313",
                detail_sale,
            ), (
                "https://proserinmobiliaria.com/apartamento-alquiler-san-joaquin-medellin/10163884",
                detail,
            )],
        ), mock.patch("scrape.cli.write_to_csv") as csv, mock.patch(
            "scrape.cli.write_to_db"
        ) as db, mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = proser_cli.main(args=args)

        self.assertEqual(result, 0)
        csv.assert_not_called()
        db.assert_not_called()
        self.assertIn("Sample: 2 listing(s) extracted", stdout.getvalue())



class TestReuseFlag(unittest.TestCase):
    def test_forwards_reuse_flag(self):
        args = argparse.Namespace(
            portal="proserinmobiliaria",
            output="both",
            ciudad="medellin",
            sample_only=True,
            max_pages=1,
            verbose=False,
            reuse_unchanged_details=True,
        )
        with (
            mock.patch(
                "scripts.scrape_proserinmobiliaria.scrape",
                return_value=[],
            ) as scrape_mock,
            mock.patch(
                "scripts.scrape_proserinmobiliaria.run_scraper",
                side_effect=lambda scraper_fn, **_kwargs: (scraper_fn(), 0)[1],
            ),
        ):
            result = proser_cli.main(args=args)

        self.assertEqual(result, 0)
        scrape_mock.assert_called_once_with(
            ciudad="medellin",
            sample_only=True,
            max_pages=1,
            verbose=False,
            reuse_unchanged_details=True,
        )

if __name__ == "__main__":
    unittest.main()
