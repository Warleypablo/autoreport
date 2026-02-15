# -*- coding: utf-8 -*-
"""web/db.py - SQLite database helpers."""

import os
import sqlite3
from pathlib import Path

from flask import g, current_app
from werkzeug.security import generate_password_hash


_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    db_path = app.config["DATABASE"]
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        db.executescript(f.read())
    # Seed admin user if not exists
    existing = db.execute(
        "SELECT id FROM users WHERE username = ?", ("admin",)
    ).fetchone()
    if not existing:
        password = os.getenv("ADMIN_PASSWORD", "admin")
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("admin", generate_password_hash(password)),
        )
        db.commit()
    db.close()
