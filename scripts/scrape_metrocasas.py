#!/usr/bin/env python3
"""Metrocasas scraper — Docker Scrapling Chromium for JS rendering + Scrapling extraction."""
import re, json, subprocess, sys, os, tempfile, unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapling import Fetcher

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
    """Fetch one page with Docker scrapling Chromium, return text."""
    url = f"{BASE_URL}/{'page/' + str(page) + '/' if page > 1 else ''}{QUERY}"
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        subprocess.run([
            "docker", "run", "--rm",
            "-v", f"{os.path.dirname(tmp_path)}:/output",
            "pyd4vinci/scrapling", "extract", "fetch",
            url, f"/output/{os.path.basename(tmp_path)}"
        ], capture_output=True, timeout=60)
        with open(tmp_path) as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


def extract_page(html: str, page: int) -> list[dict]:
    """Extract listings from rendered text using title patterns."""
    results = []
    
    # Find all listing titles in rendered text
    title_re = re.compile(
        r'(Apartaestudio|Apartamento|Casa|Oficina|Local|Bodega|Finca|Lote)\s+en\s+([^\n]+)',
        re.MULTILINE
    )
    
    # Also get data-attrs from scrapling_get for reliable titles/URLs
    # We need to fetch the same page with scrapling_get
    url = f"{BASE_URL}/{'page/' + str(page) + '/' if page > 1 else ''}{QUERY}"
    from scrapling import Fetcher
    f = Fetcher(auto_match=False)
    resp = f.get(url)
    shtml = resp.body.decode('utf-8', errors='replace')
    
    props = re.findall(
        r'data-property-id="(\d+)"[^>]*data-property-title="([^"]*)"[^>]*data-property-url="([^"]*)"',
        shtml
    )
    
    for pid, title, prop_url in props:
        m = re.match(r'(Apartaestudio|Apartamento|Casa|Oficina|Local|Bodega|Finca|Lote)\s+en\s+(.+)', title, re.IGNORECASE)
        if not m: continue
        tipo = m.group(1).lower()
        tipo_map = {"apartamento":"apartamento","apartaestudio":"apartaestudio","casa":"casa","oficina":"oficina","local":"local","bodega":"bodega","finca":"finca","lote":"lote"}
        tipo = tipo_map.get(tipo, tipo)
        barrio = m.group(2).strip()
        
        # Find this title in rendered text (accent-insensitive) and extract fields
        def strip_accents(s):
            return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
        
        idx = html.find(title)
        if idx < 0:
            idx = strip_accents(html).find(strip_accents(title))
        chunk = html[idx:idx+600] if idx >= 0 else ""
        
        # If still not found in rendered text, try using scrapling get_all_text
        if idx < 0:
            text = resp.get_all_text()
            idx = text.find(title)
            if idx < 0:
                idx = strip_accents(text).find(strip_accents(title))
            chunk = text[idx:idx+600] if idx >= 0 else ""
        
        hab_m = re.search(r'Habitaciones?\s*\n?\s*(\d+)', chunk)
        ban_m = re.search(r'Cuartos\s+de\s+baño\s*\n?\s*(\d+)', chunk)
        area_m = re.search(r'Área\s*\n?\s*(\d+)\s*(?:m\s*2|m2)', chunk)
        price_m = re.search(r'\$([\d,]+)', chunk)
        
        results.append({
            "id": f"{PREFIX}-{pid}",
            "portal": PORTAL, "tipo": tipo,
            "precio": int(price_m.group(1).replace(',','')) if price_m else 0,
            "area": int(area_m.group(1)) if area_m else 0,
            "habitaciones": int(hab_m.group(1)) if hab_m else 0,
            "banos": int(ban_m.group(1)) if ban_m else 0,
            "parqueaderos": 0, "estrato": 0,
            "barrio": barrio, "url": prop_url,
        })
    return results


if __name__ == "__main__":
    output_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/metrocasas_final.json"
    all_listings = []
    
    print(f"Metrocasas — Docker Scrapling Chromium — {TOTAL_PAGES} pages")
    for page in range(1, TOTAL_PAGES + 1):
        text = fetch_page_docker(page)
        listings = extract_page(text, page)
        all_listings.extend(listings)
        print(f"  Page {page:2d}: {len(listings)} listings")
    
    seen, unique = set(), []
    for r in all_listings:
        if r['id'] not in seen:
            seen.add(r['id']); unique.append(r)
    
    print(f"\nTotal: {len(unique)} unique")
    with open(output_file, 'w') as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    print(f"Saved: {output_file}")
