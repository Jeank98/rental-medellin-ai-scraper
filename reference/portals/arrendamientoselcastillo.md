# Arrendamientos El Castillo (`AEC`)

- **URL sources**: Official rental routes filtered by residential type
- **Type**: Two-phase browser-rendered Livewire search plus detail enrichment
- **Listing card**: Each card exposes `COD`, current price, type, area, alcobas, baños, parqueaderos, barrio, and a detail link
- **Pagination**: Each route uses the same IntersectionObserver/Livewire `load-more`; scroll until that route's visible COD set stops growing. The URL does not change.
- **Permalink**: Absolute `/detalle-propiedad/{slug}-{COD}` URL from the card; preserve the visible COD as `AEC-{COD}`

## Residential URL sources

| Normalized type | Exact official URL parameter | Verified result count | Observed card types |
|---|---|---:|---|
| `apartamento` | `?gestion=Arriendo&tipo=Apartamentos` | 143 | `apartamento` only |
| `casa` | `?gestion=Arriendo&tipo=Casas` | 54 | `casa` only |
| `apartaestudio` | `?gestion=Arriendo&tipo=Apartaestudios` | 54 | `apartaestudio` only |

The scraper unions these three sources by `AEC-{COD}` before Phase B. The final
normalized-type guard accepts only these three values. No additional residential
subtype was observed or accepted; `Casas Fincas`, `Casas Locales`, and all
commercial type routes remain excluded.

The verified production baseline is 251 active listings: 143 apartamentos, 54
casas, and 54 apartaestudios. The orchestrator minimum is 225, allowing up to
26 rows of inventory drift while flagging a loss of 27 or more.

| Column | Source | Notes |
|---|---|---|
| id | `COD: N` | `AEC-N`; matches detail `Código: N` |
| portal | constant | `arrendamientoselcastillo` |
| tipo | Standalone card type line | Normalize through shared `normalize_tipo`; only `apartamento`, `casa`, and `apartaestudio` enter output |
| precio | Current non-struck-through `$` value | Ignore an older value rendered in `del` |
| area | Card line ending in `m²` | Integer square metres |
| habitaciones | `Alcobas` / `Alcoba` | Commercial cards can explicitly show `0` |
| banos | `Baños` / `Baño` | Card value |
| parqueaderos | `parq.` | Explicit `0` is retained |
| estrato | Detail `Estrato: N` line | Search cards omit it; missing detail label remains `0` |
| barrio | Card title after the final ` - ` | Normalized with shared barrio helper |
| url | Card detail anchor | Absolute, stable numeric-COD permalink in the verified sample |

## Zero genuineness

- Search cards visibly emit `0 Alcobas` and `0 parq.` for commercial records; these source values are filtered before detail requests.
- Search cards do not emit `Estrato`; detail pages do. A fetched detail without an Estrato label yields `0`.
- A failed detail fetch leaves `estrato=0`; the current validator does not flag that zero, so no validation or logging guarantee should be inferred.

## Risks

- Full extraction requires a browser-backed Livewire scroll loop rather than numbered page URLs.
- Every unique card requires a detail request for complete `estrato` coverage.
- The unfiltered `gestion=Arriendo` route includes `local`, `oficina`, and `bodega` records; do not use it as a production source.
