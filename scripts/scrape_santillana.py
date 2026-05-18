#!/usr/bin/env python3
"""Santillana two-phase scraper — ALL Scrapling, no raw regex extraction."""
import re, json, asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapling import AsyncFetcher
from scripts.adaptive_extractor import extract_card as adaptive_extract

PREFIX, PORTAL = "STL", "santillana"
BASE = "https://santillanasas.com/search"
Q = ("?simple=1-2-496&business_type%5B0%5D=for_rent&id_country=1&id_region=2"
     "&id_city=496&order_by=created_at&order=desc"
     "&for_sale=0&for_rent=1&for_temporary_rent=0&for_transfer=0&lax_business_type=1")
CONCURRENCY = 8


async def fetch_page(fetcher, url):
    resp = await fetcher.get(url)
    return resp


async def main():
    output_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/santillana_final.json"
    fetcher = AsyncFetcher(auto_match=False)
    all_cards = []

    # Phase A: cards with Scrapling
    print("Phase A: Listing cards")
    for page in range(1, 7):
        resp = await fetch_page(fetcher, f"{BASE}{Q}&page={page}")
        cards = resp.find_all("div.item")
        page_results = []
        for c in cards:
            link = c.find("a.t8-ellipsis") or c.find("a")
            url = link.attrib.get("href", "") if link else ""
            code_m = re.search(r'/(\d+)', url)
            code = code_m.group(1) if code_m else ""
            text = c.get_all_text()
            # Use adaptive extractor for tipo and precio — no portal-specific regex
            extracted = adaptive_extract(c, PORTAL, PREFIX)
            page_results.append({"id": f"{PREFIX}-{code}" if code else "", "portal": PORTAL,
                "tipo": extracted["tipo"], "precio": extracted["precio"], "area": 0, "habitaciones": 0, "banos": 0,
                "parqueaderos": 0, "estrato": 0, "barrio": "", "url": url})
        all_cards.extend(page_results)
        print(f"  Page {page}: {len(page_results)}")
    print(f"  Total cards: {len(all_cards)}")

    # Phase B: detail pages with Scrapling selectors
    print(f"\nPhase B: {len(all_cards)} detail pages")
    sem = asyncio.Semaphore(CONCURRENCY)

    async def get_detail(url):
        async with sem:
            try:
                resp = await fetch_page(fetcher, url)
                items = resp.find_all("ul.list-li li")
                fields = {}
                for li in items:
                    strong = li.find("strong")
                    if not strong:
                        continue
                    label = strong.text.strip().lower()
                    value = li.get_all_text().replace(strong.text, '', 1).strip()

                    if 'área' in label or 'area' in label:
                        m = re.search(r'(\d+)', value)
                        if m: fields['area'] = int(m.group(1))
                    elif 'alcoba' in label:
                        m = re.search(r'(\d+)', value)
                        if m: fields['habitaciones'] = int(m.group(1))
                    elif 'baño' in label:
                        m = re.search(r'(\d+)', value)
                        if m: fields['banos'] = int(m.group(1))
                    elif 'garaje' in label:
                        m = re.search(r'(\d+)', value)
                        if m: fields['parqueaderos'] = int(m.group(1))
                    elif 'estrato' in label:
                        m = re.search(r'(\d+)', value)
                        if m: fields['estrato'] = int(m.group(1))
                    elif 'barrio' in label or 'zona' in label:
                        fields['barrio'] = value
                return fields
            except:
                return {}

    details = await asyncio.gather(*[get_detail(c['url']) for c in all_cards])
    for card, d in zip(all_cards, details):
        for k, v in d.items():
            if v: card[k] = v

    seen, unique = set(), []
    for c in all_cards:
        if c['id'] and c['id'] not in seen:
            seen.add(c['id']); unique.append(c)
    unique.sort(key=lambda x: x['id'])
    print(f"  Unique: {len(unique)}")

    with open(output_file, 'w') as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    print(f"Saved: {output_file}")

if __name__ == "__main__":
    asyncio.run(main())
