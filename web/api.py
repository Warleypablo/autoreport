# -*- coding: utf-8 -*-
"""web/api.py - JSON API + SSE streaming blueprint."""

import json
import queue
import threading
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, session

from web.auth import login_required

api_bp = Blueprint("api", __name__)

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
# Client listing
# ---------------------------------------------------------------------------
@api_bp.route("/clients")
@login_required
def list_clients():
    """Return all clients from the central spreadsheet (read-only)."""
    try:
        from core.leitura_central import fetch_clientes
        from config import settings

        clientes = fetch_clientes(
            atualizar=False,
            only=None,
            sheet_url=settings.CENTRAL_SHEET_URL,
            tab_name=settings.CENTRAL_TAB_NAME,
        )
        result = []
        for c in clientes:
            # Collect extra columns (non-private, non-standard)
            extra_cols = {
                k: v for k, v in c.extras.items()
                if not k.startswith("_") and k not in ("STATUS (AUTO)", "ULTIMA VEZ GERADO (AUTO)")
            }
            result.append({
                "nome": c.nome,
                "categoria": c.categoria,
                "painel_url": c.painel_url,
                "pasta_url": c.pasta_url,
                "id_google_ads": c.id_google_ads,
                "id_meta_ads": c.id_meta_ads,
                "id_ga4": c.id_ga4,
                "status": c.extras.get("STATUS (AUTO)", ""),
                "ultima_geracao": c.extras.get("ULTIMA VEZ GERADO (AUTO)", ""),
                "extras": extra_cols,
                "_row": c.extras.get("_row"),
            })
        return jsonify(result)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        print(f"[API /clients ERROR] {tb}")
        return jsonify({"error": str(exc), "traceback": tb}), 500


# ---------------------------------------------------------------------------
# Client update
# ---------------------------------------------------------------------------
# Map of editable field names to spreadsheet column headers
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

        # Fetch clients to find the target row and header_map
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
            # Check standard fields
            col_name = _FIELD_TO_COL.get(field_key)
            if not col_name:
                # Check if it's a direct column name (for extras)
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
    """Return generation history from SQLite."""
    from web.models import get_job_history

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    rows = get_job_history(page=page, per_page=per_page)
    return jsonify(rows)


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

    # Filter from the end (most recent first)
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
