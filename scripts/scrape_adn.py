#!/usr/bin/env python3
"""Scrape Arrendamientos del Norte rental listings."""
import sys
sys.path.insert(0, '.')
from scrape.cli import create_parser, run_scraper
from scrape.arrendamientosdelnorte import scrape


def main():
    parser = create_parser('arrendamientosdelnorte', 'Scrape ADN rental listings')
    args = parser.parse_args()

    def arrendamientosdelnorte():
        return scrape(ciudad=args.ciudad, sample_only=args.sample_only, max_pages=args.max_pages, verbose=args.verbose)

    run_scraper(scraper_fn=arrendamientosdelnorte, args=args)


if __name__ == '__main__':
    main()
