#!/usr/bin/env python3
"""Scrape Alberto Alvarez — hidden JSON in each listing card. Effortless."""

import re
import json
import asyncio
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapling import AsyncFetcher


PREFIX = "AAL"
PORTAL = "albertoalvarez"
CONCURRENCY = 8

ROMAN_MAP = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}

TIPOS = {
    "apartamento": "https://albertoalvarez.com/inmuebles/arrendamientos/apartamento/medellin/",
    "casa": "https://albertoalvarez.com/inmuebles/arrendamientos/casa/medellin/",
    "apartaestudio": "https://albertoalvarez.com/inmuebles/arrendamientos/apartaestudio/medellin/",
}


def extract_listings(html: str) -> list[dict]:
    """Extract listings from hidden JSON textareas in the HTML."""
    results = []

    # Find all hidden JSON blocks
    json_blocks = re.findall(
        r'<textarea[^>]*class="field-property"[^>]*>(.*?)</textarea>',
        html, re.DOTALL
    )

    for block in json_blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue

        code = data.get("code", "")
        tipo_raw = data.get("propertyType", "")
        precio = data.get("rentValue", 0)
        area = data.get("builtArea", 0)
        habitaciones = data.get("numberOfRooms", 0)
        sector = data.get("sectorName", "")

        # Nested fields
        features = data.get("householdFeatures", {})
        banos = features.get("baths", 0)
        parqueaderos = features.get("AASimpleparking", 0)

        # stratum — Roman numeral to int
        stratum_raw = data.get("stratum", "0")
        estrato = ROMAN_MAP.get(stratum_raw, 0)

        # tipo normalization
        tipo = tipo_raw.lower()
        if tipo == "casa vivienda":
            tipo = "casa"

        # URL from JSON or construct
        url = ""
        zona_raw = data.get("zoneName", "").lower().replace(" ", "-")
        sector_slug = sector.lower().replace(" ", "-")
        if code and tipo_raw and sector_slug:
            url = f"https://albertoalvarez.com/inmuebles/detalle/arrendamientos/{tipo_raw.lower()}/{code}/{sector_slug}-medellin/"

        results.append({
            "id": f"{PREFIX}-{code}" if code else "",
            "portal": PORTAL,
            "tipo": tipo,
            "precio": precio,
            "area": area,
            "habitaciones": habitaciones,
            "banos": banos,
            "parqueaderos": parqueaderos,
            "estrato": estrato,
            "barrio": sector,
            "url": url,
        })

    return results


def discover_pages(html: str, per_page: int = 9) -> int:
    """Find total pages from pagination links."""
    pages = re.findall(r'\?limit=\d+&pag=(\d+)', html)
    if pages:
        return max(int(p) for p in pages)
    return 1


async def fetch_page(fetcher, url: str) -> list[dict]:
    try:
        resp = await fetcher.get(url)
        html = resp.body.decode('utf-8', errors='replace') if isinstance(resp.body, bytes) else resp.body
        return extract_listings(html)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr, flush=True)
        return []


async def scrape_tipo(fetcher, tipo: str, base_url: str) -> list[dict]:
    print(f"\n{'='*50}")
    print(f"Scraping {tipo}...")
    print(f"  URL: {base_url}")

    # Discovery: fetch page 1
    resp = await fetcher.get(base_url)
    html = resp.body.decode('utf-8', errors='replace') if isinstance(resp.body, bytes) else resp.body
    total_pages = discover_pages(html)
    listings_p1 = extract_listings(html)
    print(f"  Page 1: {len(listings_p1)} listings | Total pages: {total_pages}")

    all_results = listings_p1

    if total_pages > 1:
        sem = asyncio.Semaphore(CONCURRENCY)

        async def bounded_fetch(page):
            async with sem:
                url = f"{base_url}?limit=9&pag={page}"
                return await fetch_page(fetcher, url)

        tasks = [bounded_fetch(p) for p in range(2, total_pages + 1)]
        page_results = await asyncio.gather(*tasks)

        for i, results in enumerate(page_results, 2):
            all_results.extend(results)
            print(f"  Page {i:2d}: {len(results)} listings")

    print(f"  Total {tipo}: {len(all_results)}")
    return all_results


async def main():
    output_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/albertoalvarez.json"

    print("Alberto Alvarez — Hidden JSON Extractor")
    print(f"Tipos to scrape: {list(TIPOS.keys())}\n")

    fetcher = AsyncFetcher(auto_match=False)
    all_listings = []

    for tipo, url in TIPOS.items():
        listings = await scrape_tipo(fetcher, tipo, url)
        all_listings.extend(listings)

    # Deduplicate
    seen = set()
    unique = []
    for r in all_listings:
        if r['id'] not in seen and r['id']:
            seen.add(r['id'])
            unique.append(r)

    print(f"\n{'='*50}")
    print(f"TOTAL: {len(all_listings)} extracted, {len(unique)} unique")

    unique.sort(key=lambda x: x['id'])

    with open(output_file, 'w') as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)

    print(f"Saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
