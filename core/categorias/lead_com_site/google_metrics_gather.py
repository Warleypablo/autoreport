from __future__ import annotations
"""
Coleta métricas de **Leads** na Google Ads API.

Gera placeholders:
    inv_goog, lead_goog, imp_goog, cpl_goog, lpi_goog
Compatível com o nome/assinatura antigos.
"""
import json
from pathlib import Path
from typing import Dict, Optional


from google.ads.googleads.client import GoogleAdsClient  # type: ignore
from google.ads.googleads.errors import GoogleAdsException  # type: ignore
from google.api_core.exceptions import InternalServerError
import time

from utils.logger import get_logger
from core.periodo import Periodo
from core.status import set_status
from utils.formatting import _fmt_brl, _fmt_int, _fmt_percent, _DEF_DASH
from .campaign_google_gather import coletar_metricas_campanhas_google

from core.cred_manager import _build_google_ads_client

log = get_logger(__name__)

# ------------------------------------------------------------------ helpers
def _calc_cpl(cost: Optional[float], leads: Optional[int]) -> Optional[float]:
    return None if not cost or not leads else cost / leads


def _calc_lpi(leads: Optional[int], impressions: Optional[int]) -> Optional[float]:
    return None if not impressions or not leads else leads / impressions

# ------------------- retry helper para search_stream -------------------
def _search_stream_with_retry(ga_service, customer_id, query, max_retries=3, delay=2):
    for attempt in range(max_retries):
        try:
            return ga_service.search_stream(customer_id=customer_id, query=query)
        except InternalServerError as exc:
            if attempt < max_retries - 1:
                if attempt == 0:
                    log.warning(f"InternalServerError (tentativa {attempt+1}/{max_retries}) para {customer_id}: {exc}")
                time.sleep(delay)
            else:
                log.error(f"InternalServerError (final) para {customer_id}: {exc}")
                raise

def coletar_metricas_google(
    cliente,
    periodo: Periodo,
    sufixo: str = "",
) -> Dict[str, str]:
    """Coleta métricas de lead (Google Ads) dentro do período."""
    # --- INÍCIO: Tratamento para cliente sem plataforma Google ---
    if getattr(cliente, "id_google_ads", None) == "0":
        metricas_gerais = {
            f"{{{{inv_goog{sufixo}}}}}":  _DEF_DASH,
            f"{{{{lead_goog{sufixo}}}}}": _DEF_DASH,
            f"{{{{imp_goog{sufixo}}}}}":  _DEF_DASH,
            f"{{{{cpl_goog{sufixo}}}}}":  _DEF_DASH,
            f"{{{{lpi_goog{sufixo}}}}}":  _DEF_DASH,
        }
        return metricas_gerais

    if not (periodo.inicio and periodo.fim):
        log.error("Periodo inválido para %s (google ads)", cliente.nome)
        set_status(cliente, "ERRO DATA")
        return {}

    try:
        client = _build_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")
    except Exception as exc:
        log.error("Auth error Google Ads: %s", exc)
        set_status(cliente, "ERRO AUTH")
        return {}

    start = periodo.inicio.strftime("%Y-%m-%d")
    end   = periodo.fim.strftime("%Y-%m-%d")

    # 1) LEADS ------------------------------------------------------------
    query_conv = (
        "SELECT segments.conversion_action_category, metrics.conversions "
        "FROM customer "
        f"WHERE segments.date BETWEEN '{start}' AND '{end}' "
        "AND segments.conversion_action_category IN ("
        "  'SUBMIT_LEAD_FORM', 'PHONE_CALL_LEAD', 'QUALIFIED_LEAD', "
        "  'CONVERTED_LEAD', 'IMPORTED_LEAD', 'REQUEST_QUOTE', "
        "  'CONTACT', 'SIGNUP'"
        ")"
    )

    conv_count = 0
    try:
        for batch in _search_stream_with_retry(
            ga_service,
            customer_id=str(cliente.id_google_ads),
            query=query_conv,
        ):
            for row in batch.results:
                conv_count += int(getattr(row.metrics, 'conversions', 0) or 0)
    except GoogleAdsException as exc:
        log.error("GAQL conv falhou (%s): %s", cliente.nome, exc.failure)
        set_status(cliente, "ERRO API")
        return {}
    except InternalServerError as exc:
        log.error("GAQL conv falhou (InternalServerError) %s: %s", cliente.nome, exc)
        set_status(cliente, "ERRO API")
        return {}

    # 2) INVESTIMENTO + IMPRESSÕES ---------------------------------------
    query_tot = (
        "SELECT metrics.cost_micros, metrics.impressions "
        "FROM customer "
        f"WHERE segments.date BETWEEN '{start}' AND '{end}' "
    )

    cost_micros = 0
    impressions_int = 0
    for_batch = _search_stream_with_retry
    try:
        for batch in for_batch(
            ga_service,
            customer_id=str(cliente.id_google_ads),
            query=query_tot,
        ):
            for row in batch.results:
                cost_micros += getattr(row.metrics, 'cost_micros', 0) or 0
                impressions_int += getattr(row.metrics, 'impressions', 0) or 0
    except GoogleAdsException as exc:
        log.error("GAQL tot falhou (%s): %s", cliente.nome, exc.failure)
        set_status(cliente, "ERRO API")
        return {}
    except InternalServerError as exc:
        log.error("GAQL tot falhou (InternalServerError) %s: %s", cliente.nome, exc)
        set_status(cliente, "ERRO API")
        return {}

    invest = cost_micros / 1_000_000 if cost_micros else None
    cpl    = _calc_cpl(invest, conv_count)
    lpi    = _calc_lpi(conv_count, impressions_int)

    metricas_gerais = {
        f"{{{{inv_goog{sufixo}}}}}":  _fmt_brl(invest, 2) if invest is not None else _DEF_DASH,
        f"{{{{lead_goog{sufixo}}}}}": _fmt_int(conv_count) if conv_count is not None else _DEF_DASH,
        f"{{{{imp_goog{sufixo}}}}}":  _fmt_int(impressions_int) if impressions_int is not None else _DEF_DASH,
        f"{{{{cpl_goog{sufixo}}}}}":  _fmt_brl(cpl, 2) if cpl is not None else _DEF_DASH,
        f"{{{{lpi_goog{sufixo}}}}}":  _fmt_percent(lpi) if lpi is not None else _DEF_DASH,
    }

    # Campanhas (top-5) somente no bloco principal ------------------------
    if sufixo == "":
        metricas_gerais |= coletar_metricas_campanhas_google(cliente, periodo)

    return metricas_gerais
