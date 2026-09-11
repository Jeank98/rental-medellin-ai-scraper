"""Plan Phase-B enrichment reuse from a prior active listing snapshot."""

import logging
from collections.abc import Callable, Mapping
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
    preserve_current_fields: frozenset[str] = frozenset(),
    prior_detail_evidence: Callable[[Mapping[str, object]], bool] | None = None,
    is_reusable_detail_value: Callable[[str, object], bool] | None = None,
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

    return plan_detail_reuse(
        listings,
        previous_by_id,
        detail_fields,
        preserve_current_fields,
        prior_detail_evidence,
        is_reusable_detail_value,
    )


def plan_active_detail_reuse_by_url(
    listings: list[dict],
    portal: str,
    ciudad: str,
    detail_fields: tuple[str, ...],
    preserve_current_fields: frozenset[str] = frozenset(),
) -> DetailReusePlan:
    """Plan reuse from the active snapshot by unambiguous stable URL + price."""
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

    return plan_detail_reuse_by_url(
        listings,
        previous_by_id,
        detail_fields,
        preserve_current_fields,
    )


def plan_detail_reuse(
    listings: list[dict],
    previous_by_id: Mapping[str, Mapping[str, object]],
    detail_fields: tuple[str, ...],
    preserve_current_fields: frozenset[str] = frozenset(),
    prior_detail_evidence: Callable[[Mapping[str, object]], bool] | None = None,
    is_reusable_detail_value: Callable[[str, object], bool] | None = None,
) -> DetailReusePlan:
    """Reuse declared Phase-B fields when stable IDs have identical prices."""
    return _plan_detail_reuse(
        listings,
        previous_by_id,
        detail_fields,
        preserve_current_fields,
        _stable_id,
        prior_detail_evidence,
        is_reusable_detail_value,
    )


def plan_detail_reuse_by_url(
    listings: list[dict],
    previous_by_id: Mapping[str, Mapping[str, object]],
    detail_fields: tuple[str, ...],
    preserve_current_fields: frozenset[str] = frozenset(),
) -> DetailReusePlan:
    """Reuse declared Phase-B fields when one prior row has the same URL + price."""
    return _plan_detail_reuse(
        listings,
        _unique_rows_by_url(previous_by_id),
        detail_fields,
        preserve_current_fields,
        _stable_url,
    )


def _plan_detail_reuse(
    listings: list[dict],
    previous_by_key: Mapping[str, Mapping[str, object]],
    detail_fields: tuple[str, ...],
    preserve_current_fields: frozenset[str],
    key_for: Callable[[Mapping[str, object]], str | None],
    prior_detail_evidence: Callable[[Mapping[str, object]], bool] | None = None,
    is_reusable_detail_value: Callable[[str, object], bool] | None = None,
) -> DetailReusePlan:
    """Copy declared fields for rows whose stable key and positive price match."""
    detail_listings: list[dict] = []
    reused_count = 0

    for listing in listings:
        key = key_for(listing)
        current_price = _positive_integer_price(listing.get("precio"))
        previous = previous_by_key.get(key) if key else None
        previous_price = (
            _positive_integer_price(previous.get("precio")) if previous else None
        )

        if (
            current_price is None
            or current_price != previous_price
            or (
                prior_detail_evidence is not None
                and (previous is None or not prior_detail_evidence(previous))
            )
        ):
            detail_listings.append(listing)
            continue

        for field in detail_fields:
            if (
                field in preserve_current_fields
                and not _is_missing_detail_field(listing.get(field))
            ):
                continue
            value = previous.get(field)
            if value is not None and (
                is_reusable_detail_value is None
                or is_reusable_detail_value(field, value)
            ):
                listing[field] = value
        reused_count += 1

    return DetailReusePlan(
        detail_listings=detail_listings,
        reused_count=reused_count,
        detail_fetch_count=sum(bool(row.get("url")) for row in detail_listings),
    )


def _stable_id(row: Mapping[str, object]) -> str | None:
    value = row.get("id")
    return value if isinstance(value, str) and value else None


def _stable_url(row: Mapping[str, object]) -> str | None:
    value = row.get("url")
    if not isinstance(value, str):
        return None
    return value.rstrip("/") or None


def _unique_rows_by_url(
    previous_by_id: Mapping[str, Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    rows_by_url: dict[str, Mapping[str, object]] = {}
    ambiguous_urls: set[str] = set()

    for row in previous_by_id.values():
        url = _stable_url(row)
        if url is None or url in ambiguous_urls:
            continue
        if url in rows_by_url:
            rows_by_url.pop(url)
            ambiguous_urls.add(url)
            continue
        rows_by_url[url] = row

    return rows_by_url


def _is_missing_detail_field(value: object) -> bool:
    """Match Phase-B's zero-or-empty convention for optional fields."""
    return value is None or value == "" or value == 0


def _positive_integer_price(value: object) -> int | None:
    """Return a valid price or ``None`` without coercing malformed values."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value
