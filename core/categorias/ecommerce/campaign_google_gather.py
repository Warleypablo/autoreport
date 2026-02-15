"""Coleta métricas das *TOP 5* campanhas do Google Ads, ordenadas por
número de conversões (desc).

Retorna um dicionário pronto para substituir os placeholders de Slides.
Exemplo de saída:
{
    "{{nome_ad1}}": "Campanha X",
    "{{conv_ad1}}": "123",
    "{{cpa_ad1}}": "R$ 45,67",
    ...
    "{{nome_ad5}}": "-",
    "{{conv_ad5}}": "-",
    ...
}
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from google.ads.googleads.client import GoogleAdsClient # type: ignore
from google.ads.googleads.errors import GoogleAdsException # type: ignore

from utils.logger import get_logger
from core.periodo import Periodo
from core.status import set_status
from utils.formatting import _fmt_brl, _fmt_int, _fmt_roas, _fmt_num_ptbr, _DEF_DASH

from decimal import Decimal, InvalidOperation

from core.cred_manager import _build_google_ads_client

log = get_logger(__name__)
_TOP_N = 5  # quantidade padrão de campanhas a capturar

# ---------------------------------------------------------------------------
# Auxiliares numéricos -------------------------------------------------------

def _to_decimal(val: str | int | float | None) -> Decimal:
    """
    Converte valores de 'value' da API para Decimal, aceitando
    notação 11.65 ou 11,65. Qualquer erro → 0.
    """
    if val in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(val).replace(",", "."))
    except InvalidOperation:
        log.warning("Valor inválido recebido: %s – tratado como 0", val)
        return Decimal("0")

def _calc_cpa(cost: Optional[float], conv: Optional[int]) -> Optional[float]:
    return None if not cost or not conv else cost / conv


def _calc_roas(value: Optional[float], cost: Optional[float]) -> Optional[float]:
    return None if not cost or not value else value / cost


# ---------------------------------------------------------------------------
# Função principal -----------------------------------------------------------

def coletar_metricas_campanhas_google(
    cliente,
    periodo: Periodo,
    top_n: int = _TOP_N,
) -> Dict[str, str]:
    """Consulta a API do Google Ads e devolve métricas das *N* campanhas com
    mais conversões dentro do período."""

    if not periodo.inicio or not periodo.fim:
        log.error("Periodo vazio para %s: inicio=%s, fim=%s", cliente.nome, periodo.inicio, periodo.fim)
        set_status(cliente, "ERRO DATA CAMP")
        return {}

    if not getattr(cliente, "id_google_ads", None):
        set_status(cliente, "SEM GOOGLE ID")
        return {}

    start = periodo.inicio.strftime("%Y-%m-%d")
    end = periodo.fim.strftime("%Y-%m-%d")

    # GAQL ------------------------------------------------------------------
    query = (
        "SELECT campaign.id, "
        "       campaign.name, "
        "       metrics.cost_micros, "
        "       metrics.conversions, "
        "       metrics.conversions_value, "
        "       metrics.impressions "
        "FROM campaign "
        f"WHERE segments.date BETWEEN '{start}' AND '{end}' "
        "  AND metrics.conversions > 0 "
        "ORDER BY metrics.conversions DESC "
        f"LIMIT {top_n}"
    )

    log.debug("GAQL TOP CAMPAIGNS >>> %s", query)

    # Autenticação ----------------------------------------------------------
    try:
        client = _build_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")
    except Exception as exc:
        log.error("Auth error (campanhas): %s", exc)
        set_status(cliente, "ERRO AUTH CAMP")
        return {}

    try:
        response = ga_service.search(
            customer_id=str(cliente.id_google_ads),
            query=query,
        )
    except GoogleAdsException as exc:
        log.error("GAQL campanhas falhou (%s): %s", cliente.nome, exc.failure)
        set_status(cliente, "ERRO API CAMP")
        return {}

    # ----------------------------------------------------------------------
    # Filtra campanhas com conversões > 0
    valid_rows = [row for row in response if _to_decimal(row.metrics.conversions) > 0]

    placeholders: Dict[str, str] = {}
    rank = 1
    for row in valid_rows[:top_n]:
        cost_micros = row.metrics.cost_micros or 0
        invest = Decimal(cost_micros) / Decimal(1_000_000)

        conv_dec = _to_decimal(row.metrics.conversions)
        fat_dec  = _to_decimal(row.metrics.conversions_value)
        impress  = int(row.metrics.impressions) if row.metrics.impressions else None

        cpa  = _calc_cpa(invest, conv_dec)
        roas = _calc_roas(fat_dec, invest)

        placeholders.update({
            f"{{{{nome_adg{rank}}}}}": row.campaign.name or "",
            f"{{{{conv_adg{rank}}}}}": _fmt_num_ptbr(conv_dec, 2),
            f"{{{{cpa_adg{rank}}}}}":  _fmt_brl(float(cpa), 2)  if cpa  else "",
            f"{{{{inv_adg{rank}}}}}":  _fmt_brl(float(invest), 2),
            f"{{{{roas_adg{rank}}}}}": _fmt_roas(float(roas))   if roas else "",
            f"{{{{fat_adg{rank}}}}}":  _fmt_brl(float(fat_dec), 2),
            f"{{{{imp_adg{rank}}}}}":  _fmt_int(impress),
        })
        rank += 1

    # Preenche até *top_n* com campos vazios
    while rank <= top_n:
        placeholders.update({
            f"{{{{nome_adg{rank}}}}}": "-",
            f"{{{{conv_adg{rank}}}}}": "-",
            f"{{{{cpa_adg{rank}}}}}":  "-",
            f"{{{{inv_adg{rank}}}}}":  "-",
            f"{{{{roas_adg{rank}}}}}": "-",
            f"{{{{fat_adg{rank}}}}}":  "-",
            f"{{{{imp_adg{rank}}}}}":  "-",
        })
        rank += 1

    return placeholders
