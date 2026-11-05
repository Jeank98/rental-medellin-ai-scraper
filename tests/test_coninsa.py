"""Consumer-facing municipality filtering for Coninsa GraphQL results."""

import re

import pytest

from scrape import coninsa


# Records 97041 and 97926 are from the captured Coninsa source response.
MEDELLIN = {
    "code": "97041", "city_string": "MEDELLÍN", "property_type": "Apartamento",
    "field_lease_value": 5500000, "field_area": 103, "field_bedrooms": 2,
    "field_bathrooms": 2, "field_garages": 0, "field_stratum": 5,
    "neighborhood": "EL POBLADO",
    "url": "/inmuebles/apartamento-en-arriendo/el-poblado/medellin/97041",
}
ENVIGADO = {
    "code": "97926", "city_string": "ENVIGADO", "property_type": "Casa",
    "field_lease_value": 7000000, "field_area": 220, "field_bedrooms": 5,
    "field_bathrooms": 4, "field_garages": 0, "field_stratum": 4,
    "neighborhood": "MESA", "url": "/inmuebles/casa-en-arriendo/mesa/envigado/97926",
}


def _serve_documents(monkeypatch, documents):
    def fetch(query, variables):
        # GraphQL only returns city_string when the query selects it.
        selected = bool(re.search(r"\bcity_string\b", query))
        docs = [dict(doc) for doc in documents]
        if not selected:
            for doc in docs:
                doc.pop("city_string", None)
        return {"data": {"searchAPISearch": {"result_count": len(docs), "documents": docs}}}

    monkeypatch.setattr(coninsa, "_fetch_graphql", fetch)


def test_scrape_assigns_only_source_municipality(monkeypatch):
    outside = {**ENVIGADO, "code": "10000", "city_string": "BOGOTÁ"}
    commercial = {"code": "10001", "property_type": "Local"}
    _serve_documents(monkeypatch, [MEDELLIN, ENVIGADO, outside, commercial])

    medellin = coninsa.scrape(ciudad="medellín")
    envigado = coninsa.scrape(ciudad="enVigado")

    assert medellin == [{
        "id": "CON-97041", "portal": "coninsa", "tipo": "apartamento",
        "precio": 5500000, "area": 103, "habitaciones": 2, "banos": 2,
        "parqueaderos": 0, "estrato": 5, "barrio": "El Poblado",
        "url": "https://www.coninsa.co/inmuebles/apartamento-en-arriendo/el-poblado/medellin/97041",
    }]
    assert envigado == [{
        "id": "CON-97926", "portal": "coninsa", "tipo": "casa",
        "precio": 7000000, "area": 220, "habitaciones": 5, "banos": 4,
        "parqueaderos": 0, "estrato": 4, "barrio": "Mesa",
        "url": "https://www.coninsa.co/inmuebles/casa-en-arriendo/mesa/envigado/97926",
    }]


@pytest.mark.parametrize("city", [None, "", "  ", 449, []])
def test_scrape_rejects_missing_or_invalid_residential_city(monkeypatch, city):
    invalid = {**ENVIGADO, "city_string": city}
    _serve_documents(monkeypatch, [MEDELLIN, invalid])

    with pytest.raises(ValueError, match="Coninsa residential listing has missing or invalid city_string"):
        coninsa.scrape(ciudad="medellin")


def test_scrape_rejects_absent_residential_city(monkeypatch):
    invalid = {key: value for key, value in ENVIGADO.items() if key != "city_string"}
    _serve_documents(monkeypatch, [invalid])

    with pytest.raises(ValueError, match="Coninsa residential listing has missing or invalid city_string"):
        coninsa.scrape(ciudad="envigado")
