#!/usr/bin/env python3
"""Scrape Coninsa rental listings (Load More portal)."""
import sys; sys.path.insert(0, '.')
from scrape.cli import create_parser, run_scraper
from scrape.coninsa import scrape


def main():
    parser = create_parser('coninsa', 'Scrape Coninsa rental listings')
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
