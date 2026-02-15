"""
Handler completo para clientes de **Lead Sem Site**.

Mantém o mesmo padrão do handler de E‑commerce: coleta todas as métricas,
monta o dicionário de placeholders e faz pós‑processamento opcional no
Google Slides (barras de meta, remoção de páginas vazias, etc.).

As integrações específicas (CRM, Painel, Meta) vivem dentro do pacote
`core.lead_sem_site` e podem ser ajustadas sem afetar o orquestrador.
"""

from __future__ import annotations
from typing import Set

# ─────────────────── imports dos sub‑módulos da categoria ────────────────────
from core import (
    variacao_dados_comparativos,
    slide_filler,
    progress_bar,
    variation_styler
)
from config import settings  # type: ignore

from .lead_sem_site import (
    painel_scraper,          # Painel ou CRM consolidado
    facebook_metrics_gather, # Métricas de Meta Ads (leads)
)

from dataclasses import dataclass

# Nome canônico da categoria  ➔ usado como chave em get_handler()
nome = "Lead Sem Site"
# ID do template no Google Slides (substitua pelo seu)
template_id = settings.TEMPLATE_LEAD_SEM_SITE

@dataclass(frozen=True)
class _SlideCfg:
    geral: str
    meta_ads: str

# IDs de slide – ajuste conforme o seu template
_SLIDES = _SlideCfg(
    geral="g362cfa7ad29_0_8",        # página de KPIs principais
    meta_ads="g362cfa7ad29_0_58",  # página de Meta Ads
)

# Métricas que terão variação calculada
_METRIC_VAR_KEYS: Set[str] = {
    "lead_sem", "inv_sem", "cpl", "imp",
    "lead_face", "imp", "inv_face", "cpl_face", "lpi_face", #Face
}

# ───────────────────────────────────────────────────────────────────────────────
# Interface pública                                                       (API)
# ───────────────────────────────────────────────────────────────────────────────

def coletar_dados(cliente, periodo_ref, periodo_comp):
    """Coleta e agrega todos os placeholders necessários para o relatório.

    Retorna
    -------
    dict
        Chave = {{PLACEHOLDER}}, Valor = string já formatada (PT‑BR).
    """
    from utils.logger import StepLogger, OTIMIZACAO, get_logger
    import time
    log = get_logger(__name__)
    step_logger = StepLogger(log)
    try:
        step_logger.start("painel_crm")
        dados = painel_scraper.coletar_metricas_leads(cliente, periodo_ref)
        dados.update(painel_scraper.coletar_metricas_leads(cliente, periodo_comp, sufixo="_comp"))
        step_logger.end("painel_crm")

        step_logger.start("meta_ads_leads")
        dados.update(facebook_metrics_gather.coletar_metricas_facebook(cliente, periodo_ref))
        dados.update(facebook_metrics_gather.coletar_metricas_facebook(cliente, periodo_comp, "_comp"))
        step_logger.end("meta_ads_leads")

        step_logger.start("variacoes_percentuais")
        dados.update(variacao_dados_comparativos.calcular_variacoes(dados, _METRIC_VAR_KEYS))
        step_logger.end("variacoes_percentuais")

        step_logger.start("summary_etapas_coletar_dados")
        step_logger.summary()
        step_logger.end("summary_etapas_coletar_dados")
    except Exception as exc:
        log.exception("Erro em coletar_dados", extra={"cliente": getattr(cliente, 'nome', None)})
    return dados


def pos_processar(presentation_id: str, dados: dict) -> None:
    """Ajustes pós‑processamento no Slides.

    • Redimensiona barras de meta
    • Remove páginas vazias caso não haja investimento ou sessões suficientes
    """
    from utils.logger import StepLogger, OTIMIZACAO, get_logger
    import time
    log = get_logger(__name__)
    step_logger = StepLogger(log, doc_id=presentation_id)
    try:
        step_logger.start("redimensionar_barras_meta")
        progress_bar.redimensionar(
            presentation_id,
            slide_id=_SLIDES.geral,
            meta_per_fat=dados.get("{{per_meta_lead}}"),
            meta_per_inv=dados.get("{{per_meta_inv}}"),
        )
        step_logger.end("redimensionar_barras_meta")

        step_logger.start("remover_slide_meta_ads")
        if dados.get("{{lead_face}}", "0") in {"", "0", "-", None}:
            slide_filler.remover_slide(presentation_id, _SLIDES.meta_ads)
        step_logger.end("remover_slide_meta_ads")

        step_logger.start("aplicar_vermelho_variacoes")
        variation_styler.aplicar_vermelho(presentation_id, dados, _METRIC_VAR_KEYS)
        step_logger.end("aplicar_vermelho_variacoes")

        step_logger.start("summary_etapas_pos_processar")
        step_logger.summary()
        step_logger.end("summary_etapas_pos_processar")
    except Exception as exc:
        log.exception("Erro em pos_processar", extra={"doc_id": presentation_id})
