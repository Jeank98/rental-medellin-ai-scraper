# Alnago (`ALN`)

- **URL**: `https://alnago.com` (homepage with SSR property links)
- **Type**: Next.js SSR — server-rendered property cards
- **Strategy**: **Two-phase** — homepage cards → detail pages
- **Key feature**: **Server-rendered property links on homepage** — no Playwright or API needed

## Phase A — Homepage cards (via Scrapling)

Use `Fetcher.get()` to fetch the homepage. The current markup exposes each card as an
`<a href="/en/inmueble/{code}">` element (the legacy markup used `<article>`). Each
current link contains:
```
Rent / $N/mo / Code {code} /
{tipo} en arriendo en {zona} / {barrio}, {ciudad} / N / N / N / N m²
```

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `ALN-{code}` | `Cod:` in article text or URL path |
| `portal` | `alnago` | Fixed |
| `tipo` | **Phase B** — detail page title | First word before "en arriendo" |
| `precio` | `Precio` line | `$1.700.000` → normalize_price |
| `area` | **Phase B** — detail page "Área privada" | `110 M2` → int |
| `habitaciones` | `Bedrooms` line | `3` → int |
| `banos` | `Bathrooms` line | `2` → int |
| `parqueaderos` | `Garages` line | `0` → int |
| `estrato` | **Phase B** — detail description prose | `"estrato 3"` → int (absent → 0) |
| `barrio` | Location line before the city | `El Carmelo, Bello` → `El Carmelo` |
| `url` | `https://alnago.com/es/inmueble/{code}` | Constructed |

## Phase B — Detail pages (server-rendered, `/es/inmueble/{code}`)

Fetch with `scrape/fetcher.py` `bulk_fetch()`. Extract from HTML text:

| Column | Source | Pattern |
|--------|--------|---------|
| `tipo` | Title line | `"Casa en arriendo en La Milagrosa"` → first word → normalize_tipo |
| `area` | `Área privada` or `Área terreno` | `110 M2` → digits before space/M |
| `estrato` | Description prose | `"estrato 3"` → int (regex for first contiguous digits) |

**Detail page field locations (text labels):**
- `Código del inmueble\n{code}`
- `Alcobas\n{N}` (cross-check with card)
- `Baños\n{N}` (cross-check with card)
- `Área privada\n{N} M2` or `Área terreno\n{N} M2`
- `Garaje\n{N}` (cross-check)
- `Arriendo: $N` or `Venta: $N`

## Notes

- **Site migrated from REST API to Next.js SSR (May 2026)**: Old `/api/v1/properties` removed. The current homepage serves six featured property links; the scraper supports both the current link cards and the legacy `<article>` cards.
- **Detail pages ARE server-rendered** — `scrapling_get` or `bulk_fetch` works without Playwright. URL: `https://alnago.com/es/inmueble/{code}`
- **Homepage shows mixed Arriendo + Venta** — cards don't distinguish; detail page title confirms with "en arriendo" vs "en venta"
- **Estrato NOT a structured field** — buried in description prose as `"estrato N"`. Many listings omit it → default 0.
- **Tipo from title**: First word before "en arriendo/en venta" → normalize_tipo (handles Spanish: Apartamento, Casa, Apartaestudio + English from homepage)
- **ID format**: `ALN-{code}` (simpler than old `ALN-{entry}-{id_property}` — codes are unique in new system)
- **Homepage limits**: Only six featured listings are currently server-rendered. For a full scrape, the "View all" search page needs JS execution.
- **Search page** (`/es/categorias/arrendar/todos/medellin`): Client-rendered via JS — shows "Cargando..." without browser execution. NOT usable with `scrapling_get`.
- **Scrapling API**: Uses `resp.find_all('a')` with `/inmueble/` links for current card selection, `get_all_text()` for text extraction, and retains the legacy `<article>` fallback.

## Zero Genuineness

| Field | Default 0 | Status |
|-------|-----------|--------|
| `estrato` | 0 | ✅ Genuine — Not a structured field; some descriptions mention it, most don't |

## Recent fixes

- **Tipo extraction skips noise words ("en", "arriendo", "venta", …)**: Some detail titles start with "En arriendo, Casa en La Milagrosa" — the old first-word strategy returned `tipo='en'`. The extractor now walks the words of the trigger line and skips a noise set (`en, arriendo, venta, for, rent, in, sale, y, de, el, la, los, las, un, una, the, a, an, del`) until it finds the first real tipo word, then normalizes it.
- **Garaje (parqueaderos) extracted from detail page**: Phase B now reads the `Garaje` / `Parqueadero` / `Parqueaderos` label on the detail page (line-based: label on one line, value on the next; inline fallback `Garaje: N`). The extractor returns `parqueaderos=None` when the label is absent so the orchestrator preserves the Phase A homepage value instead of overwriting it with `0`.
- **Current homepage markup restored**: The homepage no longer emits `<article>` cards. Phase A now reads the property links and their displayed price, type, location, bedrooms, bathrooms, parking, and area values.
- **Structured plural parking labels**: Detail pages use `Garajes` and also mention a bare `Garaje` in feature lists. Only a label followed by a numeric or recognized parking value is accepted, preventing feature text from overwriting the card value.
