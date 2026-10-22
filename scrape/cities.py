"""Canonical city identifiers for the south-of-Medellin rental portals.

The database stores one snapshot per ``portal + ciudad`` pair, so every CLI and
multi-city runner must agree on the exact city key before writing.  The keys
below are the storage scopes already used by ``insert_listings``; :data:`CITY_LABELS`
maps them to the label shown to operators.  ``la-estrella`` keeps the existing
hyphenated storage key so this work never creates a duplicate city scope.

``normalize_city`` is deliberately permissive: scrapers use it to inspect the
source municipality of an individual record, which may legitimately be outside
the supported list.  ``resolve_city`` is the strict gate for anything that
selects or scopes stored data.
"""

import re
import unicodedata

__all__ = ["CITY_LABELS", "normalize_city", "resolve_city"]

CITY_LABELS: dict[str, str] = {
    "medellin": "Medellín",
    "envigado": "Envigado",
    "itagui": "Itagüí",
    "la-estrella": "La Estrella",
    "sabaneta": "Sabaneta",
}

_MULTIWORD_SEPARATOR = re.compile(r"[\s_-]+")


def normalize_city(value: str) -> str:
    """Return the accent-free, lower-case, hyphen-joined form of ``value``.

    Whitespace, underscores, and hyphens all collapse into a single hyphen so
    that ``La Estrella``, ``la_estrella`` and ``LA-ESTRELLA`` share the existing
    storage key ``la-estrella``.  The result is not validated against
    :data:`CITY_LABELS`; callers that need a supported city use
    :func:`resolve_city`.
    """
    if not isinstance(value, str):
        raise TypeError(f"city must be a string, got {type(value).__name__}")
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return _MULTIWORD_SEPARATOR.sub("-", without_accents.casefold()).strip("-")


def resolve_city(value: str) -> str:
    """Return the canonical :data:`CITY_LABELS` key for ``value``.

    Raises:
        ValueError: when the normalized value is blank or not a supported city.
    """
    key = normalize_city(value)
    if key not in CITY_LABELS:
        raise ValueError(f"unsupported city: {value!r}")
    return key
