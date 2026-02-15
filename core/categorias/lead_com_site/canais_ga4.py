from __future__ import annotations
"""
core.canais_ga4 (versão Lead Generation)
-------------------------------------------------------------------------------
Coleta as *TOP N* fontes de tráfego (canais) do Google Analytics 4 ordenadas
pelo número de sessões e devolve placeholders focados em geração de **leads**.

# ---------------------------------------------------------------------------
# Placeholders gerados  (🌟 ATUALIZADO)
# ---------------------------------------------------------------------------
# * {{canal_ca{rank}}}       → Nome do canal (ex.: "Organic Search")
# * {{desc_ca{rank}}}        → Descrição amigável do canal
# * {{ses_ca{rank}}}         → Sessões
# * {{ses_eng_ca{rank}}}     → Sessões engajadas
# * {{taxa_eng_ca{rank}}}    → Taxa de engajamento (%)
# * {{user_ca{rank}}}        → número de usuários
# * {{new_user_ca{rank}}}    → número de Novos usuários
"""


from pathlib import Path
import json
from dataclasses import dataclass
from typing import Dict, List, Optional

from google.analytics.data_v1beta import BetaAnalyticsDataClient  # type: ignore
from google.analytics.data_v1beta.types import (  # type: ignore
    RunReportRequest,
    DateRange,
    Metric,
    Dimension,
    OrderBy,
)

from core.cred_manager import load_google_account
from core.periodo import Periodo
from utils.logger import get_logger
from utils.formatting import _fmt_int, _fmt_percent, _DEF_DASH

log = get_logger(__name__)

_TOP_N = 5  # quantidade padrão de canais

# ---------------------------------------------------------------------------
# Descrições de canais (opcional) – carrega JSON externo
# ---------------------------------------------------------------------------
raiz = Path(__file__).resolve().parents[2]
json_path = raiz / "channel_descriptions.json"
with json_path.open(encoding="utf-8") as fp:
    _CHANNEL_DESCS = {k.casefold(): v for k, v in json.load(fp).items()}

# ---------------------------------------------------------------------------
# Métricas solicitadas à Data API
# ---------------------------------------------------------------------------
_METRIC_SPECS: Dict[str, Metric] = {
    "sessions":        Metric(name="sessions"),
    "engagedSessions": Metric(name="engagedSessions"),
    "engagementRate":  Metric(name="engagementRate"),
    "totalUsers":      Metric(name="totalUsers"),     # Corrigido para usuários
    "newUsers":        Metric(name="newUsers"),
}
_METRIC_KEYS: List[str] = list(_METRIC_SPECS.keys())

# ---------------------------------------------------------------------------
# Dataclass helper
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _MetricasCanal:
    canal: str = _DEF_DASH
    sessoes: Optional[int] = None
    sessoes_engajadas: Optional[int] = None
    taxa_engajamento: Optional[float] = None  # decimal (0-1)
    usuarios: Optional[int] = None
    novos_usuarios: Optional[int] = None

    def as_placeholders(self, rank: int) -> Dict[str, str]:
        """Converte métricas em placeholders *_ca{rank}."""
        return {
            f"{{{{canal_ca{rank}}}}}":     self.canal or _DEF_DASH,
            f"{{{{desc_ca{rank}}}}}":      _desc_for_channel(self.canal),
            f"{{{{ses_ca{rank}}}}}":       _fmt_int(self.sessoes),
            f"{{{{ses_eng_ca{rank}}}}}":   _fmt_int(self.sessoes_engajadas),
            f"{{{{taxa_eng_ca{rank}}}}}":  _fmt_percent(self.taxa_engajamento),
            f"{{{{user_ca{rank}}}}}":      _fmt_int(self.usuarios),
            f"{{{{new_user_ca{rank}}}}}":  _fmt_int(self.novos_usuarios),
        }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _desc_for_channel(name: str | None) -> str:
    """Retorna descrição legível ou _DEF_DASH se não existir."""
    return _CHANNEL_DESCS.get((name or "").casefold(), _DEF_DASH)


def _build_client() -> BetaAnalyticsDataClient:
    return BetaAnalyticsDataClient(credentials=load_google_account())


def _value_to_float(value: str | None) -> float:
    """Converte string numérica da API para float; vazios viram 0."""
    try:
        return float(value) if value else 0.0
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def _fetch_top_channels(
    property_id: str,
    start: str,
    end: str,
    top_n: int,
) -> List[_MetricasCanal]:
    """Busca as *TOP N* fontes de tráfego.

    Faz duas tentativas: primeiro por *sessionDefaultChannelGroup* e, se não
    houver dados, por *sessionSourceMedium*.
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
            log.debug("GA4 canais – dimensão usada: %s (%d linhas)", dim_name, len(resp.rows))
            return [_row_to_metrics(row) for row in resp.rows]

    # Nenhuma dimensão trouxe dados
    log.warning("GA4 sem dados de canais no período %s – %s", start, end)
    return []


def _row_to_metrics(row) -> _MetricasCanal:
    values = {k: _value_to_float(v.value) for k, v in zip(_METRIC_KEYS, row.metric_values)}
    canal_nome = row.dimension_values[0].value or _DEF_DASH

    return _MetricasCanal(
        canal=canal_nome,
        sessoes=int(values["sessions"]) if values["sessions"] else None,
        sessoes_engajadas=int(values["engagedSessions"]) if values["engagedSessions"] else None,
        taxa_engajamento=values.get("engagementRate"),
        usuarios=int(values["totalUsers"]) if values["totalUsers"] else None,
        novos_usuarios=int(values["newUsers"]) if values["newUsers"] else None,
    )


# ---------------------------------------------------------------------------
# Função pública
# ---------------------------------------------------------------------------

def coletar_top_canais_ga4(
    cliente,
    periodo: Periodo,
    top_n: int = _TOP_N,
) -> Dict[str, str]:
    """Retorna placeholders das TOP *top_n* fontes de tráfego.

    Se o cliente não possuir **id_ga4** ou a API retornar vazio, devolve todas
    as chaves com "-".
    """
    prop_id: Optional[str] = getattr(cliente, "id_ga4", None)
    if not prop_id:
        log.warning("%s sem id_ga4 – preenchendo traços.", cliente.nome)
        return _preencher_com_tracos(top_n)

    inicio = periodo.inicio.strftime("%Y-%m-%d")
    fim = periodo.fim.strftime("%Y-%m-%d")

    try:
        canais = _fetch_top_channels(prop_id, inicio, fim, top_n)
    except Exception as exc:  # noqa: BLE001
        log.error("GA4 canais falhou (%s): %s", cliente.nome, exc)
        return _preencher_com_tracos(top_n)

    if not canais:
        return _preencher_com_tracos(top_n)

    placeholders: Dict[str, str] = {}
    for rank, canal in enumerate(canais, start=1):
        placeholders.update(canal.as_placeholders(rank))

    # Completa até top_n com traços
    while len(canais) < top_n:
        placeholders.update(_MetricasCanal().as_placeholders(len(canais) + 1))
        canais.append(None)  # apenas para incrementar

    return placeholders


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def _preencher_com_tracos(top_n: int) -> Dict[str, str]:
    """Gera placeholders vazios ("-") para *top_n* posições."""
    ph: Dict[str, str] = {}
    for r in range(1, top_n + 1):
        ph.update(_MetricasCanal().as_placeholders(r))
    return ph