# -*- coding: utf-8 -*-
"""web/models.py - Database persistence for job history."""

from __future__ import annotations

import sqlite3
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from web.jobs import Job


def _get_db_path() -> str:
    base = Path(__file__).resolve().parent.parent / "instance" / "auto_report.db"
    return str(base)


def _connect():
    db = sqlite3.connect(_get_db_path())
    db.row_factory = sqlite3.Row
    return db


def save_job(job: Job):
    """Save a completed job and its results to SQLite."""
    db = _connect()
    try:
        db.execute(
            """INSERT OR REPLACE INTO jobs
               (id, freq, status, total, completed, errors, started_by, created_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job.id,
                job.freq,
                job.status.value,
                job.total,
                job.completed,
                job.errors,
                job.started_by,
                job.created_at.isoformat(),
                job.finished_at.isoformat() if job.finished_at else None,
            ),
        )
        for cr in job.clients.values():
            db.execute(
                """INSERT INTO job_results
                   (job_id, client_name, category, status, error_detail, presentation_url, started_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.id,
                    cr.nome,
                    cr.categoria,
                    cr.status,
                    cr.error,
                    cr.presentation_url,
                    cr.started_at.isoformat() if cr.started_at else None,
                    cr.finished_at.isoformat() if cr.finished_at else None,
                ),
            )
        db.commit()
    finally:
        db.close()


def get_job_history(page: int = 1, per_page: int = 20) -> list[dict]:
    """Return paginated job history with nested results."""
    db = _connect()
    try:
        offset = (page - 1) * per_page
        jobs = db.execute(
            """SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (per_page, offset),
        ).fetchall()

        result = []
        for j in jobs:
            job_dict = dict(j)
            results = db.execute(
                "SELECT * FROM job_results WHERE job_id = ? ORDER BY client_name",
                (j["id"],),
            ).fetchall()
            job_dict["results"] = [dict(r) for r in results]
            result.append(job_dict)
        return result
    finally:
        db.close()


def get_client_history(client_name: str, limit: int = 20) -> list[dict]:
    """Return generation history for a specific client."""
    db = _connect()
    try:
        rows = db.execute(
            """SELECT jr.*, j.freq, j.created_at as job_created_at
               FROM job_results jr
               JOIN jobs j ON jr.job_id = j.id
               WHERE jr.client_name = ?
               ORDER BY jr.started_at DESC
               LIMIT ?""",
            (client_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()
