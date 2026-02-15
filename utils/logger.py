# -*- coding: utf-8 -*-
"""utils/logger.py

Logger centralizado para a automação de relatórios.
  • Escreve logs em stdout **e** em arquivo rotativo
  • Formato enxuto para não quebrar se `extra` estiver ausente
  • Pode ser usado em qualquer módulo com:
        from utils.logger import get_logger
        log = get_logger(__name__, extra={"cliente": "ACME", "doc_id": "abc123"})

O arquivo de log e tamanho/rotação são definidos em `config/settings.py`.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import settings 

# Macro de otimização: ativa logs detalhados de etapas
OTIMIZACAO = getattr(settings, "OTIMIZACAO", True)

# Função para logar início/fim de etapas com tempo
import time
class StepLogger:
    def __init__(self, logger, cliente=None, doc_id=None):
        self.logger = logger
        self.cliente = cliente
        self.doc_id = doc_id
        self.steps = []
    def start(self, step_name):
        if OTIMIZACAO:
            self.steps.append({"name": step_name, "start": time.perf_counter(), "end": None})
            self.logger.info(f"[OTIMIZACAO] INICIO: {step_name}", extra={"cliente": self.cliente or "-", "doc_id": self.doc_id or "-", "step": step_name})
    def end(self, step_name):
        if OTIMIZACAO:
            for step in reversed(self.steps):
                if step["name"] == step_name and step["end"] is None:
                    step["end"] = time.perf_counter()
                    elapsed = step["end"] - step["start"]
                    self.logger.info(f"[OTIMIZACAO] FIM: {step_name} | Tempo: {elapsed:.2f}s", extra={"cliente": self.cliente or "-", "doc_id": self.doc_id or "-", "step": step_name, "elapsed": elapsed})
                    break
    def summary(self):
        if OTIMIZACAO:
            for step in self.steps:
                if step["end"]:
                    elapsed = step["end"] - step["start"]
                    self.logger.info(f"[OTIMIZACAO] ETAPA: {step['name']} | Tempo: {elapsed:.2f}s", extra={"cliente": self.cliente or "-", "doc_id": self.doc_id or "-", "step": step["name"], "elapsed": elapsed})
# ─────────────────────────────────────────────
# Configuração raiz – chamada uma única vez
# ─────────────────────────────────────────────

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | "
    "cliente=%(cliente)s | doc=%(doc_id)s | %(message)s"
)

_DEFAULTS = {
    "cliente": "-",
    "doc_id": "-",
}

# Filtro para garantir campos default sem conflitar com extra
class _DefaultFieldsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if not hasattr(record, "cliente"):
            record.cliente = "-"
        if not hasattr(record, "doc_id"):
            record.doc_id = "-"
        return True


def _setup_root() -> None:
    """Inicializa o logger raiz se ainda não houver handlers."""
    root = logging.getLogger()
    if root.handlers:
        return  # já configurado por outro import

    root.setLevel(logging.INFO)
    default_filter = _DefaultFieldsFilter()
    root.addFilter(default_filter)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    # StreamHandler (stdout)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    sh.addFilter(default_filter)
    root.addHandler(sh)

    # RotatingFileHandler
    settings.LOG_PATH.mkdir(parents=True, exist_ok=True)
    log_file: Path = settings.LOG_PATH / "report.log"
    fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(formatter)
    fh.addFilter(default_filter)
    root.addHandler(fh)


_setup_root()


# ─────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────

def get_logger(name: str, extra: dict | None = None) -> logging.LoggerAdapter:
    """Retorna um LoggerAdapter com `extra` defaults.

    Parameters
    ----------
    name : str
        Geralmente use `__name__`.
    extra : dict | None
        Campos adicionais fixos. Podem ser sobrescritos por chamada.
    """
    if extra is None:
        extra = {}
    merged_defaults = {**_DEFAULTS, **extra}
    base_logger = logging.getLogger(name)
    return logging.LoggerAdapter(base_logger, merged_defaults)
