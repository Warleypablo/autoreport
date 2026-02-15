# core/facebook_metrics_gather.py
from __future__ import annotations

"""Coleta métricas do Meta Ads com fallback automático.

Fluxo:
1. Tenta coletar métricas usando o token do *System User* (sem expiração).
2. Se a chamada devolve **403** (sem permissão) ou **400** indicando
   *User is not Business Scoped* / *Missing business param*, executa um
   *self‑provisioning*:
   – Usa o token do *Business Admin* humano (`ACCESS_TOKEN_META_HUMAN`)
     para adicionar o *System User* (`ID_SYSTEM_USER`) **à conta de anúncios**
     via `/{ad_account}/assigned_users` com **business=<BUSINESS_ID_META>**.
3. Tenta novamente a chamada de insights.

Esse ciclo acontece em segundos e evita que o relatório quebre quando um
cliente novo chega à base sem o SU provisionado.

Nota: Tokens e IDs sensíveis devem vir de `config.settings`.
"""

import json
import os
import datetime as dt
from typing import Dict, Optional, Sequence, Tuple

import requests

from config.settings import (
    ACCESS_TOKEN_META_HUMAN,
    ACCESS_TOKEN_META_SYSTEM,
    ID_SYSTEM_USER,
    BUSINESS_ID_META,
)
from utils.logger import get_logger
from core.periodo import Periodo
from core.status import set_status
from utils.formatting import _fmt_brl, _fmt_roas, _fmt_int, _DEF_DASH
from .campaign_facebook_gather import coletar_metricas_anuncios_meta

log = get_logger(__name__)
_DEF_DASH = "-"
META_API_VERSION = "v23.0"
TIMEOUT = 30  # seg
PURCHASE_TYPES = {"omni_purchase"}


def _mask_token(token: str) -> str:
    """Masca token para log (prefixo/sufixo)."""
    if not token:
        return "-"
    if len(token) <= 12:
        return token
    return f"{token[:6]}...{token[-6:]}"

###############################################################################
# Helpers numéricos
###############################################################################

def _calc_cpa(spend: Optional[float], vendas: Optional[int]) -> Optional[float]:
    if spend is None or vendas in (None, 0):
        return None
    return spend / vendas


def _calc_roas(faturamento: Optional[float], spend: Optional[float]) -> Optional[float]:
    if faturamento is None or spend in (None, 0):
        return None
    return faturamento / spend


def _extract_purchase_metrics(actions, action_values) -> Tuple[int, float]:
    """Conta conversões e receita sem duplicar."""
    conv = sum(
        int(float(a.get("value", 0))) for a in (actions or []) if a.get("action_type") == "purchase"
    )
    fat = sum(
        float(a.get("value", 0)) for a in (action_values or []) if a.get("action_type") == "purchase"
    )
    return conv, fat

###############################################################################
# Fallback de permissão – adiciona o System User na conta se necessário
###############################################################################

def _provision_system_user(ad_account_id: str) -> bool:
    """Tenta adicionar o System User à conta via API.

    Retorna True se deu certo, False caso contrário.
    """
    url = f"https://graph.facebook.com/{META_API_VERSION}/act_{ad_account_id}/assigned_users"

    payload = {
        "user": ID_SYSTEM_USER,
        "tasks": json.dumps(["ANALYZE"]),
        "business": BUSINESS_ID_META,  # 💡 param obrigatório
        "access_token": ACCESS_TOKEN_META_HUMAN,
    }

    try:
        r = requests.post(url, data=payload, timeout=TIMEOUT)
        r.raise_for_status()
        ok = r.json() is True or r.json().get("success") or r.text == "true"
        if ok:
            log.info("System User %s atribuído à ad %s", ID_SYSTEM_USER, ad_account_id)
        else:
            log.warning("POST /assigned_users respondeu mas sem 'true': %s", r.text)
        return ok
    except requests.HTTPError as exc:
        log.error("Falha ao atribuir System User à ad %s: %s", ad_account_id, exc.response.text)
        return False

###############################################################################
# Função pública (mantém a mesma assinatura da versão anterior)
###############################################################################

def coletar_metricas_facebook(cliente, periodo: Periodo, sufixo: str = "") -> Dict[str, str]:
    """
    Otimizado: uso de requests.Session, agregação vetorizada, micro-otimizações.
    """
    # --- INÍCIO: Tratamento para cliente sem plataforma ---
    if getattr(cliente, "id_meta_ads", None) == "0":
        metricas_gerais = {
            f"{{{{inv_face{sufixo}}}}}": _DEF_DASH,
            f"{{{{fat_face{sufixo}}}}}": _DEF_DASH,
            f"{{{{vendas_face{sufixo}}}}}": _DEF_DASH,
            f"{{{{cpa_face{sufixo}}}}}": _DEF_DASH,
            f"{{{{roas_face{sufixo}}}}}": _DEF_DASH,
        }
        return metricas_gerais

    ad_acct_id = cliente.id_meta_ads
    acct_path = f"act_{ad_acct_id}"
    url = f"https://graph.facebook.com/{META_API_VERSION}/{acct_path}/insights"

    time_range = {
        "since": periodo.inicio.strftime("%Y-%m-%d"),
        "until": periodo.fim.strftime("%Y-%m-%d"),
    }

    params = {
        "level": "ad",
        "time_range": json.dumps(time_range, separators=(",", ":")),
        "time_increment": "all_days",
        "fields": "spend,actions,action_values",
        "action_attribution_windows": json.dumps(["7d_click"]),
        "action_report_time": "conversion",
        "limit": 5000,
        "access_token": ACCESS_TOKEN_META_SYSTEM,
    }

    session = requests.Session()
    session.headers.update({"Connection": "keep-alive"})

    log.info(
        "Meta token (masked) e intervalo",
        extra={
            "token_system": _mask_token(ACCESS_TOKEN_META_SYSTEM),
            "token_human": _mask_token(ACCESS_TOKEN_META_HUMAN),
            "since": time_range["since"],
            "until": time_range["until"],
        },
    )

    def _fetch() -> requests.Response:
        return session.get(url, params=params, timeout=TIMEOUT)

    # 1ª tentativa com token do System User
    resp = _fetch()

    if resp.status_code in {400, 403}:
        try:
            body = resp.json()
            msg = body.get("error", {}).get("message", "")
        except ValueError:
            msg = resp.text
        log.warning("Insights devolveu %s para %s: %s", resp.status_code, cliente.nome, msg)

        # Se for erro de permissão, tenta provisionar o System User
        if any(substr in msg.lower() for substr in ("permission", "business scoped", "missing business")):
            ok = _provision_system_user(ad_acct_id)
            if ok:
                resp = _fetch()  # 2ª tentativa agora que o SU tem acesso

    try:
        resp.raise_for_status()
    except requests.HTTPError:
        status_msg = "ERRO API META"
        try:
            err = resp.json().get("error", {})
            if err.get("code") == 190 and err.get("error_subcode") == 463:
                status_msg = "TOKEN EXPIRADO"
        except ValueError:
            pass
        log.error(
            "Erro HTTP Meta API (%s): %s",
            cliente.nome,
            resp.text,
            extra={
                "status_marker": status_msg,
                "token_system": _mask_token(ACCESS_TOKEN_META_SYSTEM),
                "token_human": _mask_token(ACCESS_TOKEN_META_HUMAN),
            },
        )
        set_status(cliente, status_msg)
        return {}

    # Parsing e agregação otimizados
    data = resp.json().get("data", []) if resp.text else []
    if not data:
        log.warning("Meta API devolveu lista vazia para %s", cliente.nome)
        set_status(cliente, "SEM DADOS")
        return {}

    # Pré-processamento para minimizar overhead de laço
    get_spend = lambda row: float(row.get("spend", 0.0))
    get_acts = lambda row: row.get("actions") or []
    get_vals = lambda row: row.get("action_values") or []

    # Agregação vetorizada
    spends = [get_spend(row) for row in data]
    acts_list = [get_acts(row) for row in data]
    vals_list = [get_vals(row) for row in data]

    spend = sum(spends)
    vendas_int = 0
    faturamento = 0.0
    for acts, vals in zip(acts_list, vals_list):
        add_v, add_fat = _extract_purchase_metrics(acts, vals)
        vendas_int += add_v
        faturamento += add_fat

    cpa = _calc_cpa(spend, vendas_int)
    roas = _calc_roas(faturamento, spend)

    metricas_gerais = {
        f"{{{{inv_face{sufixo}}}}}": _fmt_brl(spend, 2),
        f"{{{{fat_face{sufixo}}}}}": _fmt_brl(faturamento, 2),
        f"{{{{vendas_face{sufixo}}}}}": _fmt_int(vendas_int),
        f"{{{{cpa_face{sufixo}}}}}": _fmt_brl(cpa, 2) if cpa is not None else _DEF_DASH,
        f"{{{{roas_face{sufixo}}}}}": _fmt_roas(roas) if roas is not None else _DEF_DASH,
    }

    if sufixo == "":
        campanhas = coletar_metricas_anuncios_meta(cliente, periodo)
        return {**metricas_gerais, **campanhas}

    return metricas_gerais
