# -*- coding: utf-8 -*-
"""web/metrics_store.py - Store metric snapshots in PostgreSQL."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from utils.formatting import _to_float_br
from utils.logger import get_logger

log = get_logger(__name__)

# Mapping from dados dict keys to DB columns.
# E-commerce keys are listed first; Lead-category keys map to the same
# columns so the dashboard works for all categories (leads → vendas,
# CPL → CPA, etc.).  First-match wins when both exist.
_METRICS_MAP_ECOMMERCE = {
    "{{fat_sem}}": "faturamento",
    "{{inv_sem}}": "investimento",
    "{{roas}}": "roas",
    "{{vendas}}": "vendas",
    "{{cpa}}": "cpa",
    "{{inv_goog}}": "inv_google",
    "{{fat_goog}}": "fat_google",
    "{{inv_face}}": "inv_meta",
    "{{fat_face}}": "fat_meta",
    "{{vendas_goog}}": "vendas_google",
    "{{vendas_face}}": "vendas_meta",
    "{{roas_goog}}": "roas_google",
    "{{roas_face}}": "roas_meta",
    "{{cpa_goog}}": "cpa_google",
    "{{cpa_face}}": "cpa_meta",
    "{{ses_ga}}": "sessoes",
}

# Lead categories: leads → vendas, CPL → CPA (same DB columns)
_METRICS_MAP_LEAD = {
    "{{inv_sem}}": "investimento",
    "{{lead_sem}}": "vendas",
    "{{cpl}}": "cpa",
    "{{inv_goog}}": "inv_google",
    "{{lead_goog}}": "vendas_google",
    "{{cpl_goog}}": "cpa_google",
    "{{inv_face}}": "inv_meta",
    "{{lead_face}}": "vendas_meta",
    "{{cpl_face}}": "cpa_meta",
    "{{ses_ga}}": "sessoes",
}

# Integer columns (cast to int instead of float)
_INT_COLS = {"vendas", "vendas_google", "vendas_meta", "sessoes"}


def _parse_metric(dados: dict, key: str, col: str) -> Optional[Any]:
    """Parse a single metric from the dados dict."""
    raw = dados.get(key)
    if raw is None:
        return None
    val = _to_float_br(raw)
    if val is None:
        return None
    if col in _INT_COLS:
        return int(val)
    return val


def save_metrics_snapshot(cliente, dados: Dict[str, str], periodo, freq: str):
    """Parse formatted strings from dados dict and UPSERT into PG metricas table.

    Args:
        cliente: Cliente dataclass instance
        dados: Dict with {{placeholder}}: formatted_value pairs
        periodo: Periodo instance with .inicio and .fim attributes (date)
        freq: "SEMANAL" or "MENSAL"
    """
    from web.pg_db import get_standalone_conn

    # Pick the right mapping based on category
    cat = (cliente.categoria or "").strip().lower()
    if cat.startswith("lead"):
        metrics_map = _METRICS_MAP_LEAD
    else:
        metrics_map = _METRICS_MAP_ECOMMERCE

    # Parse metrics
    metrics = {}
    for dados_key, col_name in metrics_map.items():
        val = _parse_metric(dados, dados_key, col_name)
        # Only set if not already set (first-match wins)
        if col_name not in metrics or metrics[col_name] is None:
            metrics[col_name] = val

    # Build dados_raw: parse all values to float where possible
    dados_raw = {}
    for k, v in dados.items():
        if k.startswith("_"):
            continue
        parsed = _to_float_br(v)
        dados_raw[k] = parsed if parsed is not None else v

    conn = get_standalone_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO metricas
                (cliente_nome, categoria, freq, periodo_inicio, periodo_fim,
                 faturamento, investimento, roas, vendas, cpa,
                 inv_google, fat_google, inv_meta, fat_meta,
                 vendas_google, vendas_meta, roas_google, roas_meta,
                 cpa_google, cpa_meta, sessoes, dados_raw)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (cliente_nome, freq, periodo_inicio, periodo_fim)
            DO UPDATE SET
                faturamento = EXCLUDED.faturamento,
                investimento = EXCLUDED.investimento,
                roas = EXCLUDED.roas,
                vendas = EXCLUDED.vendas,
                cpa = EXCLUDED.cpa,
                inv_google = EXCLUDED.inv_google,
                fat_google = EXCLUDED.fat_google,
                inv_meta = EXCLUDED.inv_meta,
                fat_meta = EXCLUDED.fat_meta,
                vendas_google = EXCLUDED.vendas_google,
                vendas_meta = EXCLUDED.vendas_meta,
                roas_google = EXCLUDED.roas_google,
                roas_meta = EXCLUDED.roas_meta,
                cpa_google = EXCLUDED.cpa_google,
                cpa_meta = EXCLUDED.cpa_meta,
                sessoes = EXCLUDED.sessoes,
                dados_raw = EXCLUDED.dados_raw,
                created_at = NOW()
        """, (
            cliente.nome, cliente.categoria, freq,
            periodo.inicio, periodo.fim,
            metrics.get("faturamento"),
            metrics.get("investimento"),
            metrics.get("roas"),
            metrics.get("vendas"),
            metrics.get("cpa"),
            metrics.get("inv_google"),
            metrics.get("fat_google"),
            metrics.get("inv_meta"),
            metrics.get("fat_meta"),
            metrics.get("vendas_google"),
            metrics.get("vendas_meta"),
            metrics.get("roas_google"),
            metrics.get("roas_meta"),
            metrics.get("cpa_google"),
            metrics.get("cpa_meta"),
            metrics.get("sessoes"),
            json.dumps(dados_raw, ensure_ascii=False),
        ))
        conn.commit()
        log.info("Metricas salvas no PG para %s (%s %s-%s)",
                 cliente.nome, freq, periodo.inicio, periodo.fim)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
