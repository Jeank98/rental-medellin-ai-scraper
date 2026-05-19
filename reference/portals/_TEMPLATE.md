# Template — New Portal

When discovering a new portal, create a new file `reference/portals/{portal_name}.md` using this template:

```markdown
# {Portal Name} (`{PREFIX}`)

- **URL**: {search_results_url}
- **Type**: {server-rendered | JS-rendered | hybrid}
- **Listing card**: {css_selector}
- **Listings per page**: {N}
- **Total pages**: {how to discover pagination}
- **Pagination**: {url_pattern}
- **Key feature**: {any special discovery about this portal}

| Column | Source | Pattern |
|--------|--------|---------|
| `id` | {source} | {pattern} |
| `portal` | {portal_name} | Fixed |
| `tipo` | {source} | {pattern} |
| `precio` | {source} | {pattern} |
| `area` | {source} | {pattern} |
| `habitaciones` | {source} | {pattern} |
| `banos` | {source} | {pattern} |
| `parqueaderos` | {source} | {pattern} |
| `estrato` | {source} | {pattern} |
| `barrio` | {source} | {pattern} |
| `url` | {source} | {pattern} |

**Notes**:
- {observations, quirks, gotchas}
```
