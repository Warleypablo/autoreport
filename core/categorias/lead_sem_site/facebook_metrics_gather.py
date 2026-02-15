from __future__ import annotations
import json
import re
from typing import Dict, Optional, Sequence

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
from utils.formatting import _fmt_brl, _fmt_percent, _fmt_int, _DEF_DASH
from .campaign_facebook_gather import coletar_metricas_anuncios_meta

log = get_logger(__name__)
META_API_VERSION = "v23.0"
TIMEOUT = 25  # segundos, menos que 30 já acelera timeouts problemáticos

_INT_RE = re.compile(r"\d+")
_LEAD_RE = re.compile(r"(lead|conversation_started)", re.I)
_REQUIRED_TASKS = ["ANALYZE", "ADVERTISE"]

def _calc_cpl(spend: Optional[float], leads: Optional[int]) -> Optional[float]:
    return None if spend is None or leads in (None, 0) else spend / leads

def _calc_lpi(leads: Optional[int], impressions: Optional[int]) -> Optional[float]:
    return None if leads is None or impressions in (None, 0) else leads / impressions

def _lead_count_from_any(obj) -> int:
    if obj in (None, "", [], 0):
        return 0
    if isinstance(obj, str):
        m = _INT_RE.search(obj)
        return int(m.group()) if m else 0
    if isinstance(obj, dict):
        label = str(obj.get("action_type") or obj.get("indicator") or "")
        if _LEAD_RE.search(label):
            try:
                return int(float(obj.get("value", 0)))
            except Exception:
                return 0
        return 0
    if isinstance(obj, Sequence) and not isinstance(obj, str):
        total = 0
        for item in obj:
            if not isinstance(item, dict):
                continue
            label = str(item.get("action_type") or item.get("indicator") or "")
            if not _LEAD_RE.search(label):
                continue
            if "value" in item and not isinstance(item["value"], list):
                try:
                    total += int(float(item["value"]))
                except Exception:
                    continue
            elif "values" in item and item["values"]:
                try:
                    total += int(float(item["values"][0].get("value", 0)))
                except Exception:
                    continue
        return total
    try:
        return int(float(obj))
    except Exception:
        return 0

def _provision_system_user(ad_account_id: str) -> bool:
    url = f"https://graph.facebook.com/{META_API_VERSION}/act_{ad_account_id}/assigned_users"
    payload = {
        "user": ID_SYSTEM_USER,
        "tasks": json.dumps(_REQUIRED_TASKS, separators=(",", ":")),
        "business": BUSINESS_ID_META,
        "access_token": ACCESS_TOKEN_META_HUMAN,
    }
    try:
        r = requests.post(url, data=payload, timeout=TIMEOUT)
        r.raise_for_status()
        # Otimização: processa json só se for necessário
        content_type = r.headers.get("Content-Type", "")
        if "application/json" in content_type:
            data = r.json()
            ok = data is True or data.get("success")
        else:
            ok = r.text.strip() == "true"
        if ok:
            log.info("System User %s atribuído à ad %s", ID_SYSTEM_USER, ad_account_id)
        else:
            log.warning("POST /assigned_users respondeu mas sem 'true': %s", r.text)
        return ok
    except Exception as exc:
        log.error("Falha ao atribuir System User à ad %s: %s", ad_account_id, getattr(getattr(exc, "response", None), "text", exc))
        return False

def coletar_metricas_facebook(cliente, periodo: Periodo, sufixo: str = "") -> Dict[str, str]:
    """Coleta métricas do Facebook Ads para o cliente especificado."""
    # --- INÍCIO: Tratamento para cliente sem plataforma ---
    if getattr(cliente, "id_meta_ads", None) == "0":
        metricas_gerais = {
            f"{{{{inv_face{sufixo}}}}}": _DEF_DASH,
            f"{{{{lead_face{sufixo}}}}}": _DEF_DASH,
            f"{{{{imp{sufixo}}}}}": _DEF_DASH,
            f"{{{{cpl_face{sufixo}}}}}": _DEF_DASH,
            f"{{{{lpi_face{sufixo}}}}}": _DEF_DASH,
        }
        return metricas_gerais

    ad_acct_id = cliente.id_meta_ads
    url = f"https://graph.facebook.com/{META_API_VERSION}/act_{ad_acct_id}/insights"

    time_range = {
        "since": periodo.inicio.strftime("%Y-%m-%d"),
        "until": periodo.fim.strftime("%Y-%m-%d"),
    }

    params = {
        "level": "adset",
        "time_range": json.dumps(time_range, separators=(",", ":")),
        "time_increment": "all_days",
        "fields": "spend,impressions,results,actions,conversions,cost_per_action_type",
        "action_report_time": "impression",
        "use_unified_attribution_setting": "true",
        "action_attribution_windows": json.dumps(["1d_view", "7d_click", "28d_click"]),
        "action_breakdowns": "action_type",
        "limit": 5000,
        "access_token": ACCESS_TOKEN_META_SYSTEM,
    }

    session = requests.Session()
    session.headers.update({"Connection": "keep-alive"})

    def _fetch():
        return session.get(url, params=params, timeout=TIMEOUT)

    resp = _fetch()

    if resp.status_code in {400, 403}:
        try:
            msg = resp.json().get("error", {}).get("message", "")
        except Exception:
            msg = resp.text
        log.warning("Insights devolveu %s para %s: %s", resp.status_code, cliente.nome, msg)
        if any(substr in msg.lower() for substr in ("permission", "business scoped", "missing business")):
            if _provision_system_user(ad_acct_id):
                resp = _fetch()

    try:
        resp.raise_for_status()
    except requests.HTTPError:
        log.error("Erro HTTP Meta API (%s): %s", cliente.nome, resp.text)
        set_status(cliente, "ERRO API META")
        return {}

    # Otimização: parsing JSON só uma vez
    try:
        rows = resp.json().get("data", []) if resp.text else []
    except Exception:
        rows = []

    if not rows:
        log.warning("Meta API devolveu lista vazia para %s", cliente.nome)
        set_status(cliente, "SEM DADOS")
        return {}

    # AGREGAÇÃO VETORIZADA: comprehensions rápidas
    spends = []
    imps = []
    leads = []

    # single-pass, sem acessar repetidas vezes o mesmo dicionário!
    append_spend = spends.append
    append_imp = imps.append
    append_lead = leads.append

    for row in rows:
        append_spend(float(row.get("spend", 0)))
        append_imp(int(row.get("impressions", 0)))
        # O lead pode estar em várias chaves — processa apenas o necessário
        l = (
            _lead_count_from_any(row.get("results"))      or
            _lead_count_from_any(row.get("conversions")) or
            _lead_count_from_any(row.get("actions"))     or
            _lead_count_from_any(row)
        )
        append_lead(l)

    spend = sum(spends)
    impressions_int = sum(imps)
    leads_int = sum(leads)

    cpl = _calc_cpl(spend, leads_int)
    lpi = _calc_lpi(leads_int, impressions_int)

    metricas_gerais = {
        f"{{{{inv_face{sufixo}}}}}": _fmt_brl(spend, 2),
        f"{{{{lead_face{sufixo}}}}}": _fmt_int(leads_int),
        f"{{{{imp{sufixo}}}}}": _fmt_int(impressions_int),
        f"{{{{cpl_face{sufixo}}}}}": _fmt_brl(cpl, 2) if cpl is not None else _DEF_DASH,
        f"{{{{lpi_face{sufixo}}}}}": _fmt_percent(lpi) if lpi is not None else _DEF_DASH,
    }

    if sufixo == "":
        campanhas = coletar_metricas_anuncios_meta(cliente, periodo)
        metricas_gerais.update(campanhas)

    return metricas_gerais