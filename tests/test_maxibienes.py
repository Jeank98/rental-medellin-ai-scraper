"""Consumer regressions for Maxibienes pagination."""

import re

import pytest

from scrape import maxibienes


def _page(page: int, total: int) -> str:
    return f"""
    <script>var totalpagina = 12; </script>
    <script>var totalInmuebles = {total}; </script>
    <div class="grid-style1"><div class="item">
      <h3>APARTAMENTO<br>Estrato: 3</h3>
      <div class="image"><a href="/inmueble/{page}"></a><span class="location">Laureles</span></div>
      <div class="price"><span>$ 1.450.000</span></div>
      <ul class="amenities"><li>Código: {page}</li></ul>
    </div></div>
    """


@pytest.mark.parametrize(
    ("city", "total", "pages"),
    [("medellin", 972, 81), ("envigado", 204, 17), ("itagui", 174, 15),
     ("sabaneta", 226, 19), ("la estrella", 84, 7)],
)
def test_scrape_retains_all_paginated_listings(monkeypatch, city, total, pages):
    def fetch(url):
        match = re.search(r"/pagina/(\d+)\?", url)
        return _page(int(match.group(1)) if match else 1, total)

    monkeypatch.setattr(maxibienes, "fetch_page", fetch)
    rows = maxibienes.scrape(ciudad=city)

    assert [row["id"] for row in rows] == [f"MXB-{page}" for page in range(1, pages + 1)]
    assert rows[-1]["precio"] == 1450000


@pytest.mark.parametrize(
    ("options", "pages"),
    [({"sample_only": True}, 3), ({"max_pages": 4}, 4),
     ({"sample_only": True, "max_pages": 4}, 4)],
)
def test_scrape_preserves_page_limits(monkeypatch, options, pages):
    def fetch(url):
        match = re.search(r"/pagina/(\d+)\?", url)
        return _page(int(match.group(1)) if match else 1, 972)

    monkeypatch.setattr(maxibienes, "fetch_page", fetch)
    rows = maxibienes.scrape(**options)

    assert [row["id"] for row in rows] == [f"MXB-{page}" for page in range(1, pages + 1)]


@pytest.mark.parametrize("metadata", [
    "var totalpagina = 12;",
    "var totalInmuebles = 13;",
    "var totalpagina = 0; var totalInmuebles = 13;",
    "var totalpagina = -12; var totalInmuebles = 13;",
    "var totalpagina = 12.5; var totalInmuebles = 13;",
    "var totalpagina = 12; var totalInmuebles = -1;",
    "var totalpagina = 12; var totalInmuebles = 13.5;",
    "var totalpagina = 12; var totalInmuebles = '13';",
])
def test_scrape_rejects_invalid_pagination_metadata(monkeypatch, metadata):
    monkeypatch.setattr(maxibienes, "fetch_page", lambda url: f"<script>{metadata}</script>")
    with pytest.raises(ValueError, match="Maxibienes.*pagination"):
        maxibienes.scrape()


def test_scrape_returns_no_listings_for_zero_inventory(monkeypatch):
    monkeypatch.setattr(
        maxibienes, "fetch_page",
        lambda url: "<script>var totalpagina = 12; var totalInmuebles = 0;</script>",
    )
    assert maxibienes.scrape() == []
