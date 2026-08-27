"""Scrape package — shared utilities for Colombian real estate portal scrapers.

Provides fetcher, normalizer, validator, and output writer functions
that are used by thin CLI scripts in scripts/ and per-portal modules.
"""

from importlib import import_module


# Keep the package import lightweight.  Portal modules can import ``scrape``
# while their optional HTTP/database dependencies are unavailable; resolving
# an export only imports the module that owns it.
_EXPORT_MODULES = {
    "fetch_page": ("scrape.fetcher", "fetch_page"),
    "fetch_json": ("scrape.fetcher", "fetch_json"),
    "bulk_fetch": ("scrape.fetcher", "bulk_fetch"),
    "normalize_price": ("scrape.normalize", "normalize_price"),
    "normalize_tipo": ("scrape.normalize", "normalize_tipo"),
    "normalize_estrato": ("scrape.normalize", "normalize_estrato"),
    "normalize_garaje": ("scrape.normalize", "normalize_garaje"),
    "normalize_barrio": ("scrape.normalize", "normalize_barrio"),
    "normalize_url": ("scrape.normalize", "normalize_url"),
    "TIPO_MAPPING": ("scrape.normalize", "TIPO_MAPPING"),
    "validate": ("scrape.validator", "validate"),
    "write_to_db": ("scrape.db_writer", "write_to_db"),
    "write_to_csv": ("scrape.csv_writer", "write_to_csv"),
    "create_parser": ("scrape.cli", "create_parser"),
    "run_scraper": ("scrape.cli", "run_scraper"),
}


def __getattr__(name: str):
    """Resolve a public export lazily on first access."""
    try:
        module_name, attribute_name = _EXPORT_MODULES[name]
    except KeyError as error:
        raise AttributeError(f"module 'scrape' has no attribute {name!r}") from error
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include lazy public exports in interactive/module introspection."""
    return sorted(set(globals()) | set(__all__))

__all__ = [
    "fetch_page",
    "fetch_json",
    "bulk_fetch",
    "normalize_price",
    "normalize_tipo",
    "normalize_estrato",
    "normalize_garaje",
    "normalize_barrio",
    "normalize_url",
    "TIPO_MAPPING",
    "validate",
    "write_to_db",
    "write_to_csv",
    "create_parser",
    "run_scraper",
]
