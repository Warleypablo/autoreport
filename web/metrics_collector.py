# -*- coding: utf-8 -*-
"""web/metrics_collector.py - Collect metrics from APIs without generating reports."""

from __future__ import annotations

import threading
from datetime import date
from typing import List

from utils.logger import get_logger

log = get_logger(__name__)


def _build_cliente_from_row(row: dict):
    """Build a Cliente dataclass from a PG clientes row."""
    from core.leitura_central import Cliente

    return Cliente(
        nome=row.get("nome") or "",
        categoria=row.get("categoria") or "",
        painel_url=row.get("painel_url") or "",
        pasta_url=row.get("pasta_url") or "",
        id_google_ads=row.get("id_google_ads") or "",
        id_meta_ads=row.get("id_meta_ads") or "",
        id_ga4=row.get("id_ga4") or "",
        extras=row.get("extras") or {},
    )


def _collect_for_client(cliente, freq: str) -> dict:
    """Collect metrics for a single client and save to PG.

    Returns {"client": nome, "status": "ok"/"error", "detail": ...}
    """
    from core.periodo import periodo_referencia
    from core.categorias import get_handler
    from core.basic_placeholders import montar_placeholders_basicos
    from web.metrics_store import save_metrics_snapshot

    try:
        periodo_ref = periodo_referencia(today=date.today(), frequencia=freq)
        periodo_comp = periodo_referencia(today=periodo_ref.inicio, frequencia=freq)

        dados = montar_placeholders_basicos(cliente, periodo_ref, FREQ=freq)
        dados.update(
            montar_placeholders_basicos(
                cliente, periodo_comp, FREQ=freq, sufixo="_comp"
            )
        )

        handler = get_handler(cliente.categoria)
        dados.update(handler.coletar_dados(cliente, periodo_ref, periodo_comp))

        save_metrics_snapshot(cliente, dados, periodo_ref, freq)

        log.info("Metricas coletadas para %s", cliente.nome)
        return {"client": cliente.nome, "status": "ok"}
    except Exception as exc:
        log.warning("Erro ao coletar metricas de %s: %s", cliente.nome, exc)
        return {"client": cliente.nome, "status": "error", "detail": str(exc)}


def collect_metrics_for_gestor(
    gestor_name: str,
    freq: str = "SEMANAL",
    progress_callback=None,
):
    """Collect metrics for all clients of a gestor.

    Args:
        gestor_name: Name of the gestor
        freq: "SEMANAL" or "MENSAL"
        progress_callback: Optional callable(done, total, client_name, status)

    Returns:
        {"total": int, "ok": int, "errors": int, "results": [...]}
    """
    import json
    import psycopg2.extras
    from web.pg_db import get_standalone_conn

    conn = get_standalone_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM clientes WHERE gestor = %s ORDER BY nome",
            (gestor_name,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()

    if not rows:
        return {"total": 0, "ok": 0, "errors": 0, "results": []}

    # Parse extras if stored as string
    for r in rows:
        if isinstance(r.get("extras"), str):
            r["extras"] = json.loads(r["extras"])

    total = len(rows)
    results = []
    ok_count = 0
    err_count = 0

    for i, row in enumerate(rows):
        cliente = _build_cliente_from_row(row)
        result = _collect_for_client(cliente, freq)
        results.append(result)

        if result["status"] == "ok":
            ok_count += 1
        else:
            err_count += 1

        if progress_callback:
            progress_callback(i + 1, total, result["client"], result["status"])

    return {"total": total, "ok": ok_count, "errors": err_count, "results": results}


def collect_metrics_for_clients(
    client_names: List[str],
    freq: str = "SEMANAL",
    progress_callback=None,
):
    """Collect metrics for specific clients by name.

    Args:
        client_names: List of client names
        freq: "SEMANAL" or "MENSAL"
        progress_callback: Optional callable(done, total, client_name, status)

    Returns:
        {"total": int, "ok": int, "errors": int, "results": [...]}
    """
    import json
    import psycopg2.extras
    from web.pg_db import get_standalone_conn

    conn = get_standalone_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM clientes WHERE nome = ANY(%s) ORDER BY nome",
            (client_names,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()

    for r in rows:
        if isinstance(r.get("extras"), str):
            r["extras"] = json.loads(r["extras"])

    total = len(rows)
    results = []
    ok_count = 0
    err_count = 0

    for i, row in enumerate(rows):
        cliente = _build_cliente_from_row(row)
        result = _collect_for_client(cliente, freq)
        results.append(result)

        if result["status"] == "ok":
            ok_count += 1
        else:
            err_count += 1

        if progress_callback:
            progress_callback(i + 1, total, result["client"], result["status"])

    return {"total": total, "ok": ok_count, "errors": err_count, "results": results}
