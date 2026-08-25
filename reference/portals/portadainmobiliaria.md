# Portada Inmobiliaria (`POR`)

- **URL**: `https://portadainmobiliaria.com/busqueda/`
- **API**: `https://api-crinmo.azurewebsites.net/simi/v2.1.1/filtroInmueble`
- **Type**: REST API consumed by the public Vue application
- **Listings per page**: 12
- **Total pages**: `datosGrales.fin` (fallback: ceil(`totalInmuebles` / 12))
- **Pagination**: Path-based URL with `limite/{page}/total/12`
- **Key feature**: The API requires the public Basic authorization header embedded in the portal JavaScript client.

## Request Strategy

The scraper makes one request per page for each residential type:

- `tipoInm=1`: apartamento
- `tipoInm=2`: casa
- `tipoInm=11`: apartaestudio

Fixed request filters are Medellin `ciudad=25974`, arriendo `tipOper=1`,
`barrio=0`, `valmin=500000`, `valmax=50000000`, `campo=fecha`,
`precio=0`, `order=desc`, `banios=0`, `alcobas=0`, `garajes=0`,
`sede=0`, and `usuario=0`.

The full route is:

```text
/simi/v2.1.1/filtroInmueble/limite/{page}/total/12/ciudad/25974/barrio/0/tipoInm/{tipo}/tipOper/1/valmin/500000/valmax/50000000/campo/fecha/precio/0/order/desc/banios/0/alcobas/0/garajes/0/sede/0/usuario/0
```

## Field Mapping

| Column | Source | Normalization |
|---|---|---|
| `id` | `Codigo_Inmueble` | `POR-{complete code}`, e.g. `POR-679-78592` |
| `portal` | Constant | `portadainmobiliaria` |
| `tipo` | `Tipo_Inmueble` | `normalize_tipo`; only residential types are retained |
| `precio` | `Canon` | `normalize_price`, COP integer |
| `area` | `AreaConstruida` | Integer square metres |
| `habitaciones` | `Alcobas` | Integer |
| `banos` | `banios` | Integer |
| `parqueaderos` | `garaje` | Integer; structured `0` is preserved |
| `estrato` | `Estrato` | `normalize_estrato`, integer 1-6 |
| `barrio` | `Barrio` | `normalize_barrio` |
| `url` | `Codigo_Inmueble` | `https://portadainmobiliaria.com/busqueda/#/inmueble/{code}` |

## Notes

- The API response is structured JSON under `Inmuebles`; descriptions are not used for contractual fields.
- `datosGrales.fin` is the total page count. For the verified apartment sample, `totalInmuebles=394` and `fin=33`.
- Duplicate complete property codes keep their first-seen row.
- A JSON payload containing only `message` or missing `Inmuebles`/`datosGrales` is rejected instead of being treated as an empty inventory.
- No detail phase is required because all 11 output fields are present in each API record.
