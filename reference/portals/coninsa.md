# Coninsa (`CON`)

- **URL**: `https://www.coninsa.co/arrendamientos/vivienda/?text=Medellin`
- **Type**: JS-rendered SPA (React/headless CMS)
- **Listing card**: Unknown — listings load via AJAX after page load
- **Listings per load**: Unknown
- **Total listings**: Unknown
- **Pagination**: "Cargar más inmuebles" button — infinite scroll via AJAX
- **Status**: 🔲 **Blocked** — requires browser automation with click simulation

## Blockers

1. **No server-rendered listings**: All listing data loads via JavaScript after page load
2. **No discovered API endpoint**: Common patterns (wp-json, REST API) return 404
3. **Infinite scroll button**: Needs browser session + click automation to reach all properties
4. **Scrapling MCP** would solve this with `open_session` + `fetch` + click simulation, but MCP tools are not yet loaded in the session

## Next Steps

When Scrapling MCP tools are available:
1. `scrapling_open_session(type: "dynamic")`
2. `scrapling_fetch` the page with `session_id`
3. Use CSS selectors to find "Cargar más" button, click repeatedly until exhausted
4. Extract listing data from rendered HTML

Alternatively, find the API endpoint by inspecting network requests in browser DevTools.
