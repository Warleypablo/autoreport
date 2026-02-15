from __future__ import annotations

"""core.basic_placeholders
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Gera *placeholders* que não dependem de consultas externas (Sheets ou GA4).
Inclui apenas informações disponíveis localmente: nome do cliente e datas do
período.

Uso típico:
    >>> from core.basic_placeholders import montar_placeholders_basicos
    >>> ph = montar_placeholders_basicos(cliente, periodo)

Também permite mesclar *placeholders* adicionais (por exemplo, métricas do
Painel ou GA4) no mesmo dicionário antes de enviá‑los ao Google Slides.
"""

from typing import Dict, Optional

from core.periodo import Periodo  # type: ignore
from utils.logger import get_logger  # type: ignore

log = get_logger(__name__)

__all__ = ["montar_placeholders_basicos"]

# ---------------------------------------------------------------------------
# Função pública
# ---------------------------------------------------------------------------

def montar_placeholders_basicos(
    cliente,
    periodo: Periodo,
    FREQ: str = "SEMANAL",
    sufixo: str = "",
    extra: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Constrói placeholders *básicos* (cliente e datas).

    Parameters
    ----------
    cliente : Cliente
        Objeto que possua, no mínimo, o atributo ``nome``.
    periodo : Periodo
        Intervalo fechado de datas para o relatório.
    sufixo : str, optional
        Texto adicionando ao final de cada chave (ex.: ``_A``).
    extra : dict, optional
        Placeholders adicionais para serem mesclados ao resultado.

    Returns
    -------
    dict
        Dicionário pronto para *batchUpdate* no Google Slides.
    """
    freq_label = "Mensal" if FREQ.upper() == "MENSAL" else "Semanal"
    basics_placeholders: Dict[str, str] = {
        f"{{{{PERIODO_INICIO{sufixo}}}}}": periodo.inicio.strftime("%d/%m/%Y"),
        f"{{{{PERIODO_FIM{sufixo}}}}}": periodo.fim.strftime("%d/%m/%Y"),
        f"{{{{periodo{sufixo}}}}}": f"{periodo.inicio.strftime('%d/%m/%Y')} – {periodo.fim.strftime('%d/%m/%Y')}",
        f"{{{{freq{sufixo}}}}}": freq_label,
    }

    # Nome do Cliente só se sufixo for vazio
    if(sufixo == ""):  
        cliente_placeholders: Dict[str, str] = { #Nome do cliente
            f"{{{{cliente{sufixo}}}}}": cliente.nome,
        }
        basics_placeholders.update(cliente_placeholders) # Adiciona o nome do cliente

    if extra:
        basics_placeholders.update(extra)

    return basics_placeholders