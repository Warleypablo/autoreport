from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from google.ads.googleads.client import GoogleAdsClient # type: ignore
from google.ads.googleads.errors import GoogleAdsException # type: ignore

from utils.logger import get_logger
from core.periodo import Periodo
from core.status import set_status
from utils.formatting import _fmt_brl, _fmt_int, _fmt_roas

from .campaign_google_gather import coletar_metricas_campanhas_google

from core.cred_manager import _build_google_ads_client

log = get_logger(__name__)
_DEF_DASH = "-"

# --------------------------------------------------------------------
# Utilidades numéricas
def _sum(seq):
    return None if not seq else float(sum(seq))

def _calc_cpa(cost: Optional[float], conv: Optional[int]) -> Optional[float]:
    return None if not cost or not conv else cost / conv

def _calc_roas(value: Optional[float], cost: Optional[float]) -> Optional[float]:
    return None if not cost or not value else value / cost

# --------------------------------------------------------------------
def coletar_metricas_google(cliente, periodo: Periodo, sufixo: str = "") -> Dict[str, str]:
    """
    Coleta métricas da Google Ads API para o período informado.
    Requer:
      - cliente.ads_customer_id  (ex.: 1234567890)
    """
    # --- INÍCIO: Tratamento para cliente sem plataforma Google ---
    if getattr(cliente, "id_google_ads", None) == "0":
        metricas_gerais = {
            f"{{{{inv_goog{sufixo}}}}}": _DEF_DASH,
            f"{{{{fat_goog{sufixo}}}}}": _DEF_DASH,
            f"{{{{vendas_goog{sufixo}}}}}": _DEF_DASH,
            f"{{{{cpa_goog{sufixo}}}}}": _DEF_DASH,
            f"{{{{roas_goog{sufixo}}}}}": _DEF_DASH,
        }
        return metricas_gerais

    # Pré-calcula datas apenas se necessário
    start = periodo.inicio.strftime("%Y-%m-%d") if periodo.inicio else None
    end   = periodo.fim.strftime("%Y-%m-%d") if periodo.fim else None

    try:
        client = _build_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")
    except Exception as exc:  # Falha de autenticação ou YAML
        log.error("Auth error: %s", exc)
        set_status(cliente, "ERRO AUTH")
        return {}

    # GAQL -------------------------------------------------------------
    if not periodo.inicio or not periodo.fim:
        log.error("Periodo vazio: inicio=%s, fim=%s", periodo.inicio, periodo.fim)
        set_status(cliente, "ERRO DATA")
        return {}

    query = (
        "SELECT metrics.cost_micros, "
        "       metrics.conversions, "
        "       metrics.conversions_value "
        "FROM customer "
        f"WHERE segments.date BETWEEN '{start}' AND '{end}'"
    )

    log.debug("GAQL >>> %s", query)

    try:
        response = ga_service.search_stream(
            customer_id=str(cliente.id_google_ads),
            query=query,
        )
    except GoogleAdsException as exc:
        log.error("GAQL falhou (%s): %s", cliente.nome, exc.failure)
        set_status(cliente, "ERRO API")
        return {}

    # -----------------------------------------------------------------
    # Otimização: usar variáveis locais e evitar atribuições desnecessárias
    cost_micros = 0.0
    conv = 0
    conv_value = 0.0

    for batch in response:
        for row in batch.results:
            cost = getattr(row.metrics, 'cost_micros', 0) or 0
            conversions = getattr(row.metrics, 'conversions', 0) or 0
            conv_val = getattr(row.metrics, 'conversions_value', 0.0) or 0.0
            cost_micros += cost
            conv += conversions
            conv_value += conv_val

    invest = cost_micros / 1_000_000 if cost_micros else None
    vendas = int(conv) if conv else None
    fat    = conv_value if conv_value else None

    cpa  = _calc_cpa(invest, vendas)
    roas = _calc_roas(fat, invest)

    # Dados Google Geral
    metricas_gerais = {
        f"{{{{inv_goog{sufixo}}}}}":    _fmt_brl(invest, 2) if invest is not None else _DEF_DASH,
        f"{{{{fat_goog{sufixo}}}}}":    _fmt_brl(fat, 2) if fat is not None else _DEF_DASH,
        f"{{{{vendas_goog{sufixo}}}}}": _fmt_int(vendas) if vendas is not None else _DEF_DASH,
        f"{{{{cpa_goog{sufixo}}}}}":    _fmt_brl(cpa, 2) if cpa is not None else _DEF_DASH,
        f"{{{{roas_goog{sufixo}}}}}":   _fmt_roas(roas) if roas is not None else _DEF_DASH,
    }

    if sufixo == "":
        # Campanhas específicas
        campanhas = coletar_metricas_campanhas_google(cliente, periodo)   # top-5 por conversão
        metricas_gerais.update(campanhas)
    return metricas_gerais
