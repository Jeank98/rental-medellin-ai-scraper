#!/usr/bin/env python3
"""Scrape Habitamos rental listings."""
import sys; sys.path.insert(0, '.')
from scrape.cli import create_parser, run_scraper
from scrape.habitamos import scrape


def main():
    parser = create_parser('habitamos', 'Scrape Habitamos rental listings')
    args = parser.parse_args()
    run_scraper(
        scraper_fn=lambda: scrape(
            ciudad=args.ciudad,
            sample_only=args.sample_only,
            max_pages=args.max_pages,
            verbose=args.verbose,
        ),
        args=args,
    )


if __name__ == '__main__':
    main()
