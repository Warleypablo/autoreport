from __future__ import annotations
"""core.variacao
-------------------------------------------------------------------------------
Calcula variações percentuais entre métricas da semana atual e do período
comparativo, gerando placeholders ``{{var_<metric>}}`` para o template.
Adiciona uma setinha para indicar direção: ↑ para positivo, ↓ para negativo.

🆕 Compatível com a métrica ``temp_med_ga`` formatada como "34s" ou
"1min 14s" – converte essas strings para segundos (float) antes do cálculo.
"""

from typing import Dict, Set
import re

# Utilidades de formatação reutilizadas no projeto
try:
    from utils.formatting import _fmt_percent  # type: ignore
except ImportError:  # fallback para execução isolada
    def _fmt_percent(value: float | None) -> str:  # type: ignore
        """Formata número decimal (0.132) em percentual PT-BR (+13,2%)."""
        if value is None:
            return "—"
        sinal = '+' if value > 0 else ''
        return (
            f"{sinal}{value*100:,.1f}%"
            .replace('.', ',')  # decimal vírgula
            .replace(',', '.', 1)  # milhar ponto – apenas a 1ª
        )

try:
    from core.constants import _DEF_DASH  # type: ignore
except Exception:
    _DEF_DASH = "—"  # fallback

_ARROW_UP = '↑'
_ARROW_DOWN = '↓'

# ---------------------------------------------------------------------------
# Conversão genérica → float
# ---------------------------------------------------------------------------

def _parse_duration(s: str) -> float | None:
    """Converte "34s" ou "1min14s" (variações com espaço aceitas) em segundos."""
    st = s.strip().lower().replace(' ', '')  # normaliza espaços

    # Só trata se terminar com 's' ou contiver 'min'
    if not st.endswith('s'):
        return None

    # Expressão: (?:(\d+)min)?(\d+)s
    match = re.fullmatch(r'(?:(\d+)min)?(\d+)s', st)
    if not match:
        return None

    mins_part, secs_part = match.groups()
    mins = int(mins_part) if mins_part else 0
    secs = int(secs_part)
    return float(mins * 60 + secs)


def _to_float(value) -> float | None:  # noqa: ANN001, D401
    """Converte string formatada (PT-BR) ou numérico em float.

    Inclui suporte à duração no formato ``Xs`` ou ``YminZs``.
    Retorna **None** para valores não numéricos ou vazios.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()

    # 1️⃣  Duração "34s" ou "1min14s"
    dur = _parse_duration(s)
    if dur is not None:
        return dur

    # 2️⃣  Remove moeda/porcentagem/separadores
    s_clean = s
    for prefix in ('R$', 'r$', 'R\$', 'USD', 'BRL'):
        if s_clean.startswith(prefix):
            s_clean = s_clean[len(prefix):].strip()
    s_clean = (
        s_clean
        .replace('%', '')
        .replace('.', '')
        .replace('\u00A0', ' ')  # nbsp → espaço
        .replace(' ', '')
    )
    if ',' in s_clean:
        s_clean = s_clean.replace(',', '.')

    try:
        return float(s_clean)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Formatação de variação
# ---------------------------------------------------------------------------

def _fmt_variacao(delta: float | None) -> str:  # noqa: ANN001, D401
    """Formata variação (ex.: 0.123 → '↑ +12,3%')."""
    if delta is None:
        return _DEF_DASH
    if delta == 0:
        return '0%'
    percent = delta * 100
    arrow = _ARROW_UP if percent > 0 else _ARROW_DOWN
    sinal = '+' if percent > 0 else ''
    texto = f"{percent:,.1f}%".replace('.', ',')
    return f"{arrow} {sinal}{texto}"


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def calcular_variacoes(dados: Dict[str, str], _METRIC_VAR_KEYS: Set[str]) -> Dict[str, str]:  # noqa: D401
    """Calcula e devolve placeholders ``{{var_<metric>}}``.

    Parameters
    ----------
    dados : dict
        Placeholders da semana corrente e do período comparativo.
    """
    
    variacoes: Dict[str, str] = {}

    for chave in _METRIC_VAR_KEYS:
        chave_semana = f"{{{{{chave}}}}}"
        chave_comp = f"{{{{{chave}_comp}}}}"

        atual = _to_float(dados.get(chave_semana))
        comp = _to_float(dados.get(chave_comp))

        if atual is None or comp in (None, 0):
            variacoes[f"{{{{var_{chave}}}}}"] = _DEF_DASH
            continue

        delta = (atual / comp) - 1
        variacoes[f"{{{{var_{chave}}}}}"] = _fmt_variacao(delta)

    return variacoes


__all__ = ['calcular_variacoes']