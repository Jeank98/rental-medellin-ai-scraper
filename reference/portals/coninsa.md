# Coninsa (`CON`)

- **URL**: `https://www.coninsa.co/arrendamientos/vivienda/?text=Medellin`
- **Type**: Gatsby SPA with Drupal GraphQL backend
- **Scraping method**: Direct GraphQL API (Search API), no browser needed
- **GraphQL endpoint**: `https://admindrupal.coninsa.co/graphql`
- **Search index**: `search_properties`
- **Listings per request**: Up to 200 (configurable, tested limit)
- **Pagination**: Offset-based via `range: {offset, limit}`

## Scraping Strategy

**Direct GraphQL — no browser required.** The frontend is a Gatsby SPA that renders listings client-side, but the data comes from a Drupal Search API GraphQL endpoint. Query it directly with POST requests.

```python
import scrapling

f = scrapling.Fetcher()
query = """query SearchProperties($offset: Int!, $limit: Int!) {
  searchAPISearch(
    index_id: "search_properties",
    fulltext: {keys: "Medellin"},
    conditions: [
      {name: "field_service_type", value: "AR", operator: "EQUAL"}
    ],
    range: {offset: $offset, limit: $limit}
  ) {
    result_count
    documents {
      ... on SearchPropertiesDoc {
        code
        property_type
        field_lease_value
        field_area
        field_bedrooms
        field_bathrooms
        field_garages
        field_stratum
        neighborhood
        url
      }
    }
  }
}"""
resp = f.post("https://admindrupal.coninsa.co/graphql", json={"query": query, "variables": {"offset": 0, "limit": 200}})
```

### Key query parameters
- `index_id`: `"search_properties"` — the Search API index for property listings
- `fulltext: {keys: "Medellin"}` — full-text search for Medellín
- `conditions: [{name: "field_service_type", value: "AR", operator: "EQUAL"}]` — filter to Arriendo only (AR = rental, CO = corretaje/sale)
- `range: {offset, limit}` — pagination, max 200 per page

### Why old approach (StealthyFetcher + click) failed
The Gatsby SPA loads listing data at runtime via GraphQL. Rendered HTML text saw empty cards because the data is injected client-side. StealthyFetcher with page_action could click "Cargar más" but still never got listings into the HTML text. Direct GraphQL API solves this completely.

## Field Mappings

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | `CON-{code}` | `code` field from SearchPropertiesDoc |
| `portal` | `coninsa` | Fixed |
| `tipo` | `property_type` | `Apartamento` → `apartamento`, `Casa` → `casa`, `Casa finca` → `casa` |
| `precio` | `field_lease_value` | Integer, 0 when not rental |
| `area` | `field_area` | Float → int |
| `habitaciones` | `field_bedrooms` | Integer |
| `banos` | `field_bathrooms` | Integer |
| `parqueaderos` | `field_garages` | Integer |
| `estrato` | `field_stratum` | Integer 1-6 |
| `barrio` | `neighborhood` | Title-cased via `normalize_barrio()` |
| `url` | `url` field | Relative path, prefixed with `https://www.coninsa.co` |

### Residential filter
Only keep `property_type` in: `Apartamento`, `Casa`, `Casa finca`. Exclude: `Local`, `Oficina`, `Bodega`, `Consultorio`, `Por definir`.

### Data volume
- ~327 total AR (rental) listings in Medellín across all property types
- ~199 residential (Apartamento + Casa) after filtering
- 2 GraphQL API calls needed (offset 0 + offset 200 with limit 200)

## Notes
- **No browser needed** — pure HTTP POST to GraphQL endpoint
- **No rate limiting observed** — consecutive requests return 200 OK
- **Introspection enabled** — schema can be explored with introspection queries
- `field_service_type` values: `"AR"` (Arriendo/rental), `"CO"` (Corretaje/sale)
- Property types found: Apartamento, Casa, Casa finca, Local, Oficina, Bodega, Consultorio, Por definir
