"""DB writer — thin wrapper around db/__init__.py for portal scraper scripts."""

import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path for importing the db package
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from db import create_tables, deactivate_listings, insert_listings

logger = logging.getLogger(__name__)


def write_to_db(rows: list[dict], portal: str, ciudad: str = "medellin") -> int:
    """Insert listings into the database.

    Calls create_tables → deactivate_listings → insert_listings in order.

    Args:
        rows: List of listing dicts matching the 11-column spec.
        portal: Portal identifier (e.g. 'alnago').
        ciudad: City name (default 'medellin').

    Returns:
        Number of rows inserted. Returns 0 if rows is empty or on error.
    """
    if not rows:
        return 0

    try:
        create_tables()
        deactivate_listings(portal, ciudad)
        insert_listings(rows)
        logger.info("Deactivated old %s listings, inserted %d new ones", portal, len(rows))
        return len(rows)
    except Exception as e:
        logger.error("DB write failed for %s: %s", portal, e)
        return 0
