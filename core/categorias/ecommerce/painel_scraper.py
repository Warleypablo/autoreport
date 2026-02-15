from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utils.logger import get_logger  # type: ignore
from core.periodo import Periodo  # type: ignore
from core.cred_manager import load_google_account  # type: ignore
from googleapiclient.discovery import build
from core.status import set_status  # type: ignore

from utils.formatting import _fmt_brl, _fmt_percent, _to_float_br, _fmt_roas, _fmt_int, _DEF_DASH, _MONTH_PT
from utils.retry import execute_with_retries

import re
from utils.sheets import a1_range, resolve_sheet_title

log = get_logger(__name__)

__all__ = ["parse_sheet_id", "coletar_metricas"]

# ---------------------------------------------------------------------------
# Helpers Google Sheets
# ---------------------------------------------------------------------------

def _build_sheets_service():
    """Client Sheets autenticado com a credencial do Google Account (Sheets/Drive)."""
    return build(
        "sheets",
        "v4",
        credentials=load_google_account(),
        cache_discovery=False,
    )

# ---------------------------------------------------------------------------
# Regex – extrai o *spreadsheetId* da URL
# ---------------------------------------------------------------------------

_RE_SHEET_ID = re.compile(r"/d/([a-zA-Z0-9-_]+)")


def parse_sheet_id(url: str) -> str:
    m = _RE_SHEET_ID.search(url)
    if not m:
        raise ValueError(f"URL de planilha inválida: {url}")
    return m.group(1)

# ---------------------------------------------------------------------------
# Download DataFrame com fallback de aba
# ---------------------------------------------------------------------------

def _fetch_dataframe(spreadsheet_id: str, tab_name: str = "Acompanhamento Geral") -> pd.DataFrame:
    import time
    service = _build_sheets_service()
    tab_name = resolve_sheet_title(service, spreadsheet_id, tab_name, logger=log)
    max_retries = 5
    delay = 2
    for attempt in range(max_retries):
        try:
            range_a1 = a1_range(tab_name, "A:ZZZ")
            resp = execute_with_retries(
                lambda: service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=range_a1
                ).execute(),
                logger=log,
                context=f"sheets.values().get ({spreadsheet_id}, {range_a1})"
            )
            break
        except HttpError as exc:
            # Aba não encontrada → tenta primeira aba existente
            if exc.resp.status == 400 and "Unable to parse range" in str(exc):
                meta = execute_with_retries(
                    lambda: service.spreadsheets().get(
                        spreadsheetId=spreadsheet_id,
                        fields="sheets.properties.title"
                    ).execute(),
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
                    lambda: service.spreadsheets().values().get(
                        spreadsheetId=spreadsheet_id,
                        range=range_first
                    ).execute(),
                    logger=log,
                    context=f"sheets.values().get ({spreadsheet_id}, {range_first})"
                )
                break
            elif exc.resp.status == 503:
                log.warning(f"Sheets API 503 (rate limit) – tentativa {attempt+1}/{max_retries}. Aguarde {delay}s...")
                time.sleep(delay)
                delay *= 2
                continue
            else:
                raise
    else:
        raise RuntimeError(f"Sheets API 503 – excedido número máximo de tentativas ({max_retries})")

    values: List[List[str]] = resp.get("values", [])
    if not values:
        raise RuntimeError("Planilha vazia ou aba sem dados.")

    header, *rows = values
    n_cols = len(header)
    rows = [r + [""] * (n_cols - len(r)) for r in rows]
    return pd.DataFrame(rows, columns=header)

# ---------------------------------------------------------------------------
# Dataclass resultado (placeholders)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _Metricas:
    faturamento_semana: Optional[float] = None
    faturamento_mes: Optional[float] = None
    investimento_semana: Optional[float] = None
    investimento_mes: Optional[float] = None
    pedidos_semana: Optional[int] = None
    sessoes_semana: Optional[int] = None
    roas: Optional[float] = None
    taxa_conversao: Optional[float] = None  # decimal (0.034)
    ticket_medio: Optional[float] = None
    custo_por_sessao: Optional[float] = None
    meta_fat: Optional[float] = None
    meta_invest: Optional[float] = None
    meta_per_fat: Optional[float] = None  # decimal
    meta_per_inv: Optional[float] = None  # decimal
    cpa_semana: Optional[float] = None #Novo

    def as_placeholders(self, sufixo: str="") -> Dict[str, str]:
        """Converte as métricas em valores de placeholder prontos para Slides."""
        return {
            f"{{{{fat_sem{sufixo}}}}}":    _fmt_brl(self.faturamento_semana),
            f"{{{{fat_mes{sufixo}}}}}":    _fmt_brl(self.faturamento_mes),
            f"{{{{inv_sem{sufixo}}}}}":    _fmt_brl(self.investimento_semana),
            f"{{{{inv_mes{sufixo}}}}}":    _fmt_brl(self.investimento_mes),
            f"{{{{vendas{sufixo}}}}}":     _fmt_int(self.pedidos_semana),
            f"{{{{roas{sufixo}}}}}":       _fmt_roas(self.roas) if self.roas is not None else _DEF_DASH,
            f"{{{{taxa_conv{sufixo}}}}}":  _fmt_percent(self.taxa_conversao),
            f"{{{{tck_med{sufixo}}}}}":    _fmt_brl(self.ticket_medio, 2),
            f"{{{{cps{sufixo}}}}}":        _fmt_brl(self.custo_por_sessao, 2),
            f"{{{{meta_fat{sufixo}}}}}":   _fmt_brl(self.meta_fat),
            f"{{{{meta_inv{sufixo}}}}}":   _fmt_brl(self.meta_invest),
            f"{{{{per_meta_fat{sufixo}}}}}":_fmt_percent(self.meta_per_fat),
            f"{{{{per_meta_inv{sufixo}}}}}":_fmt_percent(self.meta_per_inv),
            f"{{{{cpa{sufixo}}}}}":        _fmt_brl(self.cpa_semana, 2) if self.cpa_semana is not None else _DEF_DASH,
        }

# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def coletar_metricas(cliente, periodo: Periodo, sufixo: str = "", aba: str = "Acompanhamento Geral") -> Dict[str, str]:
    """Baixa métricas do Painel de Controle e devolve placeholders prontos.

    * **Semana**: intervalo fechado [periodo.inicio, periodo.fim].
    * **Mês**: utiliza a linha‑síntese (JANEIRO…)
      – se ausente, soma do dia 1 até periodo.fim como fallback.
    """

    placeholders: Dict[str, str] = {}         # ← inicializa placeholders fora do try

    # 1) Valida URL
    try:
        sheet_id = parse_sheet_id(cliente.painel_url)
    except ValueError as exc:
        log.error("URL Painel inválida (%s): %s", cliente.nome, exc)
        set_status(cliente, "PAINEL URL INVÁLIDA")
        return {}

    # 2) Baixa DataFrame
    try:
        df = _fetch_dataframe(sheet_id, aba)
    except Exception as exc:  # noqa: BLE001
        log.error("Sheets API falhou (%s): %s", cliente.nome, exc)
        set_status(cliente, "ERRO SHEETS")
        return {}

    # 3) Validação de colunas mínimas
    required_cols = {"DATA", "VALOR INVESTIDO", "FATURAMENTO", "PEDIDOS", "SESSÕES"}
    missing = required_cols - set(df.columns)
    if missing:
        msg = f"Aba sem colunas obrigatórias: {', '.join(missing)} – {cliente.nome}"
        log.error(msg)
        set_status(cliente, "ERRO CABEÇALHO")
        # Aqui lança a exceção para interromper o processamento
        raise ValueError(msg)

    # 4) Prepara coluna de texto original antes da conversão
    # ------------------------------------------------------
    df["DATA_TXT"] = df["DATA"].astype(str).str.strip().str.upper()
    df["DATA"] = (
    pd.to_datetime(df["DATA"].astype(str).str.strip(),      # limpa espaços
                   format="%d/%m/%Y",
                   dayfirst=True,                           # dd/mm/yyyy
                   errors="coerce")
      .dt.normalize()                                       # zera horário
      .dt.date                                              # → datetime.date
      )

    # 5) Conversões de valores numéricos (BRL / int / float)
    # ------------------------------------------------------
    numeric_cols = [
        "VALOR INVESTIDO",
        "FATURAMENTO",
        "PEDIDOS",
        "SESSÕES",
        "TAXA DE CONVERSÃO",
        "TICKET MÉDIO",
        "META INVESTIMENTO",
        "META FATURAMENTO",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].apply(_to_float_br)

    # Helpers ---------------------------------------------------------------
    def _sum(s: pd.Series) -> Optional[float]:
        s_non_null = s.dropna()
        return None if s_non_null.empty else float(s_non_null.sum())

    def _first_non_null(s: pd.Series) -> Optional[float]:
        s_non_null = s.dropna()
        return None if s_non_null.empty else float(s_non_null.iloc[0])

    # 6) Segmentação — intervalo móvel definido em `Periodo`
    inicio_periodo = periodo.inicio   # ontem-6
    fim_periodo    = periodo.fim      # ontem

    # mantém apenas linhas com DATA não nula e dentro do intervalo desejado
    linhas_validas = df["DATA"].notna()
    semana = df[linhas_validas & df["DATA"].between(inicio_periodo, fim_periodo, inclusive="both")]

    # 7) Segmentação — mês (linha-síntese) ----------------------------------
    nome_mes = _MONTH_PT[periodo.fim.month]
    linha_mes = df[df["DATA"].isna() & (df["DATA_TXT"] == nome_mes)]

    if not linha_mes.empty:
        # Usa a linha-síntese
        fat_mes = _first_non_null(linha_mes["FATURAMENTO"])
        inv_mes = _first_non_null(linha_mes["VALOR INVESTIDO"])
        meta_fat = _first_non_null(linha_mes.get("META FATURAMENTO", pd.Series(dtype=float)))
        meta_inv = _first_non_null(linha_mes.get("META INVESTIMENTO", pd.Series(dtype=float)))
    else:
        # Fallback: soma do 1º dia até hoje
        mes = df[df["DATA"].between(periodo.inicio.replace(day=1), periodo.fim)]
        fat_mes = _sum(mes["FATURAMENTO"])
        inv_mes = _sum(mes["VALOR INVESTIDO"])
        meta_fat = _first_non_null(mes.get("META FATURAMENTO", pd.Series(dtype=float)))
        meta_inv = _first_non_null(mes.get("META INVESTIMENTO", pd.Series(dtype=float)))

    # 8) Agregações da semana ----------------------------------------------
    fat_semana = _sum(semana["FATURAMENTO"])
    inv_semana = _sum(semana["VALOR INVESTIDO"])
    pedidos_semana = _sum(semana["PEDIDOS"])
    sessoes_semana = _sum(semana["SESSÕES"])

    cpa_semana = (
        None if (inv_semana is None or pedidos_semana is None or pedidos_semana == 0)
        else inv_semana / pedidos_semana)
    
    roas_semana = (
        None if (inv_semana is None or inv_semana == 0 or fat_semana is None)
        else fat_semana / inv_semana)

    taxa_conv = (
        None if (sessoes_semana is None or sessoes_semana == 0 or pedidos_semana is None)
        else pedidos_semana / sessoes_semana)

    ticket_medio = (
        None if (pedidos_semana is None or pedidos_semana == 0 or fat_semana is None)
        else fat_semana / pedidos_semana)

    custo_por_sessao = (
        None if (sessoes_semana is None or sessoes_semana == 0 or inv_semana is None)
        else inv_semana / sessoes_semana)

    # 9) Percentuais de meta -------------------------------------------------
    meta_per_fat = (
        None if (fat_mes is None or fat_mes == 0 or meta_fat is None)
        else fat_mes / meta_fat)
    
    meta_per_inv = (
        None if (inv_mes is None or inv_mes == 0 or meta_inv is None)
        else  inv_mes / meta_inv)

    # 10) Empacota tudo ------------------------------------------------------
    met = _Metricas(
        faturamento_semana=fat_semana,
        faturamento_mes=fat_mes,
        investimento_semana=inv_semana,
        investimento_mes=inv_mes,
        pedidos_semana=int(pedidos_semana) if pedidos_semana is not None else None,
        sessoes_semana=int(sessoes_semana) if sessoes_semana is not None else None,
        roas=roas_semana,
        taxa_conversao=taxa_conv,
        ticket_medio=ticket_medio,
        custo_por_sessao=custo_por_sessao,
        meta_fat=meta_fat,
        meta_invest=meta_inv,
        meta_per_fat=meta_per_fat,
        meta_per_inv=meta_per_inv,
        cpa_semana=cpa_semana,
    )

    # 11) Placeholders finais ---------------------------------------------
    placeholders: Dict[str, str] = {
        **met.as_placeholders(sufixo),
    }

    return placeholders
