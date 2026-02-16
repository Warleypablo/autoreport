# -*- coding: utf-8 -*-
"""web/models.py - Database persistence for job history (PostgreSQL)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg2.extras

if TYPE_CHECKING:
    from web.jobs import Job


def _connect():
    """Get a standalone PG connection for background threads."""
    from web.pg_db import get_standalone_conn
    return get_standalone_conn()


def save_job(job: Job):
    """Save a completed job and its results to PostgreSQL."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO jobs (id, freq, status, total, completed, errors,
                                 started_by, created_at, finished_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET
                   status = EXCLUDED.status,
                   total = EXCLUDED.total,
                   completed = EXCLUDED.completed,
                   errors = EXCLUDED.errors,
                   finished_at = EXCLUDED.finished_at""",
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
            cur.execute(
                """INSERT INTO job_results
                   (job_id, client_name, category, status, error_detail,
                    presentation_url, started_at, finished_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
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
        conn.commit()
    finally:
        conn.close()


def get_job_history(page: int = 1, per_page: int = 20) -> list[dict]:
    """Return paginated job history with nested results."""
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        offset = (page - 1) * per_page
        cur.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (per_page, offset),
        )
        jobs = cur.fetchall()

        result = []
        for j in jobs:
            job_dict = dict(j)
            cur.execute(
                "SELECT * FROM job_results WHERE job_id = %s ORDER BY client_name",
                (j["id"],),
            )
            job_dict["results"] = [dict(r) for r in cur.fetchall()]
            result.append(job_dict)
        return result
    finally:
        conn.close()


def get_client_history(client_name: str, limit: int = 20) -> list[dict]:
    """Return generation history for a specific client."""
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT jr.*, j.freq, j.created_at as job_created_at
               FROM job_results jr
               JOIN jobs j ON jr.job_id = j.id
               WHERE jr.client_name = %s
               ORDER BY jr.started_at DESC
               LIMIT %s""",
            (client_name, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
