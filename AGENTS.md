### ⛔ NO REGEX RULE (mandatory)

**Zero static pattern matching.** This project uses Scrapling MCP tools (`scrapling_get`, `scrapling_screenshot`, `scrapling_bulk_get`) for ALL field extraction. The agent reads the rendered text output from Scrapling and uses its own reasoning to identify and extract fields — guided by `docs/variable-detection.md`.

**Never use:**
- `re.search`, `re.match`, `re.findall`, `re.compile` for field extraction
- Hardcoded CSS selectors (`.alcobas`, `.garaje`) in Python code
- Per-portal scraper scripts
- `adaptive_extractor.py` or any regex-based extraction

**Always use:**
- `scrapling_get` to fetch pages and see their content
- `scrapling_screenshot` for visually identifying icon-only fields
- `scrapling_bulk_get` for parallel multi-page extraction
- The agent's own reasoning to map text → 11 columns per `docs/variable-detection.md`

### MCP Limitation — Button Click / Scroll Fallback

Scrapling MCP does not expose `page_action` for clicks or scrolls. For "Load More" portals, use Python API:

```python
from scrapling import StealthyFetcher
from playwright.sync_api import Page

def click_load_more(page: Page):
    last = page.locator('text=Código:').count()
    while True:
        btn = page.locator('text=Cargar más inmuebles')
        if btn.count() == 0 or not btn.first.is_visible():
            break  # button gone
        btn.first.click()
        page.wait_for_timeout(2000)
        current = page.locator('text=Código:').count()
        if current == last: break  # stopped growing — all loaded
        last = current

resp = StealthyFetcher.fetch(url, page_action=click_load_more, headless=True)
```

**Never hardcode click/scroll counts.** Stop when:
1. Button disappears OR
2. Listing count stops growing (comparing before/after each interaction)

Same pattern for scroll-based portals: compare element count before/after each scroll.

See `reference/portals/coninsa.md` and `reference/portals/arrendamientosvillacruz.md` for full examples.