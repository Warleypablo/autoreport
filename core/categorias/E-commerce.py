"""
Handler completo para clientes de E-commerce.

Toda a lógica de coleta (placeholders básicos, Painel, GA4, variações e
redimensionamento de barras de meta) vive aqui, deixando o orquestrador limpo.
"""

from __future__ import annotations
from typing import Set

# ─────────────────── imports dos sub-módulos já existentes ────────────────────
from core import (  # type: ignore
    variacao_dados_comparativos,
    slide_filler,
    progress_bar,
    variation_styler 
)
from config import settings  # type: ignore

from .ecommerce import (  # type: ignore
    painel_scraper,
    facebook_metrics_gather,
    google_metrics_gather,
    ga4_scraper
)

from dataclasses import dataclass

# Nome canônico da categoria  ➔ usado como chave em get_handler()
nome = "E-commerce"
# Template (pode ser sobrescrito via settings/env)
template_id = settings.TEMPLATE_ECOMMERCE

@dataclass(frozen=True)
class _SlideCfg:
    geral: str
    meta_ads: str
    google_ads: str
    ga4: str

_SLIDES = _SlideCfg(
    geral="g366e383ee32_0_121",
    meta_ads="g366e383ee32_0_60",
    google_ads="g366e383ee32_1_117",
    ga4="g362be775eb0_0_0"
)

# Métricas que terão variação calculada
_VARIATION_KEYS: Set[str] = {
    "fat_sem", "inv_sem", "vendas",
    "roas", "taxa_conv", "tck_med", "cps", "meta_fat",
    "meta_inv", "per_meta_fat", "per_meta_inv", "cpa",
    "vendas_face", "roas_face", "inv_face", "fat_face",
    "cpa_face", "vendas_goog", "roas_goog", "inv_goog",
    "fat_goog", "cpa_goog", "ses_ga", "ses_eng_ga",
    "taxa_eng_ga", "temp_med_ga",
}

# ───────────────────────────────────────────────────────────────────────────────
# Interface pública                                                       (API)
# ───────────────────────────────────────────────────────────────────────────────
def coletar_dados(cliente, periodo_ref, periodo_comp) -> dict:
    """
    Agrega todos os placeholders necessários (*sem*) tocar no Google Slides.

    Retorna
    -------
    dict
        Chave = {{PLACEHOLDER}}, Valor = string já formatada (PT-BR)."""
    from utils.logger import StepLogger, OTIMIZACAO, get_logger
    import time
    log = get_logger(__name__)
    step_logger = StepLogger(log)
    dados: dict = {}
    try:
        step_logger.start("painel_controle")
        dados = painel_scraper.coletar_metricas(cliente, periodo_ref)
        dados.update(painel_scraper.coletar_metricas(cliente, periodo_comp, sufixo="_comp"))
        step_logger.end("painel_controle")

        step_logger.start("meta_ads")
        dados.update(facebook_metrics_gather.coletar_metricas_facebook(cliente, periodo_ref))
        dados.update(facebook_metrics_gather.coletar_metricas_facebook(cliente, periodo_comp, "_comp"))
        step_logger.end("meta_ads")

        step_logger.start("google_ads")
        dados.update(google_metrics_gather.coletar_metricas_google(cliente, periodo_ref))
        dados.update(google_metrics_gather.coletar_metricas_google(cliente, periodo_comp, "_comp"))
        step_logger.end("google_ads")

        step_logger.start("ga4")
        dados.update(ga4_scraper.coletar_metricas_ga4(cliente, periodo_ref))
        dados.update(ga4_scraper.coletar_metricas_ga4(cliente, periodo_comp, sufixo="_comp"))
        step_logger.end("ga4")

        step_logger.start("variacoes_percentuais")
        dados.update(variacao_dados_comparativos.calcular_variacoes(dados, _VARIATION_KEYS))
        step_logger.end("variacoes_percentuais")

        step_logger.start("summary_etapas_coletar_dados")
        step_logger.summary()
        step_logger.end("summary_etapas_coletar_dados")
    except Exception as exc:
        log.exception("Erro em coletar_dados", extra={"cliente": getattr(cliente, 'nome', None)})
    return dados

def pos_processar(presentation_id: str, dados: dict) -> None:
    """
    • Ajusta barras de meta (já implementado)
    • Remove slides vazios (GA4 / Ads)
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
            meta_per_fat=dados.get('{{per_meta_fat}}'),
            meta_per_inv=dados.get('{{per_meta_inv}}')
        )
        step_logger.end("redimensionar_barras_meta")

        step_logger.start("remover_slide_meta_ads")
        if dados.get("{{fat_face}}", "0") in {"", "0", "-", None}:
            slide_filler.remover_slide(presentation_id, _SLIDES.meta_ads)
        step_logger.end("remover_slide_meta_ads")

        step_logger.start("remover_slide_google_ads")
        if dados.get("{{fat_goog}}", "0") in {"", "0", "-", None}:
            slide_filler.remover_slide(presentation_id, _SLIDES.google_ads)
        step_logger.end("remover_slide_google_ads")

        step_logger.start("remover_slide_ga4")
        if dados.get("{{ses_ga}}", "0") in {"", "0", "-", None}:
            slide_filler.remover_slide(presentation_id, _SLIDES.ga4)
        step_logger.end("remover_slide_ga4")

        step_logger.start("aplicar_vermelho_variacoes")
        variation_styler.aplicar_vermelho(presentation_id, dados, _VARIATION_KEYS)
        step_logger.end("aplicar_vermelho_variacoes")

        step_logger.start("summary_etapas_pos_processar")
        step_logger.summary()
        step_logger.end("summary_etapas_pos_processar")
    except Exception as exc:
        log.exception("Erro em pos_processar", extra={"doc_id": presentation_id})
