# Panorama Inmobiliario

## Identity

- Portal: `panoramainmobiliario`
- Prefix: `PAN`
- Platform: Wasi.co, server-rendered HTML
- Strategy: two-phase HTML
- Scope: Medellín rentals only (`id_city=496`)

## Verified source URLs

Panorama's unfiltered search mixes residential and commercial inventory. The
scraper must query the three residential streams separately:

| Type | `id_property_type` | Source |
|---|---:|---|
| Apartaestudio | `14` | `/search?id_city=496&id_property_type=14&business_type%5B0%5D=for_rent&order_by=created_at&order=desc&page=N&for_sale=0&for_rent=1&for_temporary_rent=0&for_transfer=0&lax_business_type=1` |
| Apartamento | `2` | Same URL with `id_property_type=2` |
| Casa | `1` | Same URL with `id_property_type=1` |

The result page has 12 cards per page in the verified live sample. Continue
until the filtered page has no cards or fewer than 12 cards. The observed live
sample had 10 apartaestudio pages, 29 apartamento pages, and 8 casa pages;
the final pages were partial or empty, so the scraper does not hardcode these
counts. An incomplete page response is retried once; the response with the
most cards is retained, and two incomplete responses still terminate the
stream. This protects the first page from transient empty/short HTML without
creating an unbounded pagination loop.

## Phase A: Search cards

- Card selector: `.list-properties .item.item_small`
- Detail URL: first official anchor in the card with a numeric final path segment
- ID: numeric final path segment, emitted as `PAN-{code}`
- Type: the filtered `id_property_type` stream is authoritative; `.tag1` is a
  consistency check. Do not infer type from the title, image alt text, or JSON-LD.
- Price: the card's `.areaPrecio` block labelled `Alquiler`; this avoids taking
  the sale price when both sale and rent are shown.
- Listings with a negative price or a price above PostgreSQL's integer maximum
  (`2147483647`) are skipped with an ID/value warning; valid prices are not
  coerced.
- Card fields: `tipo`, `precio`, `area`, `habitaciones`, `banos`,
  `parqueaderos`, and `url`; `id` is derived from `url`.
- Not on cards: structured `estrato` and `barrio`.

## Phase B: Detail pages

The first `ul.list-info-2` containing `Tipo de inmueble` is the structured
property-detail block. Labels observed in live samples include:

- `Zona / barrio`
- `Área Construida`
- `Alcobas`
- `Baño` or `Baños`
- `Garaje`
- `Estrato`
- `Tipo de inmueble`

Merge positive detail values without replacing the filtered type. A failed
detail fetch keeps card values and defaults. A non-residential detail type is
rejected. Detail JSON-LD is SEO metadata and was inconsistent in a live
sample, so it is not an extraction source.

## Normalization and zero values

- Accept only `apartamento`, `casa`, and `apartaestudio`.
- Deduplicate before Phase B by the numeric URL code, not by title or slug.
- `estrato=0` means the detail omitted it or reported the non-numeric value
  `Comercial`; it is not an inferred socioeconomic level.
- `barrio=""` means no explicit detail label was available.
- `parqueaderos=0`, `banos=0`, or `area=0` can be a real source value or a
  missing value; do not invent replacements.

## Risks

- Source titles and image alt text can contradict the structured type. A live
  `CASA` card had an `APARTAMENTO` title, and an `APARTAESTUDIO` card had a
  `LOCAL` title; both retained their filtered/structured type.
- Some cards expose both `Venta` and `Alquiler`; always select the rental
  block. The `for_rent` query can still leak sale-only cards, which are
  skipped when no explicit `Alquiler` block exists.
- The site loads reCAPTCHA, has a CSRF token and `/gettoken`, and can issue
  location AJAX requests. The listing HTML itself was returned in the initial
  document; no inventory API or GraphQL endpoint was observed.
- Use bounded concurrency and retries. Detail fetch volume is much larger
  than search-page volume.
