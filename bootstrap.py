"""Prepare an empty Azure Database for PostgreSQL server for the demo, then seed it.

Steps: wait for connectivity, create the database, create the extensions, run the seed.
Safe to re-run (idempotent). Used by deploy.ps1; can also be run by hand:  python bootstrap.py
"""
from __future__ import annotations

import logging
import sys
import time

import psycopg
import psycopg.sql

from kgdb import ENV, connect
from seed import seed

logger = logging.getLogger(__name__)
EXTENSIONS = ("age", "btree_gist", "temporal_tables", "fuzzystrmatch", "pg_trgm")


def wait_for_server(attempts: int = 20, delay: int = 15) -> None:
    for i in range(1, attempts + 1):
        try:
            connect(dbname="postgres").close()
            return
        except psycopg.OperationalError as ex:
            logger.info("waiting for server (%d/%d): %s", i, attempts, str(ex).splitlines()[0][:90])
            time.sleep(delay)
    raise SystemExit(
        "Cannot connect to the server. Usually the firewall does not include this machine's egress address; "
        "run .\\allow-my-ip.ps1 (see README Troubleshooting)."
    )


def main() -> None:
    wait_for_server()
    db = ENV.get("PGDATABASE", "kgdemo")
    admin = connect(dbname="postgres")
    if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone():
        admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(db)))
        logger.info("created database %s", db)
    admin.close()

    conn = connect()
    for ext in EXTENSIONS:
        try:
            conn.execute(psycopg.sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(psycopg.sql.Identifier(ext)))
        except psycopg.Error as ex:
            raise SystemExit(
                f"Extension '{ext}' could not be created: {str(ex).splitlines()[0]}\n"
                "Check server parameters azure.extensions (must list AGE, BTREE_GIST, TEMPORAL_TABLES, FUZZYSTRMATCH, PG_TRGM) "
                "and shared_preload_libraries (must contain age), then restart the server."
            ) from ex
    versions = conn.execute("SELECT extname, extversion FROM pg_extension WHERE extname = ANY(%s) ORDER BY 1", (list(EXTENSIONS),)).fetchall()
    conn.close()
    logger.info("extensions: %s", {v["extname"]: v["extversion"] for v in versions})
    stats = seed(log=lambda m: logger.info(m))
    logger.info("seeded: %s", stats)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
    sys.exit(0)
