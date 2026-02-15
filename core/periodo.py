# -*- coding: utf-8 -*-
"""core.periodo

Utilitário de cálculo de períodos de referência usados no relatório.

Novidades
---------
Este módulo agora suporta **duas periodicidades**: semanal (padrão) e
mensal. Uma *macro* simples define qual delas será utilizada, sem exigir
mudanças no restante do pipeline.

* **Semanal** – mantém a lógica original: última janela móvel de 7 dias
  (de D‑7 a D‑1).
* **Mensal** – mês civil completo imediatamente anterior ao mês corrente.
  Ex.: se hoje for 04/07/2025, retorna 01/06/2025 → 30/06/2025.

A periodicidade é controlada por uma única **constante global**
``FREQUENCIA_DEFAULT`` neste arquivo.  Basta alterar seu valor para
``Frequencia.SEMANAL`` ou ``Frequencia.MENSAL`` conforme a necessidade.
Você também pode sobrescrever esse comportamento passando o parâmetro
``frequencia`` diretamente para :func:`periodo_referencia`.

Exemplo
-------
>>> periodo_referencia(today=date(2025, 7, 4))  # semanal (default)
Periodo(inicio=date(2025, 6, 28), fim=date(2025, 7, 3), fim_plus_1=date(2025, 7, 4))
>>> periodo_referencia(today=date(2025, 7, 4), frequencia="MENSAL")
Periodo(inicio=date(2025, 6, 1), fim=date(2025, 6, 30), fim_plus_1=date(2025, 7, 1))
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Any

__all__ = [
    "Periodo",
    "Frequencia",
    "FREQUENCIA_DEFAULT",
    "periodo_referencia",
    "ultima_semana_completa",
    "ultimo_mes_completo",
]


class Frequencia(str, Enum):
    """Enum legível para periodicidade de relatório."""

    SEMANAL = "SEMANAL"
    MENSAL = "MENSAL"

    @classmethod
    def from_any(cls, value: str | "Frequencia" | None) -> "Frequencia":  # pragma: no cover
        if value is None:
            return cls.SEMANAL
        if isinstance(value, cls):
            return value
        return cls(value.upper())


#: Frequência padrão usada quando nenhuma é informada às funções de fachada.
#   **Altere aqui** para trocar entre SEMANAL e MENSAL.
FREQUENCIA_DEFAULT: Frequencia = Frequencia.SEMANAL


@dataclass(slots=True)
class Periodo:
    """Objeto‐valor representando um intervalo de tempo fechado."""

    inicio: date
    fim: date
    fim_plus_1: date
    extra: dict[str, Any] | None = None

    # Métodos utilitários ---------------------------------------------------
    def __contains__(self, dia: date) -> bool:  # pragma: no cover
        return self.inicio <= dia <= self.fim

    def __iter__(self):  # pragma: no cover
        current = self.inicio
        while current <= self.fim:
            yield current
            current += timedelta(days=1)

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover
        d = {
            "inicio": self.inicio.isoformat(),
            "fim": self.fim.isoformat(),
            "fim_plus_1": self.fim_plus_1.isoformat(),
        }
        if self.extra:
            d.update(self.extra)
        return d

    # Representações amigáveis ---------------------------------------------
    def __str__(self):  # pragma: no cover
        return f"{self.inicio:%d/%m/%Y} → {self.fim:%d/%m/%Y}"

    def __repr__(self):  # pragma: no cover
        return (
            f"Periodo(inicio={self.inicio!r}, fim={self.fim!r}, "
            f"fim_plus_1={self.fim_plus_1!r})"
        )


# ---------------------------------------------------------------------------
# Funções específicas de cálculo
# ---------------------------------------------------------------------------


def ultima_semana_completa(*, today: date | None = None) -> Periodo:
    """Retorna a **última janela móvel de sete dias**: de ontem (incl.) a seis dias atrás.

    Parameters
    ----------
    today : date | None
        Data de referência.  Se ``None``, utiliza :pyfunc:`date.today`.
    """
    if today is None:
        today = date.today()

    fim = today - timedelta(days=1)       # ontem
    inicio = fim - timedelta(days=6)      # seis dias antes
    fim_plus_1 = fim + timedelta(days=1)  # hoje, útil p/ nomes de arquivos

    return Periodo(inicio=inicio, fim=fim, fim_plus_1=fim_plus_1)


def ultimo_mes_completo(*, today: date | None = None) -> Periodo:
    """Retorna o **mês civil completo** imediatamente anterior ao mês corrente.

    Exemplos
    --------
    >>> ultimo_mes_completo(today=date(2025, 7, 4))
    Periodo(inicio=date(2025, 6, 1), fim=date(2025, 6, 30), fim_plus_1=date(2025, 7, 1))
    """
    if today is None:
        today = date.today()

    month = today.month - 1
    year = today.year
    if month == 0:
        month = 12
        year -= 1

    inicio = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    fim = date(year, month, last_day)
    fim_plus_1 = fim + timedelta(days=1)

    return Periodo(inicio=inicio, fim=fim, fim_plus_1=fim_plus_1)


# ---------------------------------------------------------------------------
# Função de fachada – decide qual cálculo usar conforme a *macro*.
# ---------------------------------------------------------------------------


def periodo_referencia(*, today: date | None = None, frequencia: str | Frequencia | None = None) -> Periodo:
    """Retorna o :class:`Periodo` adequado à periodicidade desejada.

    Parameters
    ----------
    today : date | None
        Data de referência.  Se ``None``, utiliza :pyfunc:`date.today`.
    frequencia : str | Frequencia | None
        Quando ``None``, usa o valor de :data:`FREQUENCIA_DEFAULT`.  Pode
        ser uma instância de :class:`Frequencia` ou uma *string*
        ("SEMANAL" / "MENSAL").  Valores inválidos geram
        :class:`ValueError`.
    """
    freq = Frequencia.from_any(frequencia) if frequencia else FREQUENCIA_DEFAULT

    if freq is Frequencia.MENSAL:
        return ultimo_mes_completo(today=today)
    return ultima_semana_completa(today=today)