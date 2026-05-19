# Alnago (`ALN`)

- **URL**: `https://alnago.com/es/categorias/arrendar/todos/medellin`
- **Type**: JS-rendered SPA with REST API
- **API endpoint**: `https://alnago.com/api/v1/properties?type=arrendar&city=medellin&skip=0&limit=30`
- **Key feature**: **REST API — all 11 fields, no parsing needed**

| Column | API field | Pattern |
|--------|-----------|---------|
| `id` | `ALN-{entry}` or `ALN-{id_property}` | `entry` field (fallback: `ALN-{id_property}` if entry empty/"0") |
| `portal` | `alnago` | Fixed |
| `tipo` | `property_type.name` or `id_property_type` | Map type IDs: 1=apartamento, 2=casa, 8=apartaestudio, 3=oficina, 4=local, 5=bodega, 6=lote, 11=local, 16=habitacion |
| `precio` | `price` | Already integer (0 if "Consultar precio") |
| `area` | `area` | Already integer |
| `habitaciones` | `rooms` | Already integer (0 for commercial) |
| `banos` | `bathrooms` | Already integer |
| `parqueaderos` | `parking_capacity` | Already integer |
| `estrato` | `stratum` | Already integer (8=commercial → 0) |
| `barrio` | `neighborhood.name` | String |
| `url` | `url` | Already absolute URL |

**API Parameters**: `skip=0&limit=30` for pagination, `type=arrendar`, `city=medellin`

**Notes**:
- ID collisions: Alnago reuses `entry` codes for different `id_property` — append `-{id_property}` to resolve
- Invalid entries: `entry=""` or `"0"` → use `ALN-{id_property}` as fallback
- Estrato 8 = commercial properties → convert to 0
- 761 listings extracted via REST API (2026-05-18)
- Cleanest portal after ADN — structured JSON, no parsing needed
