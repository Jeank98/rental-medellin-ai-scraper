# Merino Hermanos (`MHR`)

- **URL**: `https://merinohermanos.com/inmuebles?b_type=arriendo`
- **Type**: Server-rendered PHP
- **Listing card**: Cards identified by price pattern `$N.NNN.NNN`
- **Listings per page**: 30
- **Total pages**: Discovered via `?page=N` pagination
- **Pagination**: `?b_type=arriendo&page=N`

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `MHR-{code}` | Numeric code line after price |
| `portal` | `merinohermanos` | Fixed |
| `tipo` | Line after price | `Oficina` → `oficina` |
| `precio` | `$` line | `$500.000` → `500000` |
| `area` | `Area N M2` | `Area 18 M2` → `18` |
| `habitaciones` | `N Alcoba(s)` | `0 Alcobas` → `0` |
| `banos` | `N Baño(s)` | `1 Baño` → `1` |
| `parqueaderos` | **Not in card** | → `0` |
| `estrato` | **Not in card** | → `0` |
| `barrio` | `CIUDAD - BARRIO` line | Split on ` - `, take right |
| `url` | Fixed search URL | `https://merinohermanos.com/inmuebles?b_type=arriendo` |

**Notes**:
- All fields text-labeled, no icon-only fields
- Property types include compound: `Oficina-Consultorio`, `Casa-Finca`, `Casa-local`, `Oficina-Local`
- Standard pagination via `?page=N` — MCP-native with `scrapling_bulk_get`
- 30 listings per page, 8 pages for arriendo

## Zero Genuineness

| Field | Default 0 | Status |
|-------|-----------|--------|
| `parqueaderos` | 0 | ✅ Genuine — Not in card |
| `estrato` | 0 | ✅ Genuine — Not in card |
