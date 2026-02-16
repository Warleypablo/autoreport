# -*- coding: utf-8 -*-
"""web/pg_db.py - PostgreSQL database helpers (replaces SQLite db.py)."""

import os
from pathlib import Path

import psycopg2
import psycopg2.extras
from flask import g, current_app
from werkzeug.security import generate_password_hash

_SCHEMA_PATH = Path(__file__).parent / "pg_schema.sql"


def _pg_dsn() -> dict:
    """Build connection kwargs from env / settings."""
    from config import settings
    return {
        "host": getattr(settings, "PG_HOST", os.getenv("PG_HOST", "127.0.0.1")),
        "port": getattr(settings, "PG_PORT", int(os.getenv("PG_PORT", "5432"))),
        "dbname": getattr(settings, "PG_DBNAME", os.getenv("PG_DBNAME", "dados_turbo")),
        "user": getattr(settings, "PG_USER", os.getenv("PG_USER", "postgres")),
        "password": getattr(settings, "PG_PASSWORD", os.getenv("PG_PASSWORD", "")),
    }


def _pg_schema() -> str:
    from config import settings
    return getattr(settings, "PG_SCHEMA", os.getenv("PG_SCHEMA", "autoreport"))


def get_pg_conn():
    """Return a psycopg2 connection stored in Flask's g object."""
    if "pg_conn" not in g:
        conn = psycopg2.connect(**_pg_dsn())
        conn.set_session(autocommit=False)
        schema = _pg_schema()
        cur = conn.cursor()
        cur.execute(f"SET search_path TO {schema}, public")
        cur.close()
        g.pg_conn = conn
    return g.pg_conn


def close_pg_conn(_exc=None):
    """Close PG connection on teardown."""
    conn = g.pop("pg_conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def get_standalone_conn():
    """Get a standalone PG connection (for use outside Flask context, e.g. in threads)."""
    conn = psycopg2.connect(**_pg_dsn())
    conn.set_session(autocommit=False)
    schema = _pg_schema()
    cur = conn.cursor()
    cur.execute(f"SET search_path TO {schema}, public")
    cur.close()
    return conn


def init_pg_db(app):
    """Run pg_schema.sql to create tables and seed admin user."""
    try:
        dsn = _pg_dsn()
        conn = psycopg2.connect(**dsn)
        conn.set_session(autocommit=True)
        try:
            cur = conn.cursor()
            with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
                cur.execute(f.read())

            schema = _pg_schema()
            cur.execute(f"SET search_path TO {schema}, public")

            # Seed admin user if not exists
            cur.execute("SELECT id FROM users WHERE username = %s", ("admin",))
            if not cur.fetchone():
                password = os.getenv("ADMIN_PASSWORD", "admin")
                cur.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                    ("admin", generate_password_hash(password)),
                )
            cur.close()
        finally:
            conn.close()
    except Exception as exc:
        print(f"[WARN] PostgreSQL init failed: {exc}")
        print("[WARN] App will start but DB features may be unavailable until PG is reachable.")
