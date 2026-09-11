"""Plan Phase-B enrichment reuse from a prior active listing snapshot."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from psycopg2 import Error as DatabaseError


@dataclass(frozen=True, slots=True)
class DetailReusePlan:
    """Rows that still need detail fetches and the resulting reuse counts."""

    detail_listings: list[dict]
    reused_count: int
    detail_fetch_count: int


def full_detail_plan(listings: list[dict]) -> DetailReusePlan:
    """Return the existing all-detail behavior as an explicit plan."""
    return DetailReusePlan(
        detail_listings=listings,
        reused_count=0,
        detail_fetch_count=sum(bool(row.get("url")) for row in listings),
    )


def plan_active_detail_reuse(
    listings: list[dict],
    portal: str,
    ciudad: str,
    detail_fields: tuple[str, ...],
) -> DetailReusePlan:
    """Plan reuse from the active DB snapshot or preserve full-detail fallback."""
    try:
        from db import get_active_listings_by_id

        previous_by_id = get_active_listings_by_id(portal, ciudad)
    except (DatabaseError, OSError, RuntimeError) as error:
        logging.getLogger(__name__).warning(
            "%s detail reuse unavailable; fetching all detail pages: %s",
            portal,
            error,
        )
        return full_detail_plan(listings)

    return plan_detail_reuse(listings, previous_by_id, detail_fields)


def plan_detail_reuse(
    listings: list[dict],
    previous_by_id: Mapping[str, Mapping[str, object]],
    detail_fields: tuple[str, ...],
) -> DetailReusePlan:
    """Reuse declared Phase-B fields when stable IDs have identical prices.

    The caller owns ``listings``. Matching rows are updated in place so their
    fresh Phase-A fields remain authoritative. A non-positive or non-integer
    price never matches: it must go through the existing detail-fetch path.
    """
    detail_listings: list[dict] = []
    reused_count = 0

    for listing in listings:
        listing_id = listing.get("id")
        current_price = _positive_integer_price(listing.get("precio"))
        previous = (
            previous_by_id.get(listing_id) if isinstance(listing_id, str) else None
        )
        previous_price = (
            _positive_integer_price(previous.get("precio")) if previous else None
        )

        if current_price is None or current_price != previous_price:
            detail_listings.append(listing)
            continue

        for field in detail_fields:
            value = previous.get(field)
            if value is not None:
                listing[field] = value
        reused_count += 1

    return DetailReusePlan(
        detail_listings=detail_listings,
        reused_count=reused_count,
        detail_fetch_count=sum(bool(row.get("url")) for row in detail_listings),
    )


def _positive_integer_price(value: object) -> int | None:
    """Return a valid price or ``None`` without coercing malformed values."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value
