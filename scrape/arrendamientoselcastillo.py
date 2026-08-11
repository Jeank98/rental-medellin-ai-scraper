"""Arrendamientos El Castillo (AEC) two-phase Livewire scraper."""

import logging
from typing import Final

from playwright.sync_api import Page

from scrape.arrendamientoselcastillo_parser import (
    Listing,
    parse_detail_estrato,
    parse_search_html,
    scroll_to_load_all,
)
from scrape.fetcher import bulk_fetch, stealthy_fetch_with_action
from scrape.validator import validate

logger = logging.getLogger(__name__)

_SEARCH_URLS: Final = (
    "https://www.arrendamientoselcastillo.com.co/resultados?gestion=Arriendo&tipo=Apartamentos",
    "https://www.arrendamientoselcastillo.com.co/resultados?gestion=Arriendo&tipo=Casas",
    "https://www.arrendamientoselcastillo.com.co/resultados?gestion=Arriendo&tipo=Apartaestudios",
)
_RESIDENTIAL_TYPES: Final = frozenset({"apartamento", "casa", "apartaestudio"})


def scrape(
    ciudad: str = "medellin",
    sample_only: bool = False,
    max_pages: int | None = None,
    verbose: bool = False,
) -> list[Listing]:
    """Scrape El Castillo's rental inventory with card and detail phases."""
    _ = ciudad
    batch_limit = max_pages
    if sample_only and batch_limit is None:
        batch_limit = 1

    def page_action(page: Page) -> None:
        scroll_to_load_all(page, batch_limit)

    by_id: dict[str, Listing] = {}
    for search_url in _SEARCH_URLS:
        rendered = stealthy_fetch_with_action(search_url, page_action)
        if not rendered:
            logger.warning("AEC: search page returned no rendered HTML: %s", search_url)
            continue
        for listing in parse_search_html(rendered):
            by_id.setdefault(listing["id"], listing)

    # Keep the guard after normalization so commercial source cards never reach detail fetches.
    listings = [
        listing for listing in by_id.values() if listing["tipo"] in _RESIDENTIAL_TYPES
    ]
    if sample_only:
        samples = []
        for property_type in ("apartamento", "casa", "apartaestudio"):
            for listing in listings:
                if listing["tipo"] == property_type:
                    samples.append(listing)
                    break
        listings = samples[:3]

    detail_urls = list(dict.fromkeys(row["url"] for row in listings if row["url"]))
    details = {url: html for url, html in bulk_fetch(detail_urls) if html}
    for listing in listings:
        detail_html = details.get(listing["url"])
        if detail_html is not None:
            listing["estrato"] = parse_detail_estrato(detail_html)
        warnings = validate(dict(listing))
        if verbose:
            for warning in warnings:
                print(f"  [ANOMALY] {listing['id']} — {warning}")

    if verbose:
        logger.info("AEC: %d listing(s) extracted", len(listings))
    return listings


__all__ = [
    "Listing",
    "parse_detail_estrato",
    "parse_search_html",
    "scrape",
    "scroll_to_load_all",
]
