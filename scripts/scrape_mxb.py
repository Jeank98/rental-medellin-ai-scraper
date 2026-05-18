#!/usr/bin/env python3
"""Scrape all Maxibienes rental listings using Scrapling.

Usage:
    uv run python scripts/scrape_mxb.py <base_url> [output_json]

Example:
    uv run python scripts/scrape_mxb.py \\
        "https://www.maxibienes.com/resultados-de-la-busqueda-de-inmueble/?gestion=1&ciudad=5001" \\
        /tmp/mxb_listings.json
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
    """From page 1 HTML, extract (total_listings, listings_per_page)."""
    # Try JS variables: var totalInmuebles = 870; var totalpagina = 12;
    total_m = re.search(r"var totalInmuebles\s*=\s*(\d+)\s*;", html)
    per_page_m = re.search(r"var totalpagina\s*=\s*(\d+)\s*;", html)
    if total_m and per_page_m:
        total = int(total_m.group(1))
        per_page = int(per_page_m.group(1))
        return total, per_page

    # Fallback: extract last page from pagination onclick="paginador(3, 73)"
    last_page_m = re.search(r'onclick="paginador\(3,\s*(\d+)\)">Ultima', html)
    if last_page_m:
        # Count cards on page to get per_page
        per_page = len(re.findall(r'class="item col-sm-4"', html))
        if per_page == 0:
            per_page = 12  # default
        total = int(last_page_m.group(1)) * per_page
        return total, per_page

    return 0, 0


async def fetch_page(fetcher: AsyncFetcher, page: int, base_url: str) -> list[dict]:
    # Maxibienes pagination pattern: /pagina/N?query
    url = base_url.replace("resultados-de-la-busqueda-de-inmueble/?", f"resultados-de-la-busqueda-de-inmueble/pagina/{page}?")
    try:
        resp = await asyncio.wait_for(fetcher.get(url), timeout=30)
        cards = resp.find_all(".grid-style1 .item")
        results = []
        for card in cards:
            extracted = extract_card(card, "maxibienes", "MXB")
            if extracted:
                results.append(extracted)
        print(f"  Page {page:3d}: {len(results)} listings", flush=True)
        return results
    except Exception as e:
        print(f"  Page {page:3d}: ERROR — {e}", file=sys.stderr, flush=True)
        return []


async def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <base_url> [output_json]")
        print("Example: uv run python scripts/scrape_mxb.py 'https://www.maxibienes.com/resultados-de-la-busqueda-de-inmueble/?gestion=1&ciudad=5001'")
        sys.exit(1)

    base_url = sys.argv[1].rstrip("/")
    output_file = sys.argv[2] if len(sys.argv) > 2 else "/tmp/mxb_listings.json"

    # Phase 1: Discovery — fetch page 1
    print("Phase 1: Discovering pagination from page 1...")
    fetcher = AsyncFetcher(auto_match=False)

    # Use sync get for discovery (simpler)
    from scrapling import Fetcher
    sf = Fetcher(auto_match=False)
    resp = sf.get(base_url)
    html = resp.body.decode("utf-8", errors="replace") if isinstance(resp.body, bytes) else resp.body

    total_listings, per_page = discover_pagination(html)
    if total_listings == 0:
        print("ERROR: Could not discover pagination. Check the URL.")
        sys.exit(1)

    total_pages = math.ceil(total_listings / per_page)
    print(f"  Total listings: {total_listings}")
    print(f"  Per page: {per_page}")
    print(f"  Total pages: {total_pages}")

    # Phase 2: Bulk scrape
    print(f"\nPhase 2: Scraping {total_pages} pages (concurrency: {CONCURRENCY})...")
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
