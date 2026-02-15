# -*- coding: utf-8 -*-
"""web/jobs.py - Background job manager for report generation."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    PENDING = "PENDENTE"
    RUNNING = "EM EXECUCAO"
    COMPLETED = "CONCLUIDO"
    FAILED = "ERRO"
    CANCELLED = "CANCELADO"


@dataclass
class ClientResult:
    nome: str
    categoria: str = ""
    status: str = "PENDENTE"
    error: Optional[str] = None
    presentation_url: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "nome": self.nome,
            "categoria": self.categoria,
            "status": self.status,
            "error": self.error,
            "presentation_url": self.presentation_url,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


@dataclass
class Job:
    id: str
    freq: str
    started_by: str = ""
    status: JobStatus = JobStatus.PENDING
    clients: dict[str, ClientResult] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    total: int = 0
    completed: int = 0
    errors: int = 0
    _cancelled: bool = field(default=False, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "freq": self.freq,
            "status": self.status.value,
            "started_by": self.started_by,
            "total": self.total,
            "completed": self.completed,
            "errors": self.errors,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "clients": {k: v.to_dict() for k, v in self.clients.items()},
        }


# In-memory job store
_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def get_job(job_id: str) -> Optional[Job]:
    with _jobs_lock:
        return _jobs.get(job_id)


def get_all_jobs() -> list[dict]:
    with _jobs_lock:
        return [j.to_dict() for j in sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)]


def cancel_job(job_id: str) -> bool:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job or job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            return False
        job._cancelled = True
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.now()
    return True


def start_generation_job(client_names: list[str], freq: str, started_by: str = "") -> str:
    """Start a background job for selected clients."""
    job_id = str(uuid.uuid4())[:8]
    job = Job(id=job_id, freq=freq, started_by=started_by)

    with _jobs_lock:
        _jobs[job_id] = job

    thread = threading.Thread(
        target=_run_job, args=(job, freq, client_names), daemon=True
    )
    thread.start()
    return job_id


def start_generation_all(freq: str, started_by: str = "") -> str:
    """Start a background job for all eligible clients."""
    return start_generation_job(client_names=[], freq=freq, started_by=started_by)


def _run_job(job: Job, freq: str, client_names: list[str]):
    """Execute report generation in a background thread."""
    from web.api import broadcast_event

    try:
        from core.leitura_central import fetch_clientes
        from config import settings
        from core import relatorio_writer
        from report_generator import processar_cliente_threadsafe

        job.status = JobStatus.RUNNING
        broadcast_event("job_status", {"job_id": job.id, "status": job.status.value})

        # Use atualizar=False to get ALL clients (the web UI decides which to generate,
        # not the GERAR? column in the spreadsheet)
        all_clients = fetch_clientes(
            atualizar=False,
            only=None,
            sheet_url=settings.CENTRAL_SHEET_URL,
            tab_name=settings.CENTRAL_TAB_NAME,
        )

        # Filter if specific clients requested
        if client_names:
            selected = [c for c in all_clients if c.nome in client_names]
        else:
            selected = all_clients

        if not selected:
            job.status = JobStatus.COMPLETED
            job.finished_at = datetime.now()
            _save_job_to_db(job)
            broadcast_event("job_complete", {
                "job_id": job.id,
                "status": job.status.value,
                "completed": 0,
                "errors": 0,
                "message": "Nenhum cliente elegivel encontrado.",
            })
            return

        job.total = len(selected)
        for c in selected:
            job.clients[c.nome] = ClientResult(nome=c.nome, categoria=c.categoria)

        broadcast_event("job_update", {
            "job_id": job.id,
            "total": job.total,
            "clients": {k: v.to_dict() for k, v in job.clients.items()},
        })

        # Create tracking spreadsheet
        ss_id = relatorio_writer.criar_planilha_relatorio()
        relatorio_writer.set_planilha_id(ss_id)

        max_threads = int(os.getenv("THREADS", "4"))
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            future_to_client = {}
            for cliente in selected:
                if job._cancelled:
                    break
                job.clients[cliente.nome].status = "PROCESSANDO"
                job.clients[cliente.nome].started_at = datetime.now()
                future_to_client[
                    executor.submit(processar_cliente_threadsafe, cliente, freq)
                ] = cliente

            for future in as_completed(future_to_client):
                if job._cancelled:
                    break
                cliente = future_to_client[future]
                try:
                    nome, result_status = future.result()
                    cr = job.clients[nome]
                    cr.status = result_status
                    cr.finished_at = datetime.now()
                    # Capture presentation link if generated
                    pres_id = cliente.extras.get("_presentation_id")
                    if pres_id:
                        cr.presentation_url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
                    if "ERRO" in result_status or "EXCEPTION" in result_status:
                        job.errors += 1
                        cr.error = result_status
                    job.completed += 1
                except Exception as exc:
                    cr = job.clients[cliente.nome]
                    cr.status = f"EXCEPTION: {type(exc).__name__}"
                    cr.error = str(exc)
                    cr.finished_at = datetime.now()
                    job.completed += 1
                    job.errors += 1

                broadcast_event("client_status", {
                    "job_id": job.id,
                    "client": cliente.nome,
                    "status": job.clients[cliente.nome].status,
                    "presentation_url": job.clients[cliente.nome].presentation_url,
                    "completed": job.completed,
                    "total": job.total,
                    "errors": job.errors,
                })

        if not job._cancelled:
            job.status = JobStatus.COMPLETED if job.errors == 0 else JobStatus.FAILED
        job.finished_at = datetime.now()

        # Persist to SQLite
        _save_job_to_db(job)

        broadcast_event("job_complete", {
            "job_id": job.id,
            "status": job.status.value,
            "completed": job.completed,
            "total": job.total,
            "errors": job.errors,
        })

    except Exception as exc:
        import traceback
        print(f"[JOB ERROR] {traceback.format_exc()}")
        job.status = JobStatus.FAILED
        job.finished_at = datetime.now()
        _save_job_to_db(job)
        broadcast_event("job_complete", {
            "job_id": job.id,
            "status": "ERRO",
            "error": str(exc),
            "completed": job.completed,
            "total": job.total,
            "errors": job.errors,
        })


def _save_job_to_db(job: Job):
    """Persist job results to SQLite history."""
    try:
        from web.models import save_job
        save_job(job)
    except Exception as exc:
        print(f"[DB SAVE ERROR] {exc}")
