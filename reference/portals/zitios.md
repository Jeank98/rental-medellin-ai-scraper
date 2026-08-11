# Zitios Inmobiliaria (`ZIT`)

- **URL**: `https://zitios.com.co/inmuebles/g/arriendo/c/medell%C3%ADn/`
- **Type**: Server-rendered HTML with semantic schema.org metadata
- **Listing card**: `article` elements with `itemprop="itemListElement"`
- **Listings per page**: 30 on pages 1-3; 4 on page 4 in the verified sample
- **Total pages**: Four numbered pages; the assessment observed 94 listings (the live count is volatile)
- **Pagination**: Base route for page 1, then `?pagina=2`, `?pagina=3`, `?pagina=4`
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
| `parqueaderos` | Card `title="Garajes"` or detail label | Numeric value; omitted card badge is not treated as proof until detail/source text is checked |
| `estrato` | **Detail only when missing on card** | `Estrato: 3` → `3`; non-numeric values → `0` |
| `barrio` | Card `addressSubLocality` metadata or `/n/` link; detail fallback | Normalize the neighborhood text |
| `url` | Direct `/inmueble/` card link | Canonical absolute URL without query/fragment; stable numeric suffix retained |

**Notes**:
- **TWO-PHASE STRATEGY**: Collect and de-duplicate cards across exactly four verified pages, then bulk-fetch only records with missing card contract values. Estrato is absent from the cards in the verified sample, so residential records normally enter Phase B.
- The filtered route is required. The unfiltered `/inmuebles/` route can trigger a Cloudflare browser-check response.
- Search results can leak `Arriendo/Venta` records. Mixed and sale-only headings are skipped.
- URL slugs are authoritative for `tipo` because some cards have a heading that disagrees with the property URL.
- A missing garage badge is not an explicit zero. Detail labels or source prose such as `No cuenta con parqueadero` must establish zero.
- The detail URL may normalize with a trailing slash after navigation; the canonical stored URL remains the card URL and preserves the numeric suffix.
