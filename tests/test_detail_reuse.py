"""Regression tests for price-stable Phase-B detail reuse."""

from unittest import mock

from db import ACTIVE_LISTINGS_BY_ID_SQL, get_active_listings_by_id
from scrape.detail_reuse import plan_detail_reuse


def _listing(listing_id: str, price: int, *, url: str | None = None) -> dict:
    return {
        "id": listing_id,
        "portal": "arrendamientossantafe",
        "tipo": "apartamento",
        "precio": price,
        "area": 55,
        "habitaciones": 2,
        "banos": 0,
        "parqueaderos": 1,
        "estrato": 0,
        "barrio": "Laureles",
        "url": url or f"https://example.test/{listing_id}",
    }


def test_reuses_only_declared_detail_fields_for_unchanged_price() -> None:
    unchanged = _listing("ASF-1", 1_500_000)
    changed = _listing("ASF-2", 1_600_000)
    new = _listing("ASF-3", 1_700_000)
    zero_price = _listing("ASF-4", 0)
    previous = {
        "ASF-1": {
            **_listing("ASF-1", 1_500_000),
            "area": 999,
            "banos": 2,
            "estrato": 5,
        },
        "ASF-2": {**_listing("ASF-2", 1_500_000), "banos": 3, "estrato": 4},
        "ASF-4": {**_listing("ASF-4", 0), "banos": 1, "estrato": 2},
    }

    plan = plan_detail_reuse(
        [unchanged, changed, new, zero_price],
        previous,
        ("banos", "estrato"),
    )

    assert unchanged["banos"] == 2
    assert unchanged["estrato"] == 5
    assert unchanged["area"] == 55
    assert [row["id"] for row in plan.detail_listings] == [
        "ASF-2",
        "ASF-3",
        "ASF-4",
    ]
    assert plan.reused_count == 1
    assert plan.detail_fetch_count == 3


def test_reuses_genuine_zero_detail_values() -> None:
    listing = _listing("ASF-1", 1_500_000)
    previous = {"ASF-1": {**_listing("ASF-1", 1_500_000), "banos": 0, "estrato": 0}}

    plan = plan_detail_reuse([listing], previous, ("banos", "estrato"))

    assert listing["banos"] == 0
    assert listing["estrato"] == 0
    assert plan.reused_count == 1
    assert plan.detail_fetch_count == 0


def test_malformed_price_never_matches_a_cached_row() -> None:
    listing = _listing("ASF-1", 1_500_000)
    listing["precio"] = "1500000"
    previous = {"ASF-1": _listing("ASF-1", 1_500_000)}

    plan = plan_detail_reuse([listing], previous, ("banos", "estrato"))

    assert plan.reused_count == 0
    assert plan.detail_listings == [listing]


def test_active_snapshot_lookup_filters_by_portal_city_and_status() -> None:
    connection = mock.MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        (
            "ASF-1",
            "arrendamientossantafe",
            "apartamento",
            1_500_000,
            55,
            2,
            1,
            1,
            4,
            "Laureles",
            "https://example.test/ASF-1",
        )
    ]

    with mock.patch("db.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = connection
        rows = get_active_listings_by_id("arrendamientossantafe", "medellin")

    cursor.execute.assert_called_once_with(
        ACTIVE_LISTINGS_BY_ID_SQL,
        {"portal": "arrendamientossantafe", "ciudad": "medellin"},
    )
    assert rows["ASF-1"]["precio"] == 1_500_000
