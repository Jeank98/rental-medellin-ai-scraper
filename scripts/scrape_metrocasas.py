#!/usr/bin/env python3
"""Metrocasas — Docker Chrome + Scrapling Selectors + adaptive_extractor. Zero portal-specific regex."""

import re, json, subprocess, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.adaptive_extractor import extract_card
from scrapling import Selector

PREFIX, PORTAL = "MTC", "metrocasas"
BASE_URL = "https://metrocasas.co/new/property-search"
QUERY = ("?status=para-alquiler&type[]=apartaestudio&type[]=apartamento"
         "&type[]=casa&location[]=bello&location[]=medellin&location[]=envigado"
         "&location[]=sabaneta&location[]=itagui&location[]=rionegro"
         "&location[]=la-estrella&location[]=la-ceja&location[]=girardota"
         "&location[]=marinilla&location[]=pereira&location[]=san-jeronimo"
         "&location[]=el-santuario&location[]=salgar-ant&location[]=san-cristobal")
TOTAL_PAGES = 12


def fetch_page_docker(page: int) -> str:
    url = f"{BASE_URL}/{'page/' + str(page) + '/' if page > 1 else ''}{QUERY}"
    out = f"/tmp/mtc_page_{page}.html"
    subprocess.run(["docker", "run", "--rm", "-v", "/tmp:/output",
        "pyd4vinci/scrapling", "extract", "fetch", url, f"/output/mtc_page_{page}.html"],
        capture_output=True, timeout=60)
    with open(out) as f:
        return f.read()


def extract_page(html: str) -> list[dict]:
    card_boundaries = [m.start() for m in re.finditer(r'data-property-id="(\d+)"', html)]
    card_ids = re.findall(r'data-property-id="(\d+)"', html)
    if not card_boundaries:
        return []
    results = []
    for i, (start, pid) in enumerate(zip(card_boundaries, card_ids)):
        card_start = max(0, start - 500)
        card_end = card_boundaries[i + 1] if i + 1 < len(card_boundaries) else start + 3000
        try:
            card = Selector(content=html[card_start:card_end])
            result = extract_card(card, PORTAL, PREFIX)
            result["id"] = f"{PREFIX}-{pid}"
            results.append(result)
        except Exception:
            continue
    return results


if __name__ == "__main__":
    all_listings = []
    print(f"Metrocasas — Docker Chrome + adaptive_extractor — {TOTAL_PAGES} pages")
    for page in range(1, TOTAL_PAGES + 1):
        html = fetch_page_docker(page)
        listings = extract_page(html)
        all_listings.extend(listings)
        print(f"  Page {page:2d}: {len(listings)} listings")
    seen, unique = set(), []
    for r in all_listings:
        if r['id'] not in seen: seen.add(r['id']); unique.append(r)
    print(f"\nTotal: {len(unique)} unique")
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/metrocasas_refactored.json"
    with open(out, 'w') as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out}")
