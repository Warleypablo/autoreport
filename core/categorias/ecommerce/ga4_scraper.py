from __future__ import annotations
"""core.ga4_scraper
-------------------------------------------------------------------------------
Captura indicadores semanais de **Google Analytics 4** focados em *engajamento* 
através da *Google Analytics Data API (v1beta)* e devolve placeholders
personalizados com sufixo *_ga*.

Métricas retornadas
-------------------
* **Número total de sessões**                    → ``{{ses_ga}}``
* **Número total de sessões engajadas**          → ``{{ses_eng_ga}}``
* **Taxa de engajamento das sessões**            → ``{{taxa_eng_ga}}``
* **Tempo médio de engajamento por sessão**      → ``{{temp_med_ga}}``  (formato amigável)

O tempo médio é obtido diretamente da API via *metric expression* e formatado
por ``_fmt_dur`` para mostrar "34s" ou "1min 14s".
"""

from dataclasses import dataclass
from typing import Dict, Optional, List

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric

from core.cred_manager import load_google_account
from core.periodo import Periodo
from utils.logger import get_logger
from utils.formatting import _fmt_percent, _fmt_int, _fmt_dur

from .canais_ga4 import coletar_top_canais_ga4

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Métricas solicitadas à Data API
# ---------------------------------------------------------------------------
_METRIC_SPECS: Dict[str, Metric] = {
    "sessions": Metric(name="sessions"),
    "engagedSessions": Metric(name="engagedSessions"),
    "engagementRate": Metric(name="engagementRate"),
    "avgEngTimePerSession": Metric(
        name="avgEngTimePerSession",
        expression="userEngagementDuration/sessions",
    ),
}

_METRIC_KEYS: List[str] = list(_METRIC_SPECS.keys())

# ---------------------------------------------------------------------------
# Dataclass → placeholders *_ga*
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _MetricasGA:
    sessoes: Optional[int] = None
    sessoes_engajadas: Optional[int] = None
    taxa_engajamento: Optional[float] = None  # decimal (0–1)
    tempo_medio_engajamento: Optional[float] = None  # segundos

    def as_placeholders_ga(self, sufixo: str = "") -> Dict[str, str]:
        return {
            f"{{{{ses_ga{sufixo}}}}}":        _fmt_int(self.sessoes),
            f"{{{{ses_eng_ga{sufixo}}}}}":    _fmt_int(self.sessoes_engajadas),
            f"{{{{taxa_eng_ga{sufixo}}}}}":   _fmt_percent(self.taxa_engajamento),
            f"{{{{temp_med_ga{sufixo}}}}}":  _fmt_dur(self.tempo_medio_engajamento),
        }


# ---------------------------------------------------------------------------
# Helpers GA4
# ---------------------------------------------------------------------------

def _build_client() -> BetaAnalyticsDataClient:
    return BetaAnalyticsDataClient(credentials=load_google_account())


def _fetch_metrics(property_id: str, start: str, end: str) -> Dict[str, float]:
    client = _build_client()
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        metrics=list(_METRIC_SPECS.values()),
    )
    resp = client.run_report(request)

    if not resp.rows:
        return {k: 0.0 for k in _METRIC_KEYS}

    row = resp.rows[0]
    return {
        k: float(v.value) if v.value else 0.0
        for k, v in zip(_METRIC_KEYS, row.metric_values)
    }


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def coletar_metricas_ga4(cliente, periodo: Periodo, sufixo: str = "") -> Dict[str, str]:
    """Coleta KPIs de engajamento via GA4 e devolve placeholders *_ga*."""

    # Verifica se o cliente tem ID do GA4
    prop_id: Optional[str] = getattr(cliente, "id_ga4", None)
    if not prop_id or prop_id == "0":
        # Não coleta nada, apenas retorna traços
        log.warning("%s sem id_ga4 ou id_ga4=0 – retornando traços.", getattr(cliente, "nome", "<sem nome>"))
        return _MetricasGA().as_placeholders_ga(sufixo)

    inicio_sem = periodo.inicio.strftime("%Y-%m-%d")
    fim_sem    = periodo.fim.strftime("%Y-%m-%d")

    try:
        met_sem = _fetch_metrics(prop_id, inicio_sem, fim_sem)
    except Exception as exc:  # noqa: BLE001
        log.error("GA4 API falhou (%s): %s", cliente.nome, exc)
        return _MetricasGA().as_placeholders_ga(sufixo)

    met = _MetricasGA(
        sessoes=int(met_sem.get("sessions", 0)) if met_sem.get("sessions") else None,
        sessoes_engajadas=int(met_sem.get("engagedSessions", 0)) if met_sem.get("engagedSessions") else None,
        taxa_engajamento=met_sem.get("engagementRate"),
        tempo_medio_engajamento=met_sem.get("avgEngTimePerSession"),
    )

    # Coleta métricas dos canais, se não for o comparativo
    if(sufixo == ""):
        placeholders_canais = coletar_top_canais_ga4(cliente, periodo)
        return {**met.as_placeholders_ga(sufixo), **placeholders_canais}
    else:
        return met.as_placeholders_ga(sufixo)
