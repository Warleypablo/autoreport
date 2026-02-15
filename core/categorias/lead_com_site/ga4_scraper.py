from __future__ import annotations
"""core.ga4_scraper
-------------------------------------------------------------------------------
Captura indicadores semanais de **Google Analytics 4** focados em *aquisição de
leads* através da *Google Analytics Data API (v1beta)* e devolve placeholders
personalizados com sufixo *_ga*.

Métricas retornadas
-------------------
* **Número total de sessões**        → ``{{ses_ga}}``
* **Número total de usuários**       → ``{{user_ga}}``
* **Número total de novos usuários** → ``{{new_user_ga}}``

Estas três métricas são suficientes para avaliar a eficiência de geração de
tráfego e captação de novos leads em propriedades cujo objetivo principal NÃO é
venda de e‑commerce.
"""

from dataclasses import dataclass
from typing import Dict, Optional, List

from google.analytics.data_v1beta import BetaAnalyticsDataClient  # type: ignore
from google.analytics.data_v1beta.types import ( # type: ignore
    RunReportRequest,
    DateRange,
    Metric,
)

from core.cred_manager import load_google_account
from core.periodo import Periodo
from utils.logger import get_logger
from utils.formatting import _fmt_int

from .canais_ga4 import coletar_top_canais_ga4

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Métricas solicitadas à Data API
# ---------------------------------------------------------------------------
_METRIC_SPECS: Dict[str, Metric] = {
    "sessions": Metric(name="sessions"),
    "totalUsers": Metric(name="totalUsers"),
    "newUsers": Metric(name="newUsers"),
}

_METRIC_KEYS: List[str] = list(_METRIC_SPECS.keys())

# ---------------------------------------------------------------------------
# Dataclass → placeholders *_ga*
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _MetricasGA:
    """Container simples para as métricas GA4 usadas no relatório."""

    sessoes: Optional[int] = None
    usuarios: Optional[int] = None
    novos_usuarios: Optional[int] = None

    def as_placeholders_ga(self, sufixo: str = "") -> Dict[str, str]:
        """Converte valores em placeholders já formatados."""
        return {
            f"{{{{ses{sufixo}}}}}": _fmt_int(self.sessoes),
            f"{{{{user_ga{sufixo}}}}}": _fmt_int(self.usuarios),
            f"{{{{new_user_ga{sufixo}}}}}": _fmt_int(self.novos_usuarios),
        }


# ---------------------------------------------------------------------------
# Helpers GA4
# ---------------------------------------------------------------------------

def _build_client() -> BetaAnalyticsDataClient:
    return BetaAnalyticsDataClient(credentials=load_google_account())


def _fetch_metrics(property_id: str, start: str, end: str) -> Dict[str, float]:
    """Executa um RunReport na GA Data API e devolve as métricas brutas."""

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
    return {k: float(v.value) if v.value else 0.0 for k, v in zip(_METRIC_KEYS, row.metric_values)}


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def coletar_metricas_ga4(cliente, periodo: Periodo, sufixo: str = "") -> Dict[str, str]:
    """Coleta KPIs de aquisição de leads via GA4 e devolve placeholders *_ga*."""

    prop_id: Optional[str] = getattr(cliente, "id_ga4", None)
    if not prop_id or prop_id == "0":
        log.warning("%s sem id_ga4 ou id_ga4=0 – retornando traços.", getattr(cliente, "nome", "<sem nome>"))
        return _MetricasGA().as_placeholders_ga(sufixo)

    inicio_sem = periodo.inicio.strftime("%Y-%m-%d")
    fim_sem = periodo.fim.strftime("%Y-%m-%d")

    try:
        met_sem = _fetch_metrics(prop_id, inicio_sem, fim_sem)
    except Exception as exc:  # noqa: BLE001
        log.error("GA4 API falhou (%s): %s", cliente.nome, exc)
        return _MetricasGA().as_placeholders_ga(sufixo)

    met = _MetricasGA(
        sessoes=int(met_sem.get("sessions", 0)) if met_sem.get("sessions") else None,
        usuarios=int(met_sem.get("totalUsers", 0)) if met_sem.get("totalUsers") else None,
        novos_usuarios=int(met_sem.get("newUsers", 0)) if met_sem.get("newUsers") else None,
    )

    # Coleta métricas dos canais, se não for o comparativo
    if sufixo == "":
        placeholders_canais = coletar_top_canais_ga4(cliente, periodo)
        return {**met.as_placeholders_ga(sufixo), **placeholders_canais}

    return met.as_placeholders_ga(sufixo)