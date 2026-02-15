# -*- coding: utf-8 -*-
"""core/relatorio_writer.py
Gera e escreve linhas na planilha de acompanhamento dos relatórios
semanais a partir do template definido em ``settings.TEMPLATE_RELATORIO_ID``.
"""

from __future__ import annotations

from typing import Any, Dict, List
import threading

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from core.cred_manager import load_google_account
from utils.logger import get_logger  # type: ignore
from datetime import datetime
from utils.retry import execute_with_retries  # NOVO IMPORT

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Função de Criação da planilha de acompanhamento
# ---------------------------------------------------------------------------
def criar_planilha_relatorio() -> str:
    """
    Cria uma nova planilha de acompanhamento a partir do template e retorna o spreadsheetId.
    Nome no formato '{MM/DD (HHh MMmin)} – Relatório de Geração de Report'.
    """
    from config import settings  # local import para evitar circular
    from config.settings import TESTE

    drive = build("drive", "v3", credentials=load_google_account(), cache_discovery=False)
    nome_final = f"{datetime.now().strftime('%m/%d (%Hh %Mmin)')} – Relatório de Geração de Report"
    folder_id = settings.RELATORIO_FOLDER_ID

    if TESTE:
        # Cria/busca pasta 'Testes' dentro da pasta de relatórios
        teste_query = (
            f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' "
            f"and name='Testes' and trashed=false"
        )
        teste_resp = execute_with_retries(
            lambda: drive.files()
                .list(
                    q=teste_query,
                    spaces="drive",
                    fields="files(id)",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                )
                .execute(),
            logger=log,
            context="drive.files().list(Testes)"
        )
        if teste_resp.get("files"):
            dest_folder_id = teste_resp["files"][0]["id"]
        else:
            teste_folder = execute_with_retries(
                lambda: drive.files()
                    .create(
                        body={
                            "name": "Testes",
                            "mimeType": "application/vnd.google-apps.folder",
                            "parents": [folder_id],
                        },
                        fields="id",
                        supportsAllDrives=True,
                    )
                    .execute(),
                logger=log,
                context="drive.files().create(Testes)"
            )
            dest_folder_id = teste_folder["id"]
    else:
        dest_folder_id = folder_id

    try:
        copy = execute_with_retries(
            lambda: drive.files()
                .copy(
                    fileId=settings.TEMPLATE_RELATORIO_ID,
                    body={"name": nome_final, "parents": [dest_folder_id]},
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute(),
            logger=log,
            context="drive.files().copy(template relatório)"
        )
        spreadsheet_id = copy["id"]
        log.info(
            "Planilha de acompanhamento criada",
            extra={"cliente": "-", "doc": spreadsheet_id},
        )
        return spreadsheet_id
    except HttpError:
        log.exception(
            "Falha ao criar planilha de acompanhamento",
            extra={"cliente": "-", "doc": "-"},
        )
        raise

# ---------------------------------------------------------------------------
# Planilha já criada! Só cache do ID
# ---------------------------------------------------------------------------
_cached_ss_id: str | None = None

def set_planilha_id(ss_id: str) -> None:
    """Seta o id da planilha criada no início da execução (chamado pelo main)."""
    global _cached_ss_id
    _cached_ss_id = ss_id

def get_planilha_id() -> str:
    """Retorna o id já definido; lança erro se não foi inicializado."""
    global _cached_ss_id
    if not _cached_ss_id:
        raise RuntimeError("ID da planilha de acompanhamento não foi inicializado!")
    return _cached_ss_id

# ---------------------------------------------------------------------------
# Sheets Service (thread-local, thread-safe)
# ---------------------------------------------------------------------------
_thread_local = threading.local()

def _sheets_service():
    if not hasattr(_thread_local, "sheets_service"):
        _thread_local.sheets_service = build(
            "sheets", "v4", credentials=load_google_account(), cache_discovery=False
        )
    return _thread_local.sheets_service

# ---------------------------------------------------------------------------
# Lock para serializar o append (evita race em ambientes Windows ou APIs instáveis)
# ---------------------------------------------------------------------------
_append_lock = threading.Lock()

def _append_row(ss_id: str, valores: List[str]) -> None:
    with _append_lock:
        sheets = _sheets_service()
        body: Dict[str, Any] = {"values": [valores]}
        execute_with_retries(
            lambda: sheets.spreadsheets().values().append(
                spreadsheetId=ss_id,
                range="A2:F",
                valueInputOption="USER_ENTERED",
                insertDataOption="OVERWRITE",
                body=body,
            ).execute(),
            logger=log,
            context="sheets.spreadsheets().values().append"
        )

# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def registrar(cliente, presentation_id: str, status: str) -> None:
    """Adiciona uma linha na planilha de acompanhamento.
    Os links são inseridos como fórmulas HYPERLINK.
    """
    ss_id = get_planilha_id()

    link_pasta = (
        f'=HYPERLINK("{cliente.pasta_url}"; "Link Pasta {cliente.nome}")'
        if getattr(cliente, "pasta_url", None) else "-"
    )
    link_report = (
        f'=HYPERLINK("https://docs.google.com/presentation/d/{presentation_id}/edit"; '
        f'"Report {cliente.nome}")'
    )

    valores = [
        getattr(cliente.extras, "get", lambda k, v="-": "-")("GESTOR", "-"),
        getattr(cliente.extras, "get", lambda k, v="-": "-")("SQUAD", "-"),
        cliente.nome,
        cliente.categoria,
        link_pasta,
        link_report,
        status,
    ]

    try:
        _append_row(ss_id, valores)
        log.info(
            "Linha adicionada ao relatório", extra={"cliente": cliente.nome, "doc": ss_id}
        )
    except HttpError:
        log.exception(
            "Falha ao registrar linha no relatório", extra={"cliente": cliente.nome, "doc": ss_id}
        )