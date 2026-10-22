# Arango Tobón Inmobiliaria (`ATB`)

- **URL**: `https://arangotobon.com/todas-las-propiedades/?destinacion=Arriendo&municipio=medellin`
- **Municipalities**: `medellin`, `envigado`, `itagui`, `sabaneta`, `la-estrella`
  (verified slugs of the site's own `municipio` filter; the scraper raises
  `UnsupportedCityError` for anything else)
- **Type**: Server-rendered WordPress theme (GET form filters + `pag` pagination)
- **Portal**: `arangotobon`
- **Strategy**: Two-phase HTML with detail enrichment
- **Card selector**: `.at-dest2-card`
- **Detail page**: `/inmueble/{code}/`
- **Pagination**: `&pag=2`, `&pag=3`, … page 1 has no `pag` param; 12 cards per page
- **Observed inventory**: 98 arriendo results in Medellín across ~9 pages

## Migration Note (2026-10)

The portal replaced its ASP.NET MVC site with WordPress. The old routes
(`/inmuebles/Arriendo/clases_…/municipios_Medellín/`, `/inmueble/{code}-{slug}`)
now return HTTP 404; `www.arangotobon.com` 301-redirects to the apex host. The
inventory lives behind a GET form on `/todas-las-propiedades/` with these
params: `destinacion` (`Arriendo`/`Venta`), `clase`, `municipio`, `barrio`,
`alcobas`, `banos`, `orden`, `codigo`, `estrato`, `garaje`, `min_precio`,
`max_precio`, `caract[]`.

`clase` accepts a single value only — a comma-joined list returns zero results.
The scraper therefore fetches the unfiltered `destinacion=Arriendo&municipio=medellin`
stream and keeps residential classes client-side.

Observed class counts (Medellín, arriendo): apartamento 40, apartaestudio 8,
apto-loft 3, casa 7; the remaining results are bodega, local, oficina, etc.

## Phase A: Search Cards

Cards are fully server-rendered; no JS or AJAX call is needed. Identity comes
from the numeric code in the detail URL and in the `COD:` chip.

| Column | Source | Handling |
|---|---|---|
| `id` | `/inmueble/{code}/` (onclick or `.at-dest2-card-btn`) | Compose `ATB-{code}` |
| `portal` | Fixed | `arangotobon` |
| `tipo` | Second `.at-dest2-tag` (e.g. `Apartamento`) | `apto-loft` becomes `apartaestudio` |
| `precio` | `.at-dest2-price` (`$1.800.000 /mes`) | Shared price normalizer drops the `/mes` suffix |
| `area` | `.at-dest2-area` (`75 m²`) | Integer |
| `habitaciones` | Absent from cards | Keep `0` until Phase B |
| `banos` | Absent from cards | Keep `0` until Phase B |
| `parqueaderos` | Absent from cards | Keep `0` until Phase B |
| `estrato` | Absent from cards | Keep `0` until Phase B |
| `barrio` | `.at-dest2-location` (icon label must be skipped) | Provisional; detail value wins |
| `url` | Card onclick / CTA anchor | Absolute official URL |

Only `Arriendo` cards whose class normalizes to `apartamento`, `casa`, or
`apartaestudio` are kept.

The results counter lives in `p.at-ti2-count`:
`Mostrando <strong>1–12</strong> de <strong>40</strong> propiedades`. The last
`<strong>` is the total and drives page-count estimation; pagination also stops
when a page yields no new IDs.

## Phase B: Detail Pages

Fetch every accepted card URL with `bulk_fetch`. Merge only detail fields whose
`COD:` chip matches the card code:

| Column | Detail source |
|---|---|
| `area` | `.at-sd-feat` pill labelled `m²` (only if the card had none) |
| `habitaciones` | Pill labelled `Alcobas` |
| `banos` | Pill labelled `Baños` |
| `parqueaderos` | Pill labelled `Parqueaderos`/`Garaje` |
| `estrato` | Pill labelled `Estrato` |
| `barrio` | `.at-sd-loc`, first comma-separated segment |

The feature pills carry Material Symbols icon labels (`bed`, `bathtub`,
`straighten`, `directions_car`, `location_city`); the icon text must be skipped
before reading the label. The same `.at-sd-feat` class is reused for amenities
and for the "Sector" block, so only the numeric field labels are accepted —
`Parques Cercanos` must not be read as parking.

The detail page also renders `Canon mensual` in `.at-sd-price-val`, useful for
verification but not authoritative: card prices come from the search stream.

Detail failures retain card values and defaults. Code mismatches are ignored
without changing the card identity.

## Zero-Genuineness and Risks

- `parqueaderos = 0` is genuine when the detail has no parking pill; observed on
  8 of 12 sampled apartamento details.
- `estrato = 0` remains possible when a detail omits the estrato pill.
- Card and detail prices can differ (e.g. detail `$2.600.000` for a card at
  `$1.800.000`); the card value is what the search stream advertises.
- Detail `barrio` may add a sector clause after a comma (`Belen los alpes, Cerca
  universidad medellin`); keep only the first segment.
- The apex host serves the site; `www` only redirects.
- The site sits behind LiteSpeed/Cloudflare caching; use the shared retrying
  fetcher.
