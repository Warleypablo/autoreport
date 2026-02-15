from __future__ import annotations
"""
Top-5 campanhas Google Ads para leads.
Gera placeholders:
    nome_adgN, lead_adgN, cpl_adgN, inv_adgN, lpi_adgN, imp_adgN
"""
from pathlib import Path
from typing import Dict, Optional

from google.ads.googleads.client import GoogleAdsClient  # type: ignore
from google.ads.googleads.errors import GoogleAdsException  # type: ignore

from utils.logger import get_logger
from core.periodo import Periodo
from core.status import set_status
from utils.formatting import _fmt_brl, _fmt_int, _fmt_percent, _DEF_DASH

from core.cred_manager import _build_google_ads_client

log = get_logger(__name__)
_TOP_N = 5

# ------------------------------------------------------------------ helpers
def _calc_cpl(cost: Optional[float], leads: Optional[int]) -> Optional[float]:
    return None if not cost or not leads else cost / leads


def _calc_lpi(leads: Optional[int], impressions: Optional[int]) -> Optional[float]:
    return None if not impressions or not leads else leads / impressions

# ------------------------------------------------------------------ pública
def coletar_metricas_campanhas_google(
    cliente,
    periodo: Periodo,
    top_n: int = _TOP_N,
) -> Dict[str, str]:
    """Retorna placeholders das *top_n* campanhas por leads."""
    # sanity checks -------------------------------------------------------
    if not (periodo.inicio and periodo.fim):
        log.error("Periodo vazio para %s (campanhas)", cliente.nome)
        set_status(cliente, "ERRO DATA CAMP")
        return {}

    if not getattr(cliente, "id_google_ads", None):
        set_status(cliente, "SEM GOOGLE ID")
        return {}

    start = periodo.inicio.strftime("%Y-%m-%d")
    end   = periodo.fim.strftime("%Y-%m-%d")

    # GAQL – leads --------------------------------------------------------
    query_leads = (
        "SELECT campaign.id, campaign.name, "
        "       segments.conversion_action_category, "
        "       metrics.conversions "
        "FROM campaign "
        f"WHERE segments.date BETWEEN '{start}' AND '{end}' "
        "AND segments.conversion_action_category IN ("
        "  'SUBMIT_LEAD_FORM', 'PHONE_CALL_LEAD', 'QUALIFIED_LEAD', "
        "  'CONVERTED_LEAD', 'IMPORTED_LEAD', 'REQUEST_QUOTE', "
        "  'CONTACT', 'SIGNUP'"
        ") "
        "AND metrics.conversions > 0"
    )

    # GAQL – custo + impressões ------------------------------------------
    query_tot = (
        "SELECT campaign.id, metrics.cost_micros, metrics.impressions "
        "FROM campaign "
        f"WHERE segments.date BETWEEN '{start}' AND '{end}' "
    )

    # autenticação --------------------------------------------------------
    try:
        client      = _build_google_ads_client()
        ga_service  = client.get_service("GoogleAdsService")
    except Exception as exc:
        log.error("Auth error (campanhas): %s", exc)
        set_status(cliente, "ERRO AUTH CAMP")
        return {}

    # leads ---------------------------------------------------------------
    conv_by_id, name_by_id = {}, {}
    try:
        for batch in ga_service.search_stream(
            customer_id=str(cliente.id_google_ads),
            query=query_leads,
        ):
            for row in batch.results:
                cid = row.campaign.id
                conv_by_id[cid] = conv_by_id.get(cid, 0) + int(row.metrics.conversions or 0)
                name_by_id[cid] = row.campaign.name
    except GoogleAdsException as exc:
        log.error("GAQL leads falhou (%s): %s", cliente.nome, exc.failure)
        set_status(cliente, "ERRO API CAMP")
        return {}

    # custo + impressões --------------------------------------------------
    cost_by_id, imp_by_id = {}, {}
    try:
        for batch in ga_service.search_stream(
            customer_id=str(cliente.id_google_ads),
            query=query_tot,
        ):
            for row in batch.results:
                cid = row.campaign.id
                cost_by_id[cid] = cost_by_id.get(cid, 0) + (row.metrics.cost_micros or 0)
                imp_by_id[cid]  = imp_by_id.get(cid, 0)  + (row.metrics.impressions or 0)
    except GoogleAdsException as exc:
        log.error("GAQL tot falhou (%s): %s", cliente.nome, exc.failure)
        set_status(cliente, "ERRO API CAMP")
        return {}

    # monta placeholders --------------------------------------------------
    # Filtra campanhas com leads > 0
    valid_cids = [cid for cid in sorted(conv_by_id, key=conv_by_id.get, reverse=True) if conv_by_id[cid] > 0]

    placeholders: Dict[str, str] = {}
    for rank, cid in enumerate(valid_cids[:top_n], start=1):
        leads_int       = conv_by_id[cid]
        cost_micros     = cost_by_id.get(cid, 0)
        impressions_int = imp_by_id.get(cid, 0)

        invest = cost_micros / 1_000_000 if cost_micros else 0.0
        cpl    = _calc_cpl(invest, leads_int)
        lpi    = _calc_lpi(leads_int, impressions_int)

        placeholders.update({
            f"{{{{nome_adg{rank}}}}}": name_by_id.get(cid, ""),
            f"{{{{lead_adg{rank}}}}}": _fmt_int(leads_int),
            f"{{{{cpl_adg{rank}}}}}":  _fmt_brl(cpl, 2) if cpl is not None else "",
            f"{{{{inv_adg{rank}}}}}":  _fmt_brl(invest, 2),
            f"{{{{lpi_adg{rank}}}}}":  _fmt_percent(lpi) if lpi is not None else "",
            f"{{{{imp_adg{rank}}}}}":  _fmt_int(impressions_int),
        })

    # Preenche até top_n com campos vazios
    for rank in range(len(valid_cids[:top_n]) + 1, top_n + 1):
        placeholders.update({
            f"{{{{nome_adg{rank}}}}}": "-",
            f"{{{{lead_adg{rank}}}}}": "-",
            f"{{{{cpl_adg{rank}}}}}":  "-",
            f"{{{{inv_adg{rank}}}}}":  "-",
            f"{{{{lpi_adg{rank}}}}}":  "-",
            f"{{{{imp_adg{rank}}}}}":  "-",
        })

    return placeholders
