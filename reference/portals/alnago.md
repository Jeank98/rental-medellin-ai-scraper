# Alnago (`ALN`)

- **URL**: `https://alnago.com` (homepage with SSR article cards)
- **Type**: Next.js SSR — server-rendered article cards
- **Strategy**: **Two-phase** — homepage articles → detail pages
- **Key feature**: **Server-rendered `<article>` cards on homepage** — no Playwright or API needed

## Phase A — Homepage cards (via Scrapling)

Use `Fetcher.get()` → `resp.find_all('article')` to get cards. Each `<article>` contains:
```
Zona / {barrio} / Finalidad / Arriendo/Venta / Precio / $N /
Cod: / {code} / Bedrooms / N / Bathrooms / N / Garages / N /
<a href="/en/inmueble/{code}">Ver inmueble</a>
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
| `barrio` | `Zona` line | `La Milagrosa` → normalize_barrio |
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

- **Site migrated from REST API to Next.js SSR (May 2026)**: Old `/api/v1/properties` removed. New site serves listing cards as `<article>` elements on homepage (24 "Featured Properties").
- **Detail pages ARE server-rendered** — `scrapling_get` or `bulk_fetch` works without Playwright. URL: `https://alnago.com/es/inmueble/{code}`
- **Homepage shows mixed Arriendo + Venta** — cards don't distinguish; detail page title confirms with "en arriendo" vs "en venta"
- **Estrato NOT a structured field** — buried in description prose as `"estrato N"`. Many listings omit it → default 0.
- **Tipo from title**: First word before "en arriendo/en venta" → normalize_tipo (handles Spanish: Apartamento, Casa, Apartaestudio + English from homepage)
- **ID format**: `ALN-{code}` (simpler than old `ALN-{entry}-{id_property}` — codes are unique in new system)
- **Homepage limits**: Only ~24-30 featured listings on homepage. For full scrape, "Load More" button needs Playwright or search page needs JS execution.
- **Search page** (`/es/categorias/arrendar/todos/medellin`): Client-rendered via JS — shows "Cargando..." without browser execution. NOT usable with `scrapling_get`.
- **Scrapling API**: Uses `resp.find_all('article')` for card selection, `article.get_all_text()` for text extraction, `article.find_all('a')` for link extraction.

## Zero Genuineness

| Field | Default 0 | Status |
|-------|-----------|--------|
| `estrato` | 0 | ✅ Genuine — Not a structured field; some descriptions mention it, most don't |
