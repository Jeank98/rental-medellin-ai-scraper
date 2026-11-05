"""Coninsa (CON) — GraphQL Search API Scraper.

Queries the Drupal Search API GraphQL endpoint directly, avoiding
the Gatsby SPA rendering issues that returned 0 listings.
"""

import logging

from scrape.cities import normalize_city
from scrape.normalize import normalize_tipo, normalize_barrio
from scrape.validator import validate

logger = logging.getLogger(__name__)

_GRAPHQL_URL = "https://admindrupal.coninsa.co/graphql"
_BASE_DOMAIN = "https://www.coninsa.co"

# Residential property types to keep — everything else is excluded
_RESIDENTIAL_TYPES = {"Apartamento", "Casa", "Casa finca"}

# Manual override for ambiguous types that normalize_tipo can't handle
_TIPO_OVERRIDE = {
    "Casa finca": "casa",
}

_COLUMNS = [
    "id", "portal", "tipo", "precio", "area",
    "habitaciones", "banos", "parqueaderos", "estrato",
    "barrio", "url",
]

_PAGE_SIZE = 200

_CITY_NAMES = {
    "medellin": "Medellin",
    "envigado": "Envigado",
    "itagui": "Itagui",
    "sabaneta": "Sabaneta",
    "la-estrella": "La Estrella",
}


def _city_name(ciudad: str) -> str:
    """Map a municipality to the name the Search API's fulltext expects."""
    key = normalize_city(ciudad)
    name = _CITY_NAMES.get(key)
    if name is None:
        raise ValueError(
            f"Coninsa has no verified fulltext for {ciudad!r}; known: "
            f"{sorted(set(_CITY_NAMES.values()))}"
        )
    return name

_GRAPHQL_TEMPLATE = """query SearchProperties($offset: Int!, $limit: Int!) {
  searchAPISearch(
    index_id: "search_properties",
    fulltext: {keys: "%s"},
    conditions: [
      {name: "field_service_type", value: "AR", operator: "EQUAL"}
    ],
    range: {offset: $offset, limit: $limit}
  ) {
    result_count
    documents {
      ... on SearchPropertiesDoc {
        code
        city_string
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


def _fetch_graphql(query: str, variables: dict) -> dict | None:
    """POST a GraphQL query to the Coninsa Drupal endpoint."""
    import scrapling

    fetcher = scrapling.Fetcher
    try:
        resp = fetcher.post(
            _GRAPHQL_URL,
            json={"query": query, "variables": variables},
            timeout=30,
        )
        if resp.status >= 400:
            logger.warning("GraphQL HTTP %s", resp.status)
            return None
        return resp.json()
    except Exception as e:
        logger.error("GraphQL fetch error: %s", e)
        return None


def _map_listing(doc: dict) -> dict:
    """Map a SearchPropertiesDoc to a standard 11-column listing dict."""
    code = doc.get("code", "")
    listing = dict.fromkeys(_COLUMNS, "")
    listing["id"] = f"CON-{code}"
    listing["portal"] = "coninsa"

    raw_tipo = doc.get("property_type", "")
    listing["tipo"] = _TIPO_OVERRIDE.get(raw_tipo, normalize_tipo(raw_tipo))

    listing["precio"] = int(doc.get("field_lease_value") or 0)
    listing["area"] = int(doc.get("field_area") or 0)
    listing["habitaciones"] = doc.get("field_bedrooms") or 0
    listing["banos"] = doc.get("field_bathrooms") or 0
    listing["parqueaderos"] = doc.get("field_garages") or 0
    listing["estrato"] = doc.get("field_stratum") or 0
    listing["barrio"] = normalize_barrio(doc.get("neighborhood") or "")

    url_path = doc.get("url", "")
    listing["url"] = f"{_BASE_DOMAIN}{url_path}" if url_path else ""

    return listing


def scrape(
    ciudad="medellin", sample_only=False, max_pages=None, verbose=False
) -> list[dict]:
    """Scrape Coninsa rental listings via GraphQL Search API.

    Searches Arriendo (AR) listings by fulltext, then filters residential
    documents by their source municipality. Paginates using offset/limit.

    Returns:
        List of 11-column listing dicts.
    """
    city_name = _city_name(ciudad)
    city_key = normalize_city(city_name)
    listings = []
    offset = 0
    total = 0
    pages_fetched = 0
    anomaly_count = 0

    while True:
        variables = {"offset": offset, "limit": _PAGE_SIZE}
        result = _fetch_graphql(_GRAPHQL_TEMPLATE % city_name, variables)

        if not result or "data" not in result:
            logger.error("GraphQL query failed at offset %d", offset)
            break

        search = result["data"].get("searchAPISearch")
        if not search:
            break

        if offset == 0:
            total = search.get("result_count", 0)
            if verbose:
                logger.info("Total rental listings in Medellin: %d", total)

        documents = search.get("documents", [])
        if not documents:
            break

        pages_fetched += 1

        for doc in documents:
            prop_type = doc.get("property_type", "")
            if prop_type not in _RESIDENTIAL_TYPES:
                continue

            source_city = doc.get("city_string")
            source_city = normalize_city(source_city) if isinstance(source_city, str) else ""
            if not source_city:
                raise ValueError("Coninsa residential listing has missing or invalid city_string")
            if source_city != city_key:
                continue

            listing = _map_listing(doc)
            listings.append(listing)

            warnings = validate(listing)
            if warnings:
                anomaly_count += 1
                if verbose:
                    for w in warnings:
                        print(f"  [ANOMALY] {listing['id']} — {w}")

        if verbose:
            logger.info(
                "Page %d: fetched %d docs, %d residential listings so far",
                pages_fetched,
                len(documents),
                len(listings),
            )

        if offset + _PAGE_SIZE >= total:
            break

        offset += _PAGE_SIZE

        if max_pages and pages_fetched >= max_pages:
            break

    if sample_only:
        print(f"Sample: {len(listings)} residential listing(s) extracted")

    if anomaly_count and verbose:
        print(
            f"\n{anomaly_count} anomaly(s) detected across {len(listings)} listings."
        )

    return listings
