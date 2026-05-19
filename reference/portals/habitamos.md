# Habitamos (`HBM`)

- **URL**: `https://en.habitamos.com.co/resultados/1/asc/fecha_consignacion/arriendo/tipo_propiedad_defecto/Medell%C3%ADn/barrio_defecto/banios_defecto/alcobas_defecto/precio_desde_defecto/precio_hasta_defecto/codigo_defecto/area_desde_defecto/area_hasta_defecto`
- **Type**: Server-rendered Drupal 9 (PHP, no JS)
- **Listing card**: `.cell.medium-6.large-3.margin-bottom-1`
- **Listings per page**: ~50
- **Total pages**: 3 — discovered dynamically (page 4 returns "There are no properties")
- **Pagination**: Page number in URL path: `/resultados/{N}/asc/...`

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `HBM-{code}` | `Code: 5382` |
| `portal` | `habitamos` | Fixed |
| `tipo` | Heading `TIPO - Medellin - BARRIO` | Normalize EN/ES: Apartment→apartamento, House→casa, etc. |
| `precio` | `$` line or "Rental price: $" | Dual For Lease/Sale: take rental price only |
| `area` | **Not in card** | → `0` |
| `habitaciones` | `Features: Bedrooms: N` (EN/ES mixed) | Also check `Habitaciones: N` |
| `banos` | `Bathrooms: N` or `Baños: N` | 0 if absent |
| `parqueaderos` | `Garage: N` | 0 if absent |
| `estrato` | **Not in card** | → `0` |
| `barrio` | Heading after `Medellin - ` | Mixed EN/ES: "Medellín" or "Medellin" |
| `url` | `/propiedad/{CODE}` | Prepend `https://en.habitamos.com.co` |

**Notes**:
- Mixed English/Spanish labels — handle both for Features extraction
- Title comes AFTER features/price in text (unusual order)
- Compound tipos: Casa-local→casa, Local-house→local, Office-Consultorio→oficina
- "For Lease/Sale" = dual price: extract "Rental price:" value
- 148 listings extracted (2026-05-18)
