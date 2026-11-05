# Zitios Inmobiliaria (`ZIT`)

- **URL**: `https://zitios.com.co/inmuebles/g/arriendo/c/medell%C3%ADn/`
- **Municipalities**: `medellin` (`medell%C3%ADn`), `envigado`, `itagui`,
  `sabaneta` — verified slugs in `/c/{slug}/`. `la-estrella` returns 404 with
  both `la-estrella` and `laestrella`, so the scraper raises
  `UnsupportedCityError` until its route is found.
- **Residential search routes**: `/t/apartamentos/`, `/t/casas/`, and `/t/apartaestudios/` before `/c/{city}/`
- **Canonical search route**: `/inmuebles/g/arriendo/c/{city}/`, unioned with the residential routes to include source subtypes such as penthouse and duplex.
- **Type**: Server-rendered HTML with semantic schema.org metadata
- **Listing card**: `article` elements with `itemprop="itemListElement"`
- **Pagination**: Each route uses its base URL for page 1, then `?pagina=N`. Full runs stop each stream independently on an empty or repeated source-ID page; sample mode defaults to one page per route and `max_pages` bounds each route.
- **Key feature**: Two-phase extraction; cards omit numeric estrato and may omit garage/other numeric badges

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | Card URL suffix and visible code | `ZIT-{numeric}` from the final underscore suffix |
| `portal` | Fixed | `zitios` |
| `tipo` | Property URL slug, then heading fallback | `arriendo-apartamento-...` → `apartamento`; slug wins over mislabelled headings |
| `precio` | Card price metadata/text or detail text | `$2.000.000` → `2000000` |
| `area` | Card `title="Área construida"` or detail label | Numeric value before the square-metre unit |
| `habitaciones` | Card `title="Alcobas"` or detail label | Numeric value; absent → `0` after detail attempt |
| `banos` | Card `title="Baños"` or detail label | Numeric value; absent → `0` after detail attempt |
| `parqueaderos` | Card `title="Garajes"` or detail label | Numeric value; an omitted detail label preserves the card value, while an explicit detail zero overrides it |
| `estrato` | **Detail only when missing on card** | `Estrato: 3` → `3`; non-numeric values → `0` |
| `barrio` | Card `addressSubLocality` metadata or `/n/` link; detail fallback | Normalize the neighborhood text |
| `url` | Direct `/inmueble/` card link | Canonical absolute URL without query/fragment; stable numeric suffix retained |

**Notes**:
- **TWO-PHASE STRATEGY**: Collect and deduplicate cards across all four routes, then bulk-fetch records with missing card contract values. Estrato is absent from the cards in the verified sample, so residential records normally enter Phase B.
- **RESIDENTIAL GUARD**: The canonical route can include commercial and sale listings; the existing card-level type, rental, and commercial-use guards apply before any detail fetch.
- **PAGINATION SAFETY**: Track source IDs independently per route, including rejected commercial cards, so overlap with typed routes or a commercial-only page cannot hide later residential cards. A missing or challenged first canonical page fails the run.
- The parser applies a second residential type guard, so `local`, `oficina`, `bodega`, and other non-residential cards never reach detail fetching.
- Search results can leak `Arriendo/Venta` records. Mixed and sale-only headings are skipped.
- URL slugs are authoritative for `tipo` because some cards have a heading that disagrees with the property URL.
- A missing garage badge is not an explicit zero. Detail labels or source prose such as `No cuenta con parqueadero` must establish zero.
- The detail URL may normalize with a trailing slash after navigation; the canonical stored URL remains the card URL and preserves the numeric suffix.
