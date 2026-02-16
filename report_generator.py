# -*- coding: utf-8 -*-
"""report_generator.py

Módulo orquestrador da automação de relatórios semanais.
Nenhuma lógica de negócio é implementada aqui – apenas o controle de fluxo
entre os sub‑módulos.

Preencha **config/settings.py** com as variáveis marcadas abaixo
antes da primeira execução.
"""

from __future__ import annotations

from core.status import set_status, set_last_generated # type: ignore

import argparse
import sys
from datetime import datetime, date, timedelta
from time import perf_counter
import os

from concurrent.futures import ThreadPoolExecutor, as_completed

# ────────────────────────────────────────────────────────────────────────────────
# Imports de módulos internos (mantêm o arquivo principal enxuto e testável)
# Cada import assume que a estrutura de pastas explicada na documentação existe.
# ────────────────────────────────────────────────────────────────────────────────
from config import settings  # ← TODO: atualizar variáveis neste módulo # type: ignore 
from utils.logger import get_logger # type: ignore
from utils.logger import StepLogger, OTIMIZACAO
from core import (  # type: ignore
    leitura_central,
    periodo,
    template_manager,
    slide_filler,
    relatorio_writer,
    basic_placeholders
)

# Novo import: roteador de categorias
from core.categorias import get_handler

# Logger global para este módulo (acrescenta info de módulo automaticamente)
log = get_logger(__name__)

# ────────────────────────────────────────────────────────────────────────────────
# Funções auxiliares
# ────────────────────────────────────────────────────────────────────────────────
def processar_cliente(cliente, FREQ: str = "SEMANAL") -> None:
    """Executa todas as etapas para um único cliente e
    atualiza a coluna STATUS (AUTO) na Planilha Central.
    """
    tic = perf_counter()
    step_logger = StepLogger(log, cliente=cliente.nome if hasattr(cliente, 'nome') else None)
    try:
        step_logger.start("set_status_PROCESSANDO")
        set_status(cliente, "PROCESSANDO")
        step_logger.end("set_status_PROCESSANDO")

        step_logger.start("periodo_referencia")
        periodo_ref = periodo.periodo_referencia(today=date.today(), frequencia=FREQ)
        periodo_comp = periodo.periodo_referencia(today=periodo_ref.inicio, frequencia=FREQ)
        step_logger.end("periodo_referencia")

        step_logger.start("placeholders_basicos")
        dados = basic_placeholders.montar_placeholders_basicos(cliente, periodo_ref, FREQ=FREQ)
        dados.update(basic_placeholders.montar_placeholders_basicos(cliente, periodo_comp, FREQ=FREQ, sufixo="_comp"))
        step_logger.end("placeholders_basicos")

        step_logger.start("handler_categoria")
        handler = get_handler(cliente.categoria)
        step_logger.end("handler_categoria")

        step_logger.start("coletar_dados_categoria")
        dados.update(handler.coletar_dados(cliente, periodo_ref, periodo_comp)) # Dados Concentrados
        step_logger.end("coletar_dados_categoria")

        # Salva metricas no PostgreSQL (nao-critico, falha silenciosa)
        try:
            from web.metrics_store import save_metrics_snapshot
            save_metrics_snapshot(cliente, dados, periodo_ref, FREQ)
        except Exception:
            log.warning("Falha ao salvar metricas no PG", exc_info=True)

        step_logger.start("criar_copia_template")
        presentation_id = template_manager.criar_copia(cliente, periodo_ref, template_id=handler.template_id, FREQ=FREQ)
        cliente.extras["_presentation_id"] = presentation_id
        step_logger.end("criar_copia_template")

        step_logger.start("preencher_placeholders_slides")
        slide_filler.preencher(presentation_id, dados, handler._SLIDES.meta_ads)
        step_logger.end("preencher_placeholders_slides")

        step_logger.start("pos_processar_categoria")
        handler.pos_processar(presentation_id, dados)
        step_logger.end("pos_processar_categoria")

        step_logger.start("set_status_GERADO")
        set_status(cliente, "GERADO ✅")
        step_logger.end("set_status_GERADO")

        step_logger.start("set_last_generated")
        try:
            set_last_generated(cliente, date.today())
        except Exception:
            log.exception(
                "Falha ao gravar 'ULTIMA VEZ GERADO (AUTO)'",
                extra={"cliente": cliente.nome},
            )
        step_logger.end("set_last_generated")

        step_logger.start("log_sucesso")
        log.info(
            "Relatório gerado com sucesso",
            extra={
                "cliente": cliente.nome,
                "doc_id": presentation_id,
                "elapsed": perf_counter() - tic
            }
        )
        step_logger.end("log_sucesso")

        step_logger.start("registrar_relatorio_writer")
        relatorio_writer.registrar(cliente, presentation_id, "GERADO ✅")
        step_logger.end("registrar_relatorio_writer")

        step_logger.start("summary_etapas")
        step_logger.summary()
        step_logger.end("summary_etapas")

    except Exception as exc:  # noqa: BLE001
        set_status(cliente, f"ERRO: {type(exc).__name__}"[:40])
        log.exception(
            "Falha ao processar %s",
            cliente.nome,
            extra={"elapsed": perf_counter() - tic}
        )

def processar_cliente_threadsafe(cliente, FREQ: str = "SEMANAL"):
    """Wrapper para processar um cliente e capturar possíveis exceptions."""
    try:
        processar_cliente(cliente, FREQ=FREQ)
        return (cliente.nome, "SUCESSO")
    except Exception as exc:
        # Já está sendo logado dentro de processar_cliente, mas retorna o erro para resumo
        return (cliente.nome, f"ERRO: {type(exc).__name__}")

def main(only_cliente: str | None = None) -> None:
    clientes = leitura_central.fetch_clientes(
        atualizar=True,
        only=only_cliente,
        sheet_url=settings.CENTRAL_SHEET_URL,   
        tab_name=settings.CENTRAL_TAB_NAME,
    )

    if not clientes:
        log.info("Nenhum cliente marcado para atualização. Encerrando.")
        return

    # Captura a frequência de geração via env, padrão é SEMANAL
    FREQ = os.getenv("FREQ", "").upper()

    # Cria a planilha de acompanhamento se não existir e grava para uso posterior
    ss_id = relatorio_writer.criar_planilha_relatorio()
    relatorio_writer.set_planilha_id(ss_id)

    # Número de threads pode ser ajustado via env ou use 4 por padrão
    max_threads = int(os.getenv("THREADS", "4"))
    log.info(f"Iniciando processamento com {max_threads} threads.")

    # ThreadPoolExecutor para paralelizar o processamento
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        # Submete todos os clientes
        future_to_cliente = {
            executor.submit(processar_cliente_threadsafe, cliente, FREQ): cliente
            for cliente in clientes
        }

        resultados = []
        for future in as_completed(future_to_cliente):
            cliente = future_to_cliente[future]
            try:
                cliente_nome, status = future.result()
                log.info(f"Processamento concluído: {cliente_nome} - {status}")
                resultados.append((cliente_nome, status))
            except Exception as exc:
                log.exception(f"Erro inesperado em {cliente.nome}")
                resultados.append((cliente.nome, f"EXCEPTION: {type(exc).__name__}"))

    # Resumo final
    total = len(resultados)
    erros = [r for r in resultados if "ERRO" in r[1] or "EXCEPTION" in r[1]]
    log.info(f"Processamento concluído: {total} clientes, {len(erros)} com erro.")

# ────────────────────────────────────────────────────────────────────────────────
# Ponto de entrada via CLI
# ────────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Gera relatórios semanais automatizados a partir da planilha central."
    )
    parser.add_argument(
        "--cliente",
        help="Processa apenas o cliente informado (filtro por substring, case‑insensitive).",
    )
    args = parser.parse_args()

    try:
        main(only_cliente=args.cliente)
    except KeyboardInterrupt:
        log.warning("Execução interrompida pelo usuário.")
        sys.exit(130)