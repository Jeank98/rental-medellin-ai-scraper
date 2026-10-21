"""Municipality mappings for the metro-capable adapters."""

import pytest

from scrape import arangotobon, coninsa, lapalma, maxibienes, panoramainmobiliario, totalbienes, zitios


def test_maxibienes_uses_the_site_city_ids() -> None:
    assert "ciudad=5001" in maxibienes._page_url(1, "medellin")
    assert "ciudad=5266" in maxibienes._page_url(1, "Envigado")
    assert "ciudad=5360" in maxibienes._page_url(2, "Itagüí")
    assert "ciudad=5631" in maxibienes._page_url(1, "sabaneta")
    assert "ciudad=5380" in maxibienes._page_url(1, "La Estrella")
    with pytest.raises(maxibienes.UnsupportedCityError):
        maxibienes._page_url(1, "bogota")


def test_panorama_and_lapalma_share_the_platform_city_ids() -> None:
    for ciudad, city_id in (
        ("medellin", "496"),
        ("envigado", "291"),
        ("itagui", "389"),
        ("La Estrella", "416"),
        ("sabaneta", "698"),
    ):
        assert f"id_city={city_id}" in panoramainmobiliario.build_page_url(1, ciudad, "apartamento")
        assert f"id_city={city_id}" in lapalma.build_page_url(1, ciudad, "apartamento")

    with pytest.raises(panoramainmobiliario.UnsupportedCityError):
        panoramainmobiliario.build_page_url(1, "bogota", "apartamento")
    with pytest.raises(lapalma.UnsupportedCityError):
        lapalma.build_page_url(1, "bogota", "apartamento")


def test_coninsa_maps_municipalities_to_fulltext_names() -> None:
    assert coninsa._city_name("medellin") == "Medellin"
    assert coninsa._city_name("Itagüí") == "Itagui"
    assert coninsa._city_name("La Estrella") == "La Estrella"
    with pytest.raises(ValueError):
        coninsa._city_name("bogota")


def test_totalbienes_only_has_verified_routes_for_medellin_and_itagui() -> None:
    medellin_urls = totalbienes._source_urls(False, None, "medellin")
    assert all("medellin" in url for url in medellin_urls)
    itagui_urls = totalbienes._source_urls(False, None, "Itagüí")
    assert all("itagui" in url for url in itagui_urls)
    with pytest.raises(ValueError):
        totalbienes._source_urls(False, None, "envigado")


def test_reference_maps_keep_their_verified_entries() -> None:
    assert arangotobon.build_page_url(1, "envigado").endswith("municipio=envigado")
    assert "/c/sabaneta/" in zitios._page_url(1, "apartamentos", "sabaneta")
