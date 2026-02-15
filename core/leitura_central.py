# -*- coding: utf-8 -*-
"""core.leitura_central

Lê a **Planilha Central**, cria instâncias `Cliente`
e já grava o STATUS (AUTO) quando necessário.

Melhorias nesta versão
----------------------
1. Função `_update_status_cell()` compartilhada para escrever na planilha.
2. Marca “IGNORADO” sempre que GERAR? = FALSE.
3. Guarda metadados da célula STATUS em `cliente.extras`
   (_sheet_id, _tab, _row, _status_idx).
4. Guarda também a posição da coluna **ULTIMA VEZ GERADO (AUTO)**
   (_lastgen_idx) para permitir atualização da data após sucesso.
5. **Encerra a leitura assim que encontra a primeira linha cujo campo
   CLIENTE esteja vazio** – evita percorrer linhas além do fim lógico
   dos dados.
6. **Suporte a CATEGORIA**: lê a nova coluna e popula `cliente.categoria`.
   Se a célula estiver vazia, escreve "SEM CATEGORIA" em STATUS e ignora
   o cliente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List
import json
import re

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import google.auth

from config import settings  # type: ignore
from utils.logger import get_logger  # type: ignore

from googleapiclient.discovery import build
from utils.retry import execute_with_retries

from core.cred_manager import load_google_account
from utils.sheets import a1_range, resolve_sheet_title

# ──────────────────────────────────────────────────────────────────────────────
# Constantes & logger
# ──────────────────────────────────────────────────────────────────────────────
log = get_logger(__name__)

COL_GERAR    = "GERAR?"
COL_CLIENTE  = "CLIENTE"
COL_CATEGORIA = "CATEGORIA"  # NOVA COLUNA
COL_PAINEL   = "LINK PAINEL DE CONTROLE"
COL_PASTA    = "LINK PASTA"
COL_IDGOOGLE = "ID GOOGLE ADS"
COL_IDMETA   = "ID META ADS"
COL_IDGA4    = "ID GA4"
COL_STATUS   = "STATUS (AUTO)"
COL_LASTGEN  = "ULTIMA VEZ GERADO (AUTO)"

__all__ = [
    "Cliente",
    "fetch_clientes",
    "_get_sheets_service",
    "_update_status_cell",
]

# ──────────────────────────────────────────────────────────────────────────────
# Dataclass de domínio
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Cliente:
    nome: str
    categoria: str  # NOVO ATRIBUTO
    painel_url: str
    pasta_url: str
    id_google_ads: str
    id_meta_ads: str
    id_ga4: str
    email: str | None = None  # reservado para futuro
    extras: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.nome = self.nome.strip()
        self.categoria = self.categoria.strip()
        self.painel_url = self.painel_url.strip()
        self.pasta_url = self.pasta_url.strip()
        self.id_google_ads = self.id_google_ads.strip()
        self.id_meta_ads = self.id_meta_ads.strip()
        self.id_ga4 = self.id_ga4.strip()


def _get_sheets_service():
    """Instancia o client Sheets usando as *credenciais padrão*."""
    return build(
        "sheets",
        "v4",
        credentials=load_google_account(),
        cache_discovery=False,
    )

# ──────────────────────────────────────────────────────────────────────────────
# Helpers de escrita
# ──────────────────────────────────────────────────────────────────────────────
def _col_to_letter(idx: int) -> str:
    """0 → A, 1 → B, … 26 → AA etc."""
    s = ""
    while idx >= 0:
        s = chr(idx % 26 + 65) + s
        idx = idx // 26 - 1
    return s


def _update_status_cell(
    service,
    spreadsheet_id: str,
    tab_name: str,
    row_1based: int,
    col_idx_0based: int,
    value: str,
) -> None:
    """
    Escreve *value* na célula indicada.
    Apesar do nome, serve para qualquer coluna de atualização automática.
    """
    cell = a1_range(tab_name, f"{_col_to_letter(col_idx_0based)}{row_1based}")
    body = {"values": [[value]]}
    execute_with_retries(
        lambda: service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=cell,
            valueInputOption="RAW",
            body=body,
        ).execute(),
        logger=log,
        context=f"sheets.values().update ({cell})"
    )
    log.info("Célula %s atualizada p/ '%s'", cell, value)

# ──────────────────────────────────────────────────────────────────────────────
# Sheets helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_values(spreadsheet_id: str, tab_name: str) -> List[List[str]]:
    service = _get_sheets_service()
    tab_name = resolve_sheet_title(service, spreadsheet_id, tab_name, logger=log)
    range_a1 = a1_range(tab_name, "A:ZZZ")
    resp = execute_with_retries(
        lambda: service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_a1)
            .execute(),
        logger=log,
        context=f"sheets.values().get ({range_a1})"
    )
    return resp.get("values", [])

# ──────────────────────────────────────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────────────────────────────────────

def _parse_header(row: List[str]) -> dict[str, int]:
    return {c.strip().upper(): i for i, c in enumerate(row)}


def _needs_update(flag: str) -> bool:
    return str(flag).strip().upper() in {"1", "TRUE", "SIM", "YES", "Y"}


def _parse_rows(
    rows: Iterable[List[str]],
    only: str | None,
    spreadsheet_id: str,
    tab_name: str,
) -> List[Cliente]:
    rows = list(rows)
    if not rows:
        return []

    header_map = _parse_header(rows[0])
    missing = [
        c
        for c in (
            COL_GERAR,
            COL_CLIENTE,
            COL_CATEGORIA,  # ← garante coluna obrigatória
            COL_PAINEL,
            COL_PASTA,
            COL_IDGOOGLE,
            COL_IDMETA,
            COL_IDGA4,
        )
        if c not in header_map
    ]
    if missing:
        raise KeyError(f"Colunas obrigatórias ausentes: {', '.join(missing)}")

    status_idx   = header_map.get(COL_STATUS)
    lastgen_idx  = header_map.get(COL_LASTGEN)
    service = _get_sheets_service()

    clientes: List[Cliente] = []
    status_updates = []  # Acumula atualizações de STATUS
    for excel_row, row in enumerate(rows[1:], start=2):  # 2 = header + 1
        row += [""] * (len(header_map) - len(row))

        if row[header_map[COL_CLIENTE]].strip() == "":
            log.info("Linha %d cliente vazio — fim lógico da planilha.", excel_row)
            break

        gerar = _needs_update(row[header_map[COL_GERAR]])

        # Atualiza STATUS quando não gerar
        if not gerar:
            if (
                status_idx is not None
                and row[status_idx].strip().upper() != "IGNORADO"
            ):
                cell = a1_range(tab_name, f"{_col_to_letter(status_idx)}{excel_row}")
                status_updates.append({"range": cell, "values": [["IGNORADO"]]})
            continue

        categoria_cell = row[header_map[COL_CATEGORIA]].strip()
        if categoria_cell == "":
            # Marca erro e ignora
            if (
                status_idx is not None
                and row[status_idx].strip().upper() != "SEM CATEGORIA"
            ):
                cell = a1_range(tab_name, f"{_col_to_letter(status_idx)}{excel_row}")
                status_updates.append({"range": cell, "values": [["SEM CATEGORIA"]]})
            log.warning(
                "Cliente '%s' linha %d sem categoria — ignorado.",
                row[header_map[COL_CLIENTE]].strip(),
                excel_row,
            )
            continue

        nome = row[header_map[COL_CLIENTE]].strip()
        if only and only.lower() not in nome.lower():
            continue

        cliente = Cliente(
            nome=nome,
            categoria=categoria_cell,
            painel_url=row[header_map[COL_PAINEL]].strip(),
            pasta_url=row[header_map[COL_PASTA]].strip(),
            id_google_ads=row[header_map[COL_IDGOOGLE]].strip(),
            id_meta_ads=row[header_map[COL_IDMETA]].strip(),
            id_ga4=row[header_map[COL_IDGA4]].strip(),
            extras={
                "_sheet_id": spreadsheet_id,
                "_tab": tab_name,
                "_row": excel_row,
                "_status_idx": status_idx,
                "_lastgen_idx": lastgen_idx,
                **{
                    k: row[idx].strip()
                    for k, idx in header_map.items()
                    if k
                    not in {
                        COL_GERAR,
                        COL_CLIENTE,
                        COL_CATEGORIA,
                        COL_PAINEL,
                        COL_PASTA,
                        COL_STATUS,
                        COL_LASTGEN,
                    }
                },
            },
        )
        clientes.append(cliente)

    # Realiza todas as atualizações de STATUS em lote
    if status_updates:
        try:
            execute_with_retries(
                lambda: service.spreadsheets().values().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"data": status_updates, "valueInputOption": "RAW"}
                ).execute(),
                logger=log,
                context=f"sheets.values().batchUpdate ({tab_name})"
            )
            for upd in status_updates:
                log.info("Célula %s atualizada p/ '%s' (batch)", upd["range"], upd["values"][0][0])
        except Exception as e:
            log.error("Erro ao atualizar células em lote: %s", e)

    return clientes

# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def parse_sheet_id(url: str) -> str:
    m = re.search(r"/d/([^/]+)/", url)
    if not m:
        raise ValueError(f"URL inválida: {url}")
    return m.group(1)


def fetch_clientes(
    *,
    atualizar: bool = True,
    only: str | None = None,
    sheet_url: str,
    tab_name: str,
) -> List[Cliente]:
    spreadsheet_id = parse_sheet_id(sheet_url)
    rows = _fetch_values(spreadsheet_id, tab_name)

    if atualizar:
        clientes = _parse_rows(rows, only, spreadsheet_id, tab_name)
    else:
        header_map = _parse_header(rows[0])
        status_idx = header_map.get(COL_STATUS)
        lastgen_idx = header_map.get(COL_LASTGEN)
        if COL_CATEGORIA not in header_map:
            raise KeyError("Coluna CATEGORIA ausente na planilha.")

        clientes = []
        for i, r in enumerate(rows[1:], start=2):
            r += [""] * (len(header_map) - len(r))
            if r[header_map[COL_CLIENTE]].strip() == "":
                break
            if only and only.lower() not in r[header_map[COL_CLIENTE]].lower():
                continue

            categoria_cell = r[header_map[COL_CATEGORIA]].strip()
            if categoria_cell == "":
                # Sem categoria — pula sem alterar STATUS, pois `atualizar=False`
                continue
            clientes.append(
                Cliente(
                    nome=r[header_map[COL_CLIENTE]].strip(),
                    categoria=categoria_cell,
                    painel_url=r[header_map[COL_PAINEL]].strip(),
                    pasta_url=r[header_map[COL_PASTA]].strip(),
                    id_google_ads=r[header_map[COL_IDGOOGLE]].strip(),
                    id_meta_ads=r[header_map[COL_IDMETA]].strip(),
                    id_ga4=r[header_map[COL_IDGA4]].strip(),
                    extras={
                        "_sheet_id": spreadsheet_id,
                        "_tab": tab_name,
                        "_row": i,
                        "_status_idx": status_idx,
                        "_lastgen_idx": lastgen_idx,
                        "_header_map": header_map,
                        COL_STATUS: r[status_idx].strip() if status_idx is not None else "",
                        COL_LASTGEN: r[lastgen_idx].strip() if lastgen_idx is not None else "",
                        **{
                            k: r[idx].strip()
                            for k, idx in header_map.items()
                            if k not in {
                                COL_GERAR, COL_CLIENTE, COL_CATEGORIA,
                                COL_PAINEL, COL_PASTA, COL_IDGOOGLE,
                                COL_IDMETA, COL_IDGA4, COL_STATUS, COL_LASTGEN,
                            }
                        },
                    },
                )
            )

    # Log final
    if clientes:
        categorias = {c.categoria for c in clientes}
        log.info("%d cliente(s) encontrados — categorias: %s", len(clientes), ", ".join(sorted(categorias)))
    else:
        log.info("Nenhum cliente elegível encontrado.")
    return clientes
