# Inmobiliaria La Estrella (`LES`)

- **URL source**: three official residential Livewire search routes, with no
  municipal filter
- **Type**: two-phase — browser-rendered load-more discovery plus static detail
  pages with JSON-LD
- **Listing card**: detail link, current price, type, area, alcobas, baños,
  parqueaderos
- **Pagination**: IntersectionObserver/Livewire load-more driven by normal page
  scrolling; numbered `page`/`pagina` parameters are ignored by the site
- **Permalink**: absolute property URL from the card; the visible numeric code
  becomes `LES-{code}`
- **City scope**: `medellin`, `envigado`, `itagui`, `la-estrella`, `sabaneta`
  (`la-estrella` is the existing database scope key)

## Residential URL sources

| Normalized type | Exact official URL parameter |
|---|---|
| `apartamento` | `?gestion=Arriendo&tipo=Apartamentos` |
| `casa` | `?gestion=Arriendo&tipo=Casas` |
| `apartaestudio` | `?gestion=Arriendo&tipo=Apartaestudios` |

The three routes are queried as-is. The site's municipal facet
`s=municipio-en-...` is not reliable: Itagui returns La Estrella properties and
Envigado returns nothing even when Envigado inventory exists. Discovery
therefore enumerates each residential type unfiltered, unions the cards by
`LES-{code}`, and assigns each property to a city only after reading its detail
page.

`Casa-Finca`, `Casa-Local`, and commercial types are not accepted. The raw type
is matched exactly; it is never passed through `normalize_tipo`, which would
split on the hyphen and turn `Casa-Finca` into `casa`.

## Load-more progress

Each route starts from the server-rendered cards and then scrolls. A scroll
triggers the page's own IntersectionObserver, which posts the Livewire update
that dispatches `load-more`; the scraper never calls a guessed `loadMore`
method or a fabricated endpoint.

A route is complete only when a settled window produces no new detail codes and
the loader image is no longer visible. The result set must also be a superset of
the previous one. If scrolling stops producing cards while the loader image is
still visible, or cards disappear, the route fails with `PortalDiscoveryError`
instead of returning a partial snapshot. Because a repeat-ID response while the
loader is active is exactly that symptom, it fails too.

The activity signal is the loader IMG, not the `.property_loader` wrapper: the
site keeps that DIV mounted after the last batch and removes only the spinner
image, so matching the wrapper class would report a permanent "still loading"
state. A loader image that is zero-sized, `display:none`, or
`visibility:hidden` does not count as visible.

Progress is measured by stable detail codes extracted from card URLs, so a
route that renders the same batch twice cannot be mistaken for completion.
Full mode has no batch ceiling: it scrolls until a settled window adds no code
and the loader image is gone, and it raises instead of truncating. `max_pages`
is the only explicit batch bound, used for testing. Sample mode bounds discovery
batches to at most three per route, then schedules at most three detail pages
per requested city before fetching any of them.

## Detail extraction

Each unique card is fetched once as static HTML. A missing or malformed detail
response is a technical failure, never a skipped row. The JSON-LD
`RealEstateListing` block is authoritative:

| Column | Source | Notes |
|---|---|---|
| `id` | Visible `COD`/`Código` label, else trailing numeric path segment | `LES-9564`; canonical URL, `og:url`, JSON-LD `url`/`identifier`, or primary visible code must carry the same code |
| `portal` | constant | `inmobiliarialaestrella` |
| `tipo` | Exact raw card type | Only `apartamento`, `casa`, `apartaestudio` |
| `precio` | `offers.price` of the `LeaseOut` offer (or its `priceSpecification.price`) | Current price; struck-through visible prices are ignored, and a `Sell` offer never prices a rental listing |
| `area` | `about.floorSize.value` | `int(float(...))` for decimal values; card value only if the detail omits it |
| `habitaciones` | `numberOfBedrooms` | 0 when absent |
| `banos` | `numberOfBathroomsTotal` | 0 when absent |
| `parqueaderos` | `amenityFeature` entry named Parqueaderos | Entry omitted when zero, so omission means `0`; never inferred from amenities |
| `estrato` | Primary visible `Estrato` label | Missing label remains `0` |
| `barrio` | Explicit `Sector <name>` phrase inside the listing's own description or detail heading | Never read from the page-wide search control (labelled `Sector/Ubicación`), navigation, or recommendation blocks. Generic lowercase prose such as `un sector residencial` is not a sector, so a page without an explicit named sector stays empty; the card title municipality is never used |
| `url` | Absolute card detail link | Stable permalink |

Visible label parsing ignores recommendation blocks (`relateds-*`), struck price
markup, and other secondary content, so related cards cannot supply an estrato
for the primary listing. The sector is read only from primary property content:
the site renders the global search control as `Sector/Ubicación`, and its `/`
is not a valid sector delimiter.

Operation is guarded from JSON-LD `offers.businessFunction` (a nested
`LeaseOut` versus `Sell` on the offer object) with the page heading as fallback.
Within one detail page the `LeaseOut` offer supplies the price first, and a
`Sell` price is never used while a rental offer exists. Only a page with no
rental offer at all (a sale page) may read the sale price, so it can be
classified and dropped. A detail that resolves to sale is logged and dropped
rather than written to a rental scope; a detail whose operation cannot be
identified as `rent` fails with `PortalDetailError` instead of being published
as a rental.

The `RealEstateListing` JSON-LD block must identify this listing. A candidate
that declares another property's code is a recommendation, never a fallback, so
it cannot donate its price or municipality to the primary record; when every
candidate declares another code, the detail is rejected even if the page
canonical matches. `address.addressLocality` is read only from the listing and
its `about`/`mainEntity` property subject; agency or provider addresses are
ignored and a missing property locality fails the detail.

## City assignment

`address.addressLocality` is one free-text `neighborhood` value, not a
municipality field: for La Estrella, Itagüí, Sabaneta, and Envigado rows it
normally contains the municipality, but for Medellín rows it normally contains
the barrio, comuna, or corregimiento (for example `POBLADO`, `LAURELES`,
`SAN ANTONIO DE PRADO`).

Resolution therefore uses three primary-evidence steps, in order:

1. An exact supported municipality in `addressLocality` (normalized with the
   shared city helper) wins. Records for unrequested supported cities are
   dropped from the requested scopes.
2. The property's own description title line is read for one supported
   municipality. The live descriptions put the title before the body, so only
   that line is inspected: `Sector Guayabal, Medellín (Piso 16)` and
   `Itagüí, Sector Bariloche (Piso 1)` are primary evidence, while body prose
   such as `cerca de Envigado` is never consulted. Two different municipalities
   in that line fail the detail.
3. An explicit, individually verified Medellín locality alias is used when the
   title line names no municipality.

The alias table is deliberately closed. Each entry was verified against
Medellín's official comuna/corregimiento geometry (ArcGIS `Comunas y
Corregimientos`, `VM_POT48_Base` layer 3) for the live inventory on
2026-10-22:

| Normalized locality | Official Medellín unit |
|---|---|
| `san-antonio-de-prado` | Corregimiento de San Antonio de Prado (comuna 80) |
| `poblado`, `el-poblado` | El Poblado (comuna 14) |
| `laureles` | Laureles (comuna 11) |
| `belen` | Belén (comuna 16) |
| `belen-rosales` | Rosales, Belén (comuna 16) |
| `guayabal` | Guayabal (comuna 15) |
| `america`, `la-america` | La América (comuna 12) |
| `floresta`, `la-floresta` | La Floresta (comuna 12) |
| `velodromo`, `el-velodromo` | El Velódromo (comuna 11) |
| `lopez-de-mesa` | López de Mesa (comuna 7) |
| `buenos-aires` | Buenos Aires (comuna 9) |
| `villa-hermosa` | Villa Hermosa (comuna 8) |

Every other label stays unresolved and is logged with its source code; it is
never assumed to be Medellín. `BARILOCHE`, for example, is an Itagüí sector and
resolves to `itagui` only because its own title line names Itagüí. Adding a new
alias requires the same official verification, not a name resemblance.

When the title line and a documented alias disagree, or when an exact
municipality and the title line disagree, `parse_detail` raises
`PortalDetailError` instead of publishing a conflicting city.

`scrape_cities` runs discovery once and fetches each detail once for all
requested cities; `scrape` delegates to it for a single city. A local JSON-LD
`RealEstateListing` that belongs to a different municipality is never used as
the primary record.

Sample mode reads the card's `en Arriendo - CITY` title only as a scheduling
hint. Before any detail is fetched, up to three candidates per requested city
are allocated from their hints, and leftover slots are filled round-robin from
cards with no usable hint. The schedule therefore never exceeds three detail
requests per requested city, and six cards from the first city cannot consume
the second city's budget. The fetched detail's primary municipality resolution
still decides where the row is published, so a wrong hint cannot move a listing
between scopes.

## Verified samples

| Code | Municipality | Precio | Área | Hab | Baños | Parqueaderos | Estrato | Sector |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 9564 | Itagüí | 2.700.000 | 70 | 3 | 2 | 1 | 4 | Ditaires |
| 9704 | La Estrella | 2.300.000 | 70 | 3 | 2 | 1 | 3 | Ferrería |
| 9648 | La Estrella | 1.700.000 | 50 | 2 | 2 | 0 | 3 | *(empty)* |
| 8187 | Medellín (locality `SAN ANTONIO DE PRADO`) | 1.200.000 | 52 | 2 | 1 | 0 | 3 | Rosaleda |
| 9454 | Itagüí (locality `ITAGUI SANTA MARIA`, title names Itagüí) | 2.200.000 | 50 | 2 | 1 | 0 | 3 | *(empty)* |
| 9612 | Medellín (locality `GUAYABAL`, title names Medellín) | 3.000.000 | 42 | 2 | 1 | 1 | 5 | *(empty)* |

The sitemap is stale and is not used for enumeration; card discovery is the
inventory source.

## Risks

- Load-more depends on the site's scrolling observer and Livewire update route;
  a redesign that replaces either must be re-probed before production.
- The loader-visibility check matches only the spinner image inside the
  verified loader wrapper (`.property_loader img`). Matching the persistent
  wrapper itself would never report completion; a loader redesign must be
  re-probed before production.
- Full mode has no batch ceiling, so a route that keeps appending new cards
  without ever settling is bounded only by the settle timeout and the route's
  own inventory; it fails loudly rather than publishing a truncated snapshot.
- Detail metrics require the JSON-LD `RealEstateListing` block. If it is removed
  or renamed, the crawl fails instead of silently emitting zero-filled rows.
- The sector exists only inside the property description (for example
  `Sector Ditaires, Itagüí`). A page whose prose has no named sector, or only
  generic wording such as `un sector residencial`, publishes an empty barrio
  rather than inferring one from the municipality or nearby place names.
- Cards carry no reliable municipality, so sample mode can fetch up to three
  details per requested city but cannot guarantee inventory coverage for a city
  that appears deeper in the result list.
- The locality field is free text. A new Medellín barrio that is not in the
  verified alias table, and whose title line names no municipality, is logged
  as `unrecognized locality` and excluded from every scope. It is never
  published as Medellín by resemblance; adding it requires official
  comuna/corregimiento verification and a regression test.
- The title-line municipality rule depends on the description keeping its
  current title-first shape. If the site starts with body prose, a municipality
  mentioned incidentally could be read as the property's city; that would need
  a re-probe of the live description format before trusting the rule.
