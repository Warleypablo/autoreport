# -*- coding: utf-8 -*-
"""web/api.py - JSON API + SSE streaming blueprint."""

import json
import queue
import threading
from decimal import Decimal
from datetime import date, datetime
from pathlib import Path

import psycopg2.extras
from flask import Blueprint, Response, jsonify, request, session

from web.auth import login_required
from web.pg_db import get_pg_conn

api_bp = Blueprint("api", __name__)


def _json_default(obj):
    """Handle Decimal, date and datetime serialisation for jsonify."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ---------------------------------------------------------------------------
# SSE broadcast infrastructure
# ---------------------------------------------------------------------------
_subscribers: list[queue.Queue] = []
_subscribers_lock = threading.Lock()


def broadcast_event(event_type: str, data: dict):
    """Push an SSE event to all connected clients."""
    msg = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _subscribers_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)


@api_bp.route("/status/stream")
@login_required
def status_stream():
    """SSE endpoint for real-time status updates."""
    def generate():
        q: queue.Queue = queue.Queue(maxsize=200)
        with _subscribers_lock:
            _subscribers.append(q)
        try:
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _subscribers_lock:
                if q in _subscribers:
                    _subscribers.remove(q)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Client listing (from PostgreSQL)
# ---------------------------------------------------------------------------
@api_bp.route("/clients")
@login_required
def list_clients():
    """Return all clients from PostgreSQL cache; fall back to Sheets if empty."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT nome, categoria, gestor, squad, painel_url, pasta_url,
                   id_google_ads, id_meta_ads, id_ga4,
                   status_auto, ultima_geracao, extras, synced_at
            FROM clientes ORDER BY nome
        """)
        rows = cur.fetchall()
        cur.close()

        # If PG table is empty, fall back to Sheets and trigger background sync
        if not rows:
            return _clients_from_sheets_fallback()

        # Map field names for backward compatibility with existing JS
        result = []
        for r in rows:
            d = dict(r)
            d["status"] = d.pop("status_auto", "")
            extras = d.get("extras") or {}
            if isinstance(extras, str):
                extras = json.loads(extras)
            d["extras"] = extras
            result.append(d)

        return jsonify(result)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        print(f"[API /clients ERROR] {tb}")
        # If PG fails entirely, fall back to Sheets
        try:
            return _clients_from_sheets_fallback()
        except Exception:
            return jsonify({"error": str(exc), "traceback": tb}), 500


def _clients_from_sheets_fallback():
    """Fetch clients directly from Google Sheets (original behavior) and trigger sync."""
    from core.leitura_central import fetch_clientes
    from config import settings

    clientes = fetch_clientes(
        atualizar=False,
        sheet_url=settings.CENTRAL_SHEET_URL,
        tab_name=settings.CENTRAL_TAB_NAME,
    )

    result = []
    for c in clientes:
        d = {
            "nome": c.nome,
            "categoria": c.categoria,
            "painel_url": c.painel_url,
            "pasta_url": c.pasta_url,
            "id_google_ads": c.id_google_ads,
            "id_meta_ads": c.id_meta_ads,
            "id_ga4": c.id_ga4,
            "gestor": c.extras.get("GESTOR", ""),
            "status": c.extras.get("STATUS (AUTO)", ""),
            "ultima_geracao": c.extras.get("ULTIMA VEZ GERADO (AUTO)", ""),
            "extras": {k: v for k, v in c.extras.items() if not k.startswith("_")},
        }
        result.append(d)

    # Trigger background sync so next request comes from PG
    _trigger_background_sync()

    return jsonify(result)


def _trigger_background_sync():
    """Run sync in a background thread (fire-and-forget)."""
    def do_sync():
        try:
            from web.sync import sync_clientes_from_sheets
            sync_clientes_from_sheets()
        except Exception:
            pass
    t = threading.Thread(target=do_sync, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Metrics collection (APIs -> PG, without report generation)
# ---------------------------------------------------------------------------
@api_bp.route("/collect-metrics", methods=["POST"])
@login_required
def collect_metrics():
    """Collect metrics from APIs for a gestor's clients (background thread)."""
    body = request.get_json(force=True) if request.data else {}
    gestor = body.get("gestor", "")
    clients = body.get("clients", [])
    freq = body.get("freq", "SEMANAL").upper()

    if not gestor and not clients:
        return jsonify({"error": "Informe 'gestor' ou 'clients'"}), 400

    def run_collection():
        from web.metrics_collector import (
            collect_metrics_for_gestor,
            collect_metrics_for_clients,
        )

        def on_progress(done, total, client_name, status):
            broadcast_event("collect_progress", {
                "done": done, "total": total,
                "client": client_name, "status": status,
            })

        if gestor:
            result = collect_metrics_for_gestor(gestor, freq, progress_callback=on_progress)
        else:
            result = collect_metrics_for_clients(clients, freq, progress_callback=on_progress)

        broadcast_event("collect_complete", {
            "total": result["total"],
            "ok": result["ok"],
            "errors": result["errors"],
        })

    t = threading.Thread(target=run_collection, daemon=True)
    t.start()

    return jsonify({"status": "started"}), 202


# ---------------------------------------------------------------------------
# Client sync (Sheets -> PG)
# ---------------------------------------------------------------------------
@api_bp.route("/sync-clients", methods=["POST"])
@login_required
def sync_clients():
    """Trigger client sync from Google Sheets to PostgreSQL."""
    try:
        from web.sync import sync_clientes_from_sheets
        result = sync_clientes_from_sheets()
        return jsonify(result)
    except Exception as exc:
        import traceback
        print(f"[API /sync-clients ERROR] {traceback.format_exc()}")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Client update (still writes to Sheets directly)
# ---------------------------------------------------------------------------
_FIELD_TO_COL = {
    "nome": "CLIENTE",
    "categoria": "CATEGORIA",
    "painel_url": "LINK PAINEL DE CONTROLE",
    "pasta_url": "LINK PASTA",
    "id_google_ads": "ID GOOGLE ADS",
    "id_meta_ads": "ID META ADS",
    "id_ga4": "ID GA4",
}


@api_bp.route("/client/<path:nome>", methods=["PUT"])
@login_required
def update_client(nome: str):
    """Update client fields in the central spreadsheet."""
    try:
        from core.leitura_central import (
            fetch_clientes, _get_sheets_service, _update_status_cell,
            parse_sheet_id,
        )
        from config import settings

        body = request.get_json(force=True)
        if not body:
            return jsonify({"error": "Corpo vazio"}), 400

        clientes = fetch_clientes(
            atualizar=False, only=nome,
            sheet_url=settings.CENTRAL_SHEET_URL,
            tab_name=settings.CENTRAL_TAB_NAME,
        )
        cliente = next((c for c in clientes if c.nome == nome), None)
        if not cliente:
            return jsonify({"error": f"Cliente '{nome}' nao encontrado"}), 404

        header_map = cliente.extras.get("_header_map", {})
        sheet_id = cliente.extras["_sheet_id"]
        tab = cliente.extras["_tab"]
        row = cliente.extras["_row"]

        service = _get_sheets_service()

        updated_fields = []
        for field_key, value in body.items():
            col_name = _FIELD_TO_COL.get(field_key)
            if not col_name:
                col_name = field_key.upper()

            col_idx = header_map.get(col_name)
            if col_idx is None:
                continue

            _update_status_cell(service, sheet_id, tab, row, col_idx, str(value))
            updated_fields.append(field_key)

        return jsonify({"updated": updated_fields})
    except Exception as exc:
        import traceback
        print(f"[API /client UPDATE ERROR] {traceback.format_exc()}")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
@api_bp.route("/generate", methods=["POST"])
@login_required
def generate():
    """Start generation for selected clients."""
    from web.jobs import start_generation_job

    body = request.get_json(force=True)
    client_names = body.get("clients", [])
    freq = body.get("freq", "SEMANAL").upper()
    if freq not in ("SEMANAL", "MENSAL"):
        return jsonify({"error": "freq deve ser SEMANAL ou MENSAL"}), 400
    if not client_names:
        return jsonify({"error": "Nenhum cliente selecionado"}), 400

    username = session.get("username", "unknown")
    job_id = start_generation_job(client_names, freq, started_by=username)
    return jsonify({"job_id": job_id}), 202


@api_bp.route("/generate-all", methods=["POST"])
@login_required
def generate_all():
    """Start generation for all eligible clients."""
    from web.jobs import start_generation_all

    body = request.get_json(force=True) if request.data else {}
    freq = body.get("freq", "SEMANAL").upper()
    if freq not in ("SEMANAL", "MENSAL"):
        return jsonify({"error": "freq deve ser SEMANAL ou MENSAL"}), 400

    username = session.get("username", "unknown")
    job_id = start_generation_all(freq, started_by=username)
    return jsonify({"job_id": job_id}), 202


# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------
@api_bp.route("/job/<job_id>")
@login_required
def job_status(job_id: str):
    """Return current status of a job."""
    from web.jobs import get_job

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job nao encontrado"}), 404
    return jsonify(job.to_dict())


@api_bp.route("/job/<job_id>/cancel", methods=["POST"])
@login_required
def cancel_job(job_id: str):
    """Cancel a running job."""
    from web.jobs import cancel_job as do_cancel

    ok = do_cancel(job_id)
    if not ok:
        return jsonify({"error": "Job nao encontrado ou ja finalizado"}), 404
    return jsonify({"status": "CANCELADO"})


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
@api_bp.route("/history")
@login_required
def get_history():
    """Return generation history from PostgreSQL."""
    from web.models import get_job_history

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    rows = get_job_history(page=page, per_page=per_page)

    # Serialize dates/decimals
    return Response(
        json.dumps(rows, default=_json_default, ensure_ascii=False),
        mimetype="application/json",
    )


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
@api_bp.route("/logs")
@login_required
def get_logs():
    """Return log lines from the log file."""
    from config import settings

    client_filter = request.args.get("client", "").strip()
    level_filter = request.args.get("level", "").strip().upper()
    lines_count = request.args.get("lines", 200, type=int)

    log_file = Path(settings.LOG_PATH) / "report.log"
    if not log_file.exists():
        return jsonify([])

    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()

    all_lines.reverse()
    result = []
    for line in all_lines:
        if len(result) >= lines_count:
            break
        if client_filter and f"cliente={client_filter}" not in line:
            continue
        if level_filter and f"| {level_filter} |" not in line:
            continue
        result.append(line.rstrip())

    return jsonify(result)


# ---------------------------------------------------------------------------
# Gestores
# ---------------------------------------------------------------------------
@api_bp.route("/gestores")
@login_required
def list_gestores():
    """Return distinct gestor names from PG; fall back to Sheets if empty."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT gestor FROM clientes
            WHERE gestor IS NOT NULL AND gestor != ''
            ORDER BY gestor
        """)
        gestores = [row[0] for row in cur.fetchall()]
        cur.close()

        if gestores:
            return jsonify(gestores)
    except Exception:
        pass

    # Fall back: fetch from Sheets and extract distinct gestores
    try:
        from core.leitura_central import fetch_clientes
        from config import settings

        clientes = fetch_clientes(
            atualizar=False,
            sheet_url=settings.CENTRAL_SHEET_URL,
            tab_name=settings.CENTRAL_TAB_NAME,
        )
        gestor_set = sorted({
            c.extras.get("GESTOR", "")
            for c in clientes
            if c.extras.get("GESTOR")
        })
        _trigger_background_sync()
        return jsonify(gestor_set)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@api_bp.route("/gestor/<path:nome>/dashboard")
@login_required
def gestor_dashboard(nome: str):
    """Return aggregated metrics and per-client breakdown for a gestor."""
    conn = get_pg_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Per-client latest metrics
    cur.execute("""
        SELECT DISTINCT ON (m.cliente_nome)
            m.cliente_nome, m.categoria, m.freq,
            m.faturamento, m.investimento, m.roas, m.vendas, m.cpa,
            m.inv_google, m.fat_google, m.inv_meta, m.fat_meta,
            m.vendas_google, m.vendas_meta, m.sessoes,
            m.periodo_inicio, m.periodo_fim, m.created_at
        FROM metricas m
        JOIN clientes c ON c.nome = m.cliente_nome
        WHERE c.gestor = %s
        ORDER BY m.cliente_nome, m.created_at DESC
    """, (nome,))
    clients_with_metrics = [dict(r) for r in cur.fetchall()]

    # Clients without metrics yet
    cur.execute("""
        SELECT c.nome as cliente_nome, c.categoria, c.status_auto, c.ultima_geracao
        FROM clientes c
        WHERE c.gestor = %s
          AND c.nome NOT IN (
              SELECT DISTINCT m.cliente_nome FROM metricas m
              JOIN clientes c2 ON c2.nome = m.cliente_nome
              WHERE c2.gestor = %s
          )
        ORDER BY c.nome
    """, (nome, nome))
    clients_no_metrics = [dict(r) for r in cur.fetchall()]

    # Summary aggregation
    summary = {
        "total_clientes": 0,
        "total_faturamento": 0,
        "total_investimento": 0,
        "roas_medio": None,
        "total_vendas": 0,
        "total_inv_google": 0,
        "total_inv_meta": 0,
    }

    # Count all clients for this gestor
    cur.execute("SELECT COUNT(*) FROM clientes WHERE gestor = %s", (nome,))
    summary["total_clientes"] = cur.fetchone()["count"]

    for c in clients_with_metrics:
        summary["total_faturamento"] += float(c.get("faturamento") or 0)
        summary["total_investimento"] += float(c.get("investimento") or 0)
        summary["total_vendas"] += int(c.get("vendas") or 0)
        summary["total_inv_google"] += float(c.get("inv_google") or 0)
        summary["total_inv_meta"] += float(c.get("inv_meta") or 0)

    if summary["total_investimento"] > 0:
        summary["roas_medio"] = round(
            summary["total_faturamento"] / summary["total_investimento"], 2
        )

    cur.close()

    result = {
        "gestor": nome,
        "summary": summary,
        "clients": clients_with_metrics,
        "clients_no_metrics": clients_no_metrics,
    }

    return Response(
        json.dumps(result, default=_json_default, ensure_ascii=False),
        mimetype="application/json",
    )
