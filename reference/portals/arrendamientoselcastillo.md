# Arrendamientos El Castillo (`AEC`)

- **URL**: `https://www.arrendamientoselcastillo.com.co/resultados?gestion=Arriendo`
- **Type**: Two-phase browser-rendered Livewire search plus detail enrichment
- **Listing card**: Each card exposes `COD`, current price, type, area, alcobas, baños, parqueaderos, barrio, and a detail link
- **Initial batch**: 36 unique cards in the verified sample
- **Inventory**: The page reported 497 rental results at assessment time
- **Pagination**: IntersectionObserver dispatches Livewire `load-more`; scroll until the visible COD set stops growing. The URL does not change.
- **Permalink**: Absolute `/detalle-propiedad/{slug}-{COD}` URL from the card; preserve the visible COD as `AEC-{COD}`

| Column | Source | Notes |
|---|---|---|
| id | `COD: N` | `AEC-N`; matches detail `Código: N` |
| portal | constant | `arrendamientoselcastillo` |
| tipo | Standalone card type line | Normalize through shared `normalize_tipo`; retain residential and commercial types |
| precio | Current non-struck-through `$` value | Ignore an older value rendered in `del` |
| area | Card line ending in `m²` | Integer square metres |
| habitaciones | `Alcobas` / `Alcoba` | Commercial cards can explicitly show `0` |
| banos | `Baños` / `Baño` | Card value |
| parqueaderos | `parq.` | Explicit `0` is retained |
| estrato | Detail `Estrato: N` line | Search cards omit it; missing detail label remains `0` |
| barrio | Card title after the final ` - ` | Normalized with shared barrio helper |
| url | Card detail anchor | Absolute, stable numeric-COD permalink in the verified sample |

## Zero genuineness

- Search cards visibly emit `0 Alcobas` and `0 parq.` for sampled commercial records; these are source values, not inferred defaults.
- Search cards do not emit `Estrato`; detail pages do. A fetched detail without an Estrato label yields `0`.
- A failed detail fetch also leaves `estrato=0` and is reported through the scraper's existing validation/logging path.

## Risks

- Full extraction requires a browser-backed Livewire scroll loop rather than numbered page URLs.
- Every unique card requires a detail request for complete `estrato` coverage.
- Broad `Arriendo` results include `local`, `oficina`, and `bodega` records as well as residential listings.
