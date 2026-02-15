from __future__ import annotations
"""
core.canais_ga4
-------------------------------------------------------------------------------
Coleta as *TOP N* fontes de tráfego (canais) do Google Analytics 4 ordenadas
pelo número de sessões e devolve placeholders prontos para preenchimento em
Slides.

Placeholders gerados
--------------------
* {{canal_ca{rank}}}      → Nome do canal (ex.: "Organic Search")
* {{ses_ca{rank}}}        → Sessões
* {{ses_eng_ca{rank}}}    → Sessões engajadas
* {{taxa_eng_ca{rank}}}   → Taxa de engajamento das sessões
* {{temp_med_ca{rank}}}   → Tempo médio de engajamento por sessão
* {{event_ca{rank}}}      → Eventos (eventCount)
* {{receit_ca{rank}}}     → Receita (purchaseRevenue)

Exemplo de retorno:
{
    "{{canal_ca1}}": "Organic Search",
    "{{ses_ca1}}": "1.234",
    "{{ses_eng_ca1}}": "987",
    "{{taxa_eng_ca1}}": "80,0%",
    "{{temp_med_ca1}}": "1min 12s",
    "{{event_ca1}}": "12.345",
    "{{receit_ca1}}": "R$ 34.567,89",
    ...
    "{{canal_ca5}}": "-",
    "{{ses_ca5}}": "-",
    ...
}
"""
from pathlib import Path
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    DateRange,
    Metric,
    Dimension,
    OrderBy,
)

from core.cred_manager import load_google_account
from core.periodo import Periodo
from utils.logger import get_logger
from utils.formatting import _fmt_int, _fmt_percent, _fmt_brl, _fmt_dur, _DEF_DASH

log = get_logger(__name__)

_TOP_N = 5  # quantidade padrão de canais

# Carrega um JSON/YAML externo ➜ editar sem mexer no código
raiz = Path(__file__).resolve().parents[2]          # volta 1 nível: ecommerce/ → core/
json_path = raiz / "channel_descriptions.json"
with json_path.open(encoding="utf-8") as fp:
    _CHANNEL_DESCS = {k.casefold(): v for k, v in json.load(fp).items()}

# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

_METRIC_SPECS: Dict[str, Metric] = {
    "sessions": Metric(name="sessions"),
    "engagedSessions": Metric(name="engagedSessions"),
    "engagementRate": Metric(name="engagementRate"),
    # Expressão: tempo médio de engajamento por sessão
    "avgEngTimePerSession": Metric(
        name="avgEngTimePerSession",                      #  <-- adicionado
        expression="userEngagementDuration/sessions",
    ),
    "eventCount": Metric(name="eventCount"),
    "purchaseRevenue": Metric(name="purchaseRevenue"),
}
_METRIC_KEYS: List[str] = list(_METRIC_SPECS.keys())

# ---------------------------------------------------------------------------
# Dataclass helper
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _MetricasCanal:
    canal: str = _DEF_DASH
    descricao: str = _DEF_DASH
    sessoes: Optional[int] = None
    sessoes_engajadas: Optional[int] = None
    taxa_engajamento: Optional[float] = None
    tempo_medio: Optional[float] = None
    eventos: Optional[int] = None
    receita: Optional[Decimal] = None

    def as_placeholders(self, rank: int) -> Dict[str, str]:
        """Converte em placeholders *_ca{rank}."""
        return {
            f"{{{{canal_ca{rank}}}}}":    self.canal or _DEF_DASH,
            f"{{{{desc_ca{rank}}}}}":     self.descricao or _DEF_DASH,
            f"{{{{ses_ca{rank}}}}}":      _fmt_int(self.sessoes),
            f"{{{{ses_eng_ca{rank}}}}}":  _fmt_int(self.sessoes_engajadas),
            f"{{{{taxa_eng_ca{rank}}}}}": _fmt_percent(self.taxa_engajamento),
            f"{{{{temp_med_ca{rank}}}}}": _fmt_dur(self.tempo_medio),
            f"{{{{event_ca{rank}}}}}":    _fmt_int(self.eventos),
            f"{{{{receit_ca{rank}}}}}":   _fmt_brl(float(self.receita), 2) if self.receita else _DEF_DASH,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _desc_for_channel(name: str | None) -> str:
    """Devolve descrição ou _DEF_DASH se não existir."""
    return _CHANNEL_DESCS.get((name or "").casefold(), _DEF_DASH)

def _build_client() -> BetaAnalyticsDataClient:
    return BetaAnalyticsDataClient(credentials=load_google_account())


def _value_to_float(value: str | None) -> float:
    """Converte string numérica da API para float; vazios viram 0."""
    try:
        return float(value) if value else 0.0
    except (ValueError, TypeError):
        return 0.0


def _fetch_top_channels(
    property_id: str,
    start: str,
    end: str,
    top_n: int,
) -> List[_MetricasCanal]:
    """
    Faz até duas tentativas:
    1) sessionDefaultChannelGroup
    2) sessionSourceMedium
    Retorna lista com até *top_n* canais.
    """
    client = _build_client()
    dim_candidates = ["sessionDefaultChannelGroup", "sessionSourceMedium"]

    for dim_name in dim_candidates:
        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date=start, end_date=end)],
            dimensions=[Dimension(name=dim_name)],
            metrics=list(_METRIC_SPECS.values()),
            order_bys=[
            OrderBy(
                metric=OrderBy.MetricOrderBy(metric_name="sessions"),
                desc=True,
            )
        ],
            limit=top_n,
        )

        resp = client.run_report(request)
        if resp.rows:
            log.debug("GA4 canais – dimensão escolhida: %s (%d linhas)", dim_name, len(resp.rows))
            return [
                _row_to_metrics(row, dim_name)   # transforma linha em dataclass
                for row in resp.rows
            ]

    # nenhuma dimensão trouxe dados
    log.warning("GA4 sem dados de canais no período %s – %s", start, end)
    return []


def _row_to_metrics(row, dim_name: str) -> _MetricasCanal:
    """Converte uma linha da API em _MetricasCanal."""
    values = {
        k: _value_to_float(v.value) for k, v in zip(_METRIC_KEYS, row.metric_values)
    }

    try:
        receita = Decimal(str(values["purchaseRevenue"])) if values["purchaseRevenue"] else None
    except InvalidOperation:
        receita = None

    # Define o nome do canal antes do return para uso
    canal_nome = row.dimension_values[0].value or _DEF_DASH

    return _MetricasCanal(
        canal=canal_nome,
        descricao=_desc_for_channel(canal_nome),
        sessoes=int(values["sessions"]) if values["sessions"] else None,
        sessoes_engajadas=int(values["engagedSessions"]) if values["engagedSessions"] else None,
        taxa_engajamento=values["engagementRate"] or None,
        tempo_medio=values["avgEngTimePerSession"] or None,
        eventos=int(values["eventCount"]) if values["eventCount"] else None,
        receita=receita,
    )


# ---------------------------------------------------------------------------
# Função principal pública
# ---------------------------------------------------------------------------

def coletar_top_canais_ga4(
    cliente,
    periodo: Periodo,
    top_n: int = _TOP_N,
) -> Dict[str, str]:
    """
    Retorna placeholders das TOP *top_n* fontes de tráfego.
    Caso não exista id_ga4 ou a API não traga linhas, devolve traços.
    """
    prop_id: Optional[str] = getattr(cliente, "id_ga4", None)
    if not prop_id:
        log.warning("%s sem id_ga4 – preenchendo traços.", cliente.nome)
        return _preencher_com_tracos(top_n)

    inicio = periodo.inicio.strftime("%Y-%m-%d")
    fim    = periodo.fim.strftime("%Y-%m-%d")

    try:
        canais = _fetch_top_channels(prop_id, inicio, fim, top_n)
    except Exception as exc:  # noqa: BLE001
        log.error("GA4 canais falhou (%s): %s", cliente.nome, exc)
        return _preencher_com_tracos(top_n)

    if not canais:  # ainda vazio
        return _preencher_com_tracos(top_n)

    placeholders: Dict[str, str] = {}
    for rank, canal in enumerate(canais, start=1):
        placeholders.update(canal.as_placeholders(rank))

    # completa até top_n
    while len(canais) < top_n:
        len_canais = len(canais) + 1
        placeholders.update(_MetricasCanal().as_placeholders(len_canais))
        canais.append(None)  # apenas para incrementar

    return placeholders


# ---------------------------------------------------------------------------
# Fallback geral
# ---------------------------------------------------------------------------

def _preencher_com_tracos(top_n: int) -> Dict[str, str]:
    """Retorna todos os placeholders com '-'."""
    ph: Dict[str, str] = {}
    for r in range(1, top_n + 1):
        ph.update(_MetricasCanal().as_placeholders(r))
    return ph
