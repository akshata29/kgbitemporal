"""Connection helpers for the entity-governance bitemporal KG demo.

Settings come from environment variables (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD),
overridden by a local .env file written by deploy.ps1.

Every connection needs ag_catalog on the search_path so the cypher() function resolves.
LOAD 'age' is NOT allowed on Azure Database for PostgreSQL (it is preloaded through
shared_preload_libraries), so we never issue it.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

GRAPH = "entity_graph"
ENV: dict[str, str] = {k: v for k, v in os.environ.items() if k.startswith("PG")}
ENV.update({k: v for k, v in dotenv_values(Path(__file__).parent / ".env").items() if v is not None})


def conninfo(dbname: str | None = None) -> str:
    return make_conninfo(
        host=ENV["PGHOST"], port=ENV.get("PGPORT", "5432"), dbname=dbname or ENV.get("PGDATABASE", "kgdemo"),
        user=ENV["PGUSER"], password=ENV["PGPASSWORD"], sslmode=ENV.get("PGSSLMODE", "require"), connect_timeout="20",
    )


def configure(conn: psycopg.Connection) -> None:
    conn.execute("SET search_path = public, ag_catalog")


def connect(autocommit: bool = True, dbname: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(conninfo(dbname), autocommit=autocommit, row_factory=dict_row)
    configure(conn)
    return conn
