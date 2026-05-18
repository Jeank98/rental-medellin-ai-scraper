#!/usr/bin/env python3
"""Scrape all Arrendamientos SantaFe rental listings using Scrapling.

Usage:
    uv run python scripts/scrape_asf.py <base_url> [output_json]
"""

import asyncio
import math
import re
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapling import AsyncFetcher
from scripts.adaptive_extractor import extract_card

CONCURRENCY = 8


def discover_pagination(html: str) -> tuple[int, int]:
    """From page 1 HTML, discover (total_listings, listings_per_page).

    Strategy: fetch page 1 for per_page count, then try page=999 to discover
    the last valid page by looking for listing codes — when codes stop changing,
    we've gone past the end.
    """
    per_page = len(re.findall(r'property-card', html))
    if per_page == 0:
        per_page = 12
    # We'll let the caller handle total by probing — return what we have
    return 0, per_page


async def fetch_page(fetcher: AsyncFetcher, page: int, base_url: str) -> list[dict]:
    url = f"{base_url.rstrip('&')}&page={page}"
    try:
        resp = await asyncio.wait_for(fetcher.get(url), timeout=30)
        cards = resp.find_all(".property-card")
        results = []
        for card in cards:
            extracted = extract_card(card, "arrendamientossantafe", "ASF")
            if extracted:
                results.append(extracted)
        print(f"  Page {page:3d}: {len(results)} listings", flush=True)
        return results
    except Exception as e:
        print(f"  Page {page:3d}: ERROR — {e}", file=sys.stderr, flush=True)
        return []


def find_last_valid_page(base_url: str) -> int:
    """Binary search to find the last page with unique listings.

    Pages beyond the end show a single stale listing with the same code.
    """
    from scrapling import Fetcher
    f = Fetcher(auto_match=False)

    def is_valid(page):
        resp = f.get(f"{base_url.rstrip('&')}&page={page}")
        cards = resp.find_all(".property-card")
        if len(cards) == 0:
            return False
        # If we get exactly 1 card, it might be the stale card
        if len(cards) == 1:
            # Check if this card appears on previous page too
            code_el = cards[0].find(".id")
            if code_el:
                code = code_el.text.strip()
                # Try page-1 to see if it has the same code
                resp_prev = f.get(f"{base_url.rstrip('&')}&page={page-1}")
                cards_prev = resp_prev.find_all(".property-card")
                if cards_prev:
                    last_prev = cards_prev[-1].find(".id")
                    if last_prev and last_prev.text.strip() == code:
                        return False
                else:
                    return False
            else:
                return False
        return True

    # Find upper bound
    low, high = 1, 1
    while is_valid(high):
        high *= 2
        if high > 1000:
            break

    # Binary search
    while low < high:
        mid = (low + high + 1) // 2
        if is_valid(mid):
            low = mid
        else:
            high = mid - 1

    return low


async def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <base_url> [output_json]")
        print("Example: uv run python scripts/scrape_asf.py 'https://arrendamientossantafe.com/propiedades/?bussines_type=Arrendar'")
        sys.exit(1)

    base_url = sys.argv[1].rstrip("/")
    output_file = sys.argv[2] if len(sys.argv) > 2 else "/tmp/asf_listings.json"

    # Phase 1: Discovery
    print("Phase 1: Discovering pagination...")
    sf = AsyncFetcher(auto_match=False)

    from scrapling import Fetcher
    sync_f = Fetcher(auto_match=False)
    resp = sync_f.get(base_url)
    html = resp.body.decode("utf-8", errors="replace") if isinstance(resp.body, bytes) else resp.body

    _, per_page = discover_pagination(html)
    total_pages = find_last_valid_page(base_url)

    # Verify: count cards on last page
    last_resp = sync_f.get(f"{base_url.rstrip('&')}&page={total_pages}")
    last_cards = last_resp.find_all(".property-card")
    cards_last = len(last_cards)

    total_approx = (total_pages - 1) * per_page + cards_last

    print(f"  Per page: {per_page}")
    print(f"  Total pages: {total_pages}")
    print(f"  Cards on last page: {cards_last}")
    print(f"  Estimated total: ~{total_approx} listings")

    # Phase 2: Bulk scrape
    print(f"\nPhase 2: Scraping {total_pages} pages (concurrency: {CONCURRENCY})...")
    fetcher = AsyncFetcher(auto_match=False)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def bounded_fetch(page):
        async with sem:
            return await fetch_page(fetcher, page, base_url)

    tasks = [bounded_fetch(p) for p in range(1, total_pages + 1)]
    all_results = await asyncio.gather(*tasks)

    listings = []
    for page_results in all_results:
        listings.extend(page_results)

    listings.sort(key=lambda x: x["id"])

    # Deduplicate
    seen = set()
    unique = []
    dupes = 0
    for l in listings:
        if l["id"] in seen:
            dupes += 1
        else:
            seen.add(l["id"])
            unique.append(l)

    print(f"\nTotal extracted: {len(listings)}")
    if dupes:
        print(f"Duplicates removed: {dupes}")
    print(f"Unique listings: {len(unique)}")

    with open(output_file, "w") as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)

    print(f"Saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
