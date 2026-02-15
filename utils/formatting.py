"""utils.formatting
====================
Funções auxiliares de **formatação** e **parsing** usadas em todo o projeto
– sempre no padrão brasileiro (PT‑BR).

Este módulo centraliza rotinas que antes estavam espalhadas pelos scrapers
(`_fmt_brl`, `_to_float_br`, etc.). Nenhuma lógica de negócio; apenas
transformação de valores ↔ strings.

Todas as funções mantêm *a mesma assinatura e nome* dos módulos originais
para evitar refatorações amplas.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import NewType, Optional, Union

__all__ = [
    "_DEF_DASH",
    "_MONTH_PT",
    "_to_float_br",
    "_fmt_dur",
    "_fmt_brl",
    "_fmt_percent",
    "_fmt_int",
    "_fmt_num_ptbr",
    "ROAS",
    "_fmt_roas",
]

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_DEF_DASH = "-"  # placeholder padrão para valores ausentes

# Mapeia número‑do‑mês → nome em PT‑BR (maiúsculo)
_MONTH_PT = {
    1: "JANEIRO",
    2: "FEVEREIRO",
    3: "MARÇO",
    4: "ABRIL",
    5: "MAIO",
    6: "JUNHO",
    7: "JULHO",
    8: "AGOSTO",
    9: "SETEMBRO",
    10: "OUTUBRO",
    11: "NOVEMBRO",
    12: "DEZEMBRO",
}

# ---------------------------------------------------------------------------
# Parsing – string BR/percentual → float
# ---------------------------------------------------------------------------

def _to_float_br(value: Union[str, int, float, None]) -> Optional[float]:
    """Converte valores no formato PT‑BR para `float`.

    Aceita exemplos como::
        "R$ 1.234,56", "1 234,56", "2,5%", "1234.56", 42

    Retorna **None** quando o valor não pode ser interpretado.
    """
    if value in (None, "", _DEF_DASH):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    # Remove tudo que não for dígito, vírgula, ponto ou menos
    v = re.sub(r"[^\d,.-]", "", str(value)).strip()
    # Troca ponto de milhar → nada e vírgula decimal → ponto
    v = v.replace(".", "").replace(",", ".")

    try:
        return float(v)
    except ValueError:
        return None

# ---------------------------------------------------------------------------
# Formatação – numérico → string PT‑BR
# ---------------------------------------------------------------------------

def _fmt_dur(seconds: Optional[float]) -> str:
    """Formata duração em segundos → "34s" / "1min 14s".

    *Trunca* (não arredonda) para manter compatibilidade com o formato
    previamente utilizado no projeto.
    """
    if seconds is None:
        return _DEF_DASH

    try:
        total = int(seconds)  # truncagem
    except (TypeError, ValueError):
        return _DEF_DASH

    mins, secs = divmod(total, 60)
    return f"{secs}s" if mins == 0 else f"{mins}min {secs}s"


def _fmt_brl(v: Optional[float], decimais: int = 0) -> str:
    """Formata moeda BRL com separador de milhares e vírgula decimal."""
    if v is None:
        return _DEF_DASH

    fmt = f"{{:,.{decimais}f}}"  # ex.: {:,.2f}
    valor_en = fmt.format(v)       # 1,234.56 (padrão en‑US)
    valor_pt = valor_en.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {valor_pt}"


def _fmt_percent(v: Optional[float]) -> str:
    if v is None:
        return _DEF_DASH
    return f"{v * 100:.2f}%".replace(".", ",")


def _fmt_int(v: Optional[int | float]) -> str:
    if v is None:
        return _DEF_DASH
    return str(int(v))


def _fmt_num_ptbr(x: Union[float, Decimal, None], casas: int = 2) -> str:
    """Formata número genérico no padrão 1 234,56."""
    if x is None:
        return _DEF_DASH
    return (
        f"{x:,.{casas}f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


ROAS = NewType("ROAS", float)  # Return‑on‑Ad‑Spend


def _fmt_roas(v: Optional[ROAS]) -> str:
    """Formata ROAS sempre com duas casas decimais."""
    if v is None:
        return _DEF_DASH
    txt = f"{v:,.2f}"  # 3,747.00 (en‑US)
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")
