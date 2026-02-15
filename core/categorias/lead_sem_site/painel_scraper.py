from __future__ import annotations

"""Coletor de métricas de geração de leads (versão simplificada).

Esta versão foi enxugada para coletar **apenas** os indicadores abaixo ‑ os
mesmos que alimentam os placeholders no template do Google Slides:

• ``lead_sem``  – Leads da última semana completa
• ``lead_mes``  – Leads acumulados do mês atual
• ``inv_sem``   – Investimento da semana
• ``inv_mes``   – Investimento no mês
• ``cpl``       – Custo por lead (investimento ÷ leads) ‑ semana
• ``meta_lead`` – Meta de leads para o mês
• ``meta_inv``  – Meta de investimento para o mês
• ``per_meta_lead`` – % da meta de leads já cumprida
• ``per_meta_inv``  – % da meta de investimento já gasto

Todas as demais métricas (sessões, CPS, LPS etc.) foram removidas para
simplificar o código e acelerar a execução.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

import re

import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utils.logger import get_logger  # type: ignore
from core.periodo import Periodo  # type: ignore
from core.cred_manager import load_google_account  # type: ignore
from core.status import set_status  # type: ignore
from utils.formatting import (
    _fmt_brl,
    _fmt_int,
    _fmt_percent,
    _to_float_br,
    _DEF_DASH,
    _MONTH_PT,
)
from utils.sheets import a1_range, resolve_sheet_title
from utils.retry import execute_with_retries

log = get_logger(__name__)

__all__ = ["parse_sheet_id", "coletar_metricas_leads"]

# ---------------------------------------------------------------------------
# Sheets helpers
# ---------------------------------------------------------------------------

def _build_sheets_service():
    """Instância autenticada da API Google Sheets."""
    return build(
        "sheets",
        "v4",
        credentials=load_google_account(),
        cache_discovery=False,
    )


_RE_SHEET_ID = re.compile(r"/d/([a-zA-Z0-9-_]+)")


def parse_sheet_id(url: str) -> str:  # noqa: D401
    """Extrai *spreadsheetId* da URL ou lança ``ValueError``."""
    m = _RE_SHEET_ID.search(url)
    if not m:
        raise ValueError(f"URL de planilha inválida: {url}")
    return m.group(1)


# ---------------------------------------------------------------------------
# DataFrame loader com fallback de aba
# ---------------------------------------------------------------------------

def _fetch_dataframe(
    spreadsheet_id: str,
    tab_name: str = "Acompanhamento Geral",
) -> pd.DataFrame:  # noqa: D401,E501
    """Baixa tabela da planilha; se a aba não existir usa a primeira disponí­vel."""

    import time
    service = _build_sheets_service()
    tab_name = resolve_sheet_title(service, spreadsheet_id, tab_name, logger=log)
    max_retries = 5
    delay = 2.0
    last_exc = None
    for attempt in range(max_retries):
        try:
            range_a1 = a1_range(tab_name, "A:ZZZ")
            resp = execute_with_retries(
                lambda: service.spreadsheets()
                    .values()
                    .get(spreadsheetId=spreadsheet_id, range=range_a1)
                    .execute(),
                logger=log,
                context=f"sheets.values().get ({spreadsheet_id}, {range_a1})"
            )
            values: List[List[str]] = resp.get("values", [])
            if not values:
                raise RuntimeError("Planilha vazia ou aba sem dados.")
            header, *rows = values
            n_cols = len(header)
            rows = [r + [""] * (n_cols - len(r)) for r in rows]
            return pd.DataFrame(rows, columns=header)
        except HttpError as exc:
            last_exc = exc
            # Aba não encontrada (400): tenta primeira aba
            if exc.resp.status == 400 and "Unable to parse range" in str(exc):
                try:
                    meta = execute_with_retries(
                        lambda: service.spreadsheets()
                            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title")
                            .execute(),
                        logger=log,
                        context=f"sheets.get ({spreadsheet_id}, sheets.properties.title)"
                    )
                    first_title = meta["sheets"][0]["properties"]["title"]
                    log.warning(
                        "Aba '%s' não existe em %s. Usando primeira aba '%s'.",
                        tab_name,
                        spreadsheet_id,
                        first_title,
                    )
                    range_first = a1_range(first_title, "A:ZZZ")
                    resp = execute_with_retries(
                        lambda: service.spreadsheets()
                            .values()
                            .get(spreadsheetId=spreadsheet_id, range=range_first)
                            .execute(),
                        logger=log,
                        context=f"sheets.values().get ({spreadsheet_id}, {range_first})"
                    )
                    values: List[List[str]] = resp.get("values", [])
                    if not values:
                        raise RuntimeError("Planilha vazia ou aba sem dados.")
                    header, *rows = values
                    n_cols = len(header)
                    rows = [r + [""] * (n_cols - len(r)) for r in rows]
                    return pd.DataFrame(rows, columns=header)
                except Exception as exc2:
                    last_exc = exc2
            # Rate limit ou erro temporário (503): retry com backoff
            elif exc.resp.status == 503:
                log.warning(
                    "Sheets API 503 (rate limit) na tentativa %d/%d. Aguardando %.1fs...",
                    attempt + 1,
                    max_retries,
                    delay,
                )
                time.sleep(delay)
                delay *= 2
            else:
                break
        except Exception as exc:
            last_exc = exc
            break
    # Se chegou aqui, todas as tentativas falharam
    raise last_exc if last_exc else RuntimeError("Falha ao coletar dados da planilha.")


# ---------------------------------------------------------------------------
# Dataclass de retorno
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _MetricasLead:
    """Estrutura interna para armazenar métricas já tipadas."""

    lead_semana: Optional[int] = None
    lead_mes: Optional[int] = None
    investimento_semana: Optional[float] = None
    investimento_mes: Optional[float] = None
    cpl_semana: Optional[float] = None
    meta_lead: Optional[int] = None
    meta_invest: Optional[float] = None
    meta_per_lead: Optional[float] = None  # decimal (0‑1)
    meta_per_inv: Optional[float] = None   # decimal (0‑1)

    # -----------------------------------------------------------------
    # Conversão → placeholders Google Slides
    # -----------------------------------------------------------------

    def as_placeholders(self, sufixo: str = "") -> Dict[str, str]:  # noqa: D401
        return {
            f"{{{{lead_sem{sufixo}}}}}": _fmt_int(self.lead_semana),
            f"{{{{lead_mes{sufixo}}}}}": _fmt_int(self.lead_mes),
            f"{{{{inv_sem{sufixo}}}}}": _fmt_brl(self.investimento_semana),
            f"{{{{inv_mes{sufixo}}}}}": _fmt_brl(self.investimento_mes),
            f"{{{{cpl{sufixo}}}}}": _fmt_brl(self.cpl_semana, 2)
            if self.cpl_semana is not None
            else _DEF_DASH,
            f"{{{{meta_lead{sufixo}}}}}": _fmt_int(self.meta_lead),
            f"{{{{meta_inv{sufixo}}}}}": _fmt_brl(self.meta_invest),
            f"{{{{per_meta_lead{sufixo}}}}}": _fmt_percent(self.meta_per_lead),
            f"{{{{per_meta_inv{sufixo}}}}}": _fmt_percent(self.meta_per_inv),
        }


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def coletar_metricas_leads(  # noqa: D401
    cliente,
    periodo: Periodo,
    sufixo: str = "",
    aba: str = "Acompanhamento Geral",
) -> Dict[str, str]:
    """Retorna placeholders de métricas de leads para o período solicitado."""

    # 1) URL → spreadsheetId
    try:
        sheet_id = parse_sheet_id(cliente.painel_url)
    except ValueError as exc:
        log.error("URL Painel inválida (%s): %s", cliente.nome, exc)
        set_status(cliente, "PAINEL URL INVÁLIDA")
        return {}

    # 2) Baixa dados
    try:
        df = _fetch_dataframe(sheet_id, aba)
    except Exception as exc:  # noqa: BLE001
        log.error("Sheets API falhou (%s): %s", cliente.nome, exc)
        set_status(cliente, "ERRO SHEETS")
        return {}

    # 3) Validação de colunas mínimas
    required_cols = {"DATA", "VALOR INVESTIDO", "LEADS"}
    missing = required_cols - set(df.columns)
    if missing:
        msg = f"Aba sem colunas obrigatórias: {', '.join(missing)} – {cliente.nome}"
        log.error(msg)
        set_status(cliente, "ERRO CABEÇALHO")
        raise ValueError(msg)


    # 4) Normaliza coluna DATA (texto + datetime)
    df["DATA_TXT"] = df["DATA"].astype(str).str.strip().str.upper()
    df["DATA"] = (
        pd.to_datetime(
            df["DATA"].astype(str).str.strip(),
            format="%d/%m/%Y",
            dayfirst=True,
            errors="coerce",
        )
        .dt.normalize()
        .dt.date
    )

    # 5) Conversão numérica padrão BRL/pt‑BR
    numeric_cols = [
        "VALOR INVESTIDO",
        "LEADS",
        "META INVESTIMENTO",
        "META LEADS",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].apply(_to_float_br)

    # ------------------------------------------------------------------
    # Helpers de agregação
    # ------------------------------------------------------------------
    def _sum(s: pd.Series) -> Optional[float]:
        s_non_null = s.dropna()
        return None if s_non_null.empty else float(s_non_null.sum())

    def _first_non_null(s: pd.Series) -> Optional[float]:
        s_non_null = s.dropna()
        return None if s_non_null.empty else float(s_non_null.iloc[0])

    # 6) Intervalos
    inicio, fim = periodo.inicio, periodo.fim
    semana = df[df["DATA"].notna() & df["DATA"].between(inicio, fim, inclusive="both")]

    nome_mes = _MONTH_PT[fim.month]
    linha_mes = df[df["DATA"].isna() & (df["DATA_TXT"] == nome_mes)]

    if not linha_mes.empty:
        # Linha‑síntese
        lead_mes = _first_non_null(linha_mes["LEADS"])
        inv_mes = _first_non_null(linha_mes["VALOR INVESTIDO"])
        meta_lead = _first_non_null(linha_mes.get("META LEADS", pd.Series(dtype=float)))
        meta_inv = _first_non_null(linha_mes.get("META INVESTIMENTO", pd.Series(dtype=float)))
    else:
        # Fallback: soma do mês corrente
        mes = df[df["DATA"].between(inicio.replace(day=1), fim)]
        lead_mes = _sum(mes["LEADS"])
        inv_mes = _sum(mes["VALOR INVESTIDO"])
        meta_lead = _first_non_null(mes.get("META LEADS", pd.Series(dtype=float)))
        meta_inv = _first_non_null(mes.get("META INVESTIMENTO", pd.Series(dtype=float)))

    # 8) Semana
    lead_semana = _sum(semana["LEADS"])
    inv_semana = _sum(semana["VALOR INVESTIDO"])

    cpl_semana = None if not inv_semana or not lead_semana else inv_semana / lead_semana

    # 9) Metas – progresso
    meta_per_lead = None if not lead_mes or not meta_lead else lead_mes / meta_lead
    meta_per_inv = None if not inv_mes or not meta_inv else inv_mes / meta_inv

    # 10) Empacota
    met = _MetricasLead(
        lead_semana=int(lead_semana) if lead_semana is not None else None,
        lead_mes=int(lead_mes) if lead_mes is not None else None,
        investimento_semana=inv_semana,
        investimento_mes=inv_mes,
        cpl_semana=cpl_semana,
        meta_lead=int(meta_lead) if meta_lead is not None else None,
        meta_invest=meta_inv,
        meta_per_lead=meta_per_lead,
        meta_per_inv=meta_per_inv,
    )

    return met.as_placeholders(sufixo)
