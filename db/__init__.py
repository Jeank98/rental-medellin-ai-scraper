import logging
import os
from contextlib import contextmanager

import psycopg2
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TABLE_NAME = "listings"

_DATABASE_URL = None


def _get_db_url() -> str:
    global _DATABASE_URL
    if _DATABASE_URL is None:
        _DATABASE_URL = os.getenv("DATABASE_URL")
        if not _DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set in .env file")
    return _DATABASE_URL

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id              TEXT PRIMARY KEY,
    portal          TEXT NOT NULL,
    tipo            TEXT NOT NULL DEFAULT '',
    precio          INTEGER NOT NULL DEFAULT 0,
    area            INTEGER NOT NULL DEFAULT 0,
    habitaciones    INTEGER NOT NULL DEFAULT 0,
    banos           INTEGER NOT NULL DEFAULT 0,
    parqueaderos    INTEGER NOT NULL DEFAULT 0,
    estrato         INTEGER NOT NULL DEFAULT 0,
    barrio          TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    ciudad          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active',
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

MIGRATE_STATUS_SQL = f"""
ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
CREATE INDEX IF NOT EXISTS idx_listings_portal_ciudad_status ON {TABLE_NAME} (portal, ciudad, status);
"""

INSERT_SQL = f"""
INSERT INTO {TABLE_NAME} (id, portal, tipo, precio, area, habitaciones, banos, parqueaderos, estrato, barrio, url, ciudad, status)
VALUES (%(id)s, %(portal)s, %(tipo)s, %(precio)s, %(area)s, %(habitaciones)s, %(banos)s, %(parqueaderos)s, %(estrato)s, %(barrio)s, %(url)s, %(ciudad)s, 'active')
ON CONFLICT (id) DO UPDATE SET
    portal = EXCLUDED.portal,
    tipo = EXCLUDED.tipo,
    precio = EXCLUDED.precio,
    area = EXCLUDED.area,
    habitaciones = EXCLUDED.habitaciones,
    banos = EXCLUDED.banos,
    parqueaderos = EXCLUDED.parqueaderos,
    estrato = EXCLUDED.estrato,
    barrio = EXCLUDED.barrio,
    url = EXCLUDED.url,
    ciudad = EXCLUDED.ciudad,
    status = 'active',
    scraped_at = NOW();
"""

DEACTIVATE_SQL = f"""
UPDATE {TABLE_NAME} SET status = 'inactive' WHERE portal = %(portal)s AND ciudad = %(ciudad)s AND status = 'active';
"""


@contextmanager
def get_conn():
    conn = psycopg2.connect(_get_db_url())
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass  # connection may already be closed; don't mask the original error
        raise
    finally:
        conn.close()


def create_tables():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            cur.execute(MIGRATE_STATUS_SQL)


def insert_listing(row: dict):
    required = ["id", "portal", "tipo", "precio", "area", "habitaciones",
                "banos", "parqueaderos", "estrato", "barrio", "url", "ciudad"]
    values = {k: row.get(k, "" if k in ("id", "portal", "tipo", "barrio", "url", "ciudad") else 0) for k in required}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, values)


def deactivate_listings(portal: str, ciudad: str):
    """Mark all active listings for a portal+city as inactive before a new scrape."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(DEACTIVATE_SQL, {"portal": portal, "ciudad": ciudad})


def insert_listings(rows: list[dict], ciudad: str = "") -> int:
    """Insert a complete portal batch atomically.

    Each row's INSERT runs inside a SAVEPOINT while errors are collected.
    Any invalid row aborts the outer transaction so the previous portal
    snapshot remains active.

    ``ciudad`` is the city for the WHOLE batch and is passed explicitly
    (not read from row dicts). Portal scrapers historically did not include
    ``ciudad`` in their row dicts — only the function-level param. Without
    this explicit arg, the deactivate-then-insert flow would store rows
    with ``ciudad=''`` (empty), making them invisible to ``--city medellin``
    filters in the export.

    Contract:
        * Rows whose ``id`` is ``None``, empty, or whitespace-only are
          reported as errors and abort the batch.
        * Rows that raise during INSERT are rolled back to their savepoint,
          reported, and abort the batch after inspection.
        * All rows are committed together in a single outer transaction. The
          function never partially-commits: either the whole batch succeeds
          or the whole batch is rolled back.
        * A summary log line is emitted on completion with the totals.

    Args:
        rows: List of listing dicts. Each row must contain at least:
            ``id``, ``portal``, ``tipo``, ``precio``, ``area``,
            ``habitaciones``, ``banos``, ``parqueaderos``, ``estrato``,
            ``barrio``, ``url``. Missing string fields default to ``''``;
            missing numeric fields default to ``0``.
        ciudad: City for the entire batch (e.g. ``'medellin'``). Defaults
            to ``''`` for backward compat but callers should always pass it.

    Note:
        Savepoint names are uniquified per row index (``row_sp_{i}``) so
        that a previous row's errored savepoint does not collide with the
        next row's. Per the SQL standard, ``ROLLBACK TO SAVEPOINT`` does
        not destroy the savepoint, so reusing a static name across rows
        would fail after the first error.
    """
    required = ["id", "portal", "tipo", "precio", "area", "habitaciones",
                "banos", "parqueaderos", "estrato", "barrio", "url", "ciudad"]
    inserted = 0
    skipped_empty_id = 0
    errored = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Deactivate existing listings for this portal+city first.
            # portal comes from the row dict (set by the scraper).
            # ciudad comes from the explicit arg (NOT from row dict — see
            # docstring).
            if rows:
                portal = rows[0].get("portal", "")
                if portal and ciudad:
                    cur.execute(DEACTIVATE_SQL, {"portal": portal, "ciudad": ciudad})

            for i, row in enumerate(rows):
                row_id = (row.get("id") or "").strip()
                if not row_id:
                    logger.warning(
                        "Skipping row with empty ID: url=%s",
                        row.get("url") or "<no url>",
                    )
                    skipped_empty_id += 1
                    continue

                values = {
                    k: row.get(k, "" if k in ("id", "portal", "tipo", "barrio", "url") else 0)
                    for k in required
                }
                # Always override ciudad with the explicit arg.
                values["ciudad"] = ciudad
                sp_name = f"row_sp_{i}"
                cur.execute(f"SAVEPOINT {sp_name}")
                try:
                    cur.execute(INSERT_SQL, values)
                except Exception as e:
                    cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                    logger.warning(
                        "Skipping row %s due to error: %s", row_id, e,
                    )
                    errored += 1
                else:
                    cur.execute(f"RELEASE SAVEPOINT {sp_name}")
                    inserted += 1

            if skipped_empty_id or errored:
                raise RuntimeError(
                    f"batch rejected: {skipped_empty_id} empty IDs, {errored} row errors"
                )

    logger.info(
        "insert_listings done: %d total, %d inserted, %d skipped (empty id), %d errored (ciudad=%r)",
        len(rows), inserted, skipped_empty_id, errored, ciudad,
    )
    return inserted


def test_connection() -> bool:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False


def get_count() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
            return cur.fetchone()[0]


def get_all() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {TABLE_NAME} ORDER BY scraped_at DESC")
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
