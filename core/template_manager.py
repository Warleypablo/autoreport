# -*- coding: utf-8 -*-
"""core/template_manager – gerencia cópia do template.

Agora remove apresentações antigas com o mesmo nome antes de copiar o novo
arquivo.
"""
from __future__ import annotations

import re
from typing import Optional, List

# Variável global para controle de testes
from config.settings import TESTE 
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from config import settings  # type: ignore
from utils.logger import get_logger  # type: ignore
from core.leitura_central import ( # type: ignore
    _get_sheets_service,
    _update_status_cell,
)  # type: ignore
from core.periodo import Periodo  # type: ignore

from googleapiclient.discovery import build
from core.cred_manager import load_google_account  # type: ignore
import threading
from utils.retry import execute_with_retries

log = get_logger(__name__)

__all__ = ["criar_copia"]

# --------------------------------------------------
# Helpers Drive
# --------------------------------------------------
_thread_local = threading.local()

def _drive_service():
    if not hasattr(_thread_local, "drive_service"):
        _thread_local.drive_service = build(
            "drive", "v3", credentials=load_google_account(), cache_discovery=False
        )
    return _thread_local.drive_service


_FOLDER_RE = re.compile(r"/folders/([A-Za-z0-9_-]{10,})")
_FILE_RE = re.compile(r"/d/([A-Za-z0-9_-]{10,})/")


def _parse_id(url: str, kind: str = "folder") -> Optional[str]:
    if not url:
        return None
    m = (_FOLDER_RE if kind == "folder" else _FILE_RE).search(url)
    return m.group(1) if m else None


# --------------------------------------------------
# STATUS helper
# --------------------------------------------------
def _set_status(cliente, msg: str):  # noqa: ANN001
    extras = getattr(cliente, "extras", {})
    sid, tab, row, col = (
        extras.get(k) for k in ("_sheet_id", "_tab", "_row", "_status_idx")
    )
    if None in {sid, tab, row, col}:
        return  # coluna STATUS não existe
    service = _get_sheets_service()
    try:
        _update_status_cell(service, sid, tab, row, col, msg)
    except HttpError as exc:
        log.error("Falha ao gravar STATUS (%s): %s", cliente.nome, exc)


# --------------------------------------------------
# Pasta destino (com fallback)
# --------------------------------------------------
def _dest_folder(cliente, folder_id: str | None, freq: str = "SEMANAL") -> str:
    service = _drive_service()
    # Se configurado, força todas as cópias para uma pasta específica
    forced = getattr(settings, "FORCE_REPORT_FOLDER_ID", "") or ""
    parent = forced or folder_id or "root"

    # 1) valida pasta-mãe
    try:
        execute_with_retries(
            lambda: service.files().get(
                fileId=parent,
                fields="id",
                supportsAllDrives=True,
            ).execute(),
            logger=log,
            context=f"drive.files().get (valida pasta-mãe: {parent})"
        )
    except HttpError as exc:
        if exc.resp.status in {403, 404}:
            _set_status(cliente, "PASTA INACESSÍVEL")
            parent = "root"
        else:
            raise

    # 2) busca/cria 'Auto Report 2025' primeiro
    ar25_query = (
        f"'{parent}' in parents and mimeType='application/vnd.google-apps.folder' "
        f"and name='Auto Report 2025' and trashed=false"
    )
    ar25_resp = execute_with_retries(
        lambda: service.files()
            .list(
                q=ar25_query,
                spaces="drive",
                fields="files(id)",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            ).execute(),
        logger=log,
        context=f"drive.files().list (Auto Report 2025 em {parent})"
    )
    if ar25_resp.get("files"):
        ar25_id = ar25_resp["files"][0]["id"]
    else:
        ar25_folder = execute_with_retries(
            lambda: service.files()
                .create(
                    body={
                        "name": "Auto Report 2025",
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": [parent],
                    },
                    fields="id",
                    supportsAllDrives=True,
                ).execute(),
            logger=log,
            context=f"drive.files().create (Auto Report 2025 em {parent})"
        )
        ar25_id = ar25_folder["id"]

    # Se for mensal, busca/cria '0. Report Mensal' dentro de 'Auto Report 2025'
    if freq.upper() == "MENSAL":
        mensal_query = (
            f"'{ar25_id}' in parents and mimeType='application/vnd.google-apps.folder' "
            f"and name='0. Report Mensal' and trashed=false"
        )
        mensal_resp = execute_with_retries(
            lambda: service.files()
                .list(
                    q=mensal_query,
                    spaces="drive",
                    fields="files(id)",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                ).execute(),
            logger=log,
            context=f"drive.files().list (0. Report Mensal em {ar25_id})"
        )
        if mensal_resp.get("files"):
            mensal_id = mensal_resp["files"][0]["id"]
        else:
            mensal_folder = execute_with_retries(
                lambda: service.files()
                    .create(
                        body={
                            "name": "0. Report Mensal",
                            "mimeType": "application/vnd.google-apps.folder",
                            "parents": [ar25_id],
                        },
                        fields="id",
                        supportsAllDrives=True,
                    ).execute(),
                logger=log,
                context=f"drive.files().create (0. Report Mensal em {ar25_id})"
            )
            mensal_id = mensal_folder["id"]
        # Se TESTE, busca/cria pasta 'Testes' dentro de '0. Report Mensal'
        if TESTE:
            teste_query = (
                f"'{mensal_id}' in parents and mimeType='application/vnd.google-apps.folder' "
                f"and name='Testes' and trashed=false"
            )
            teste_resp = execute_with_retries(
                lambda: service.files()
                    .list(
                        q=teste_query,
                        spaces="drive",
                        fields="files(id)",
                        includeItemsFromAllDrives=True,
                        supportsAllDrives=True,
                    ).execute(),
                logger=log,
                context=f"drive.files().list (Testes em {mensal_id})"
            )
            if teste_resp.get("files"):
                return teste_resp["files"][0]["id"]
            teste_folder = execute_with_retries(
                lambda: service.files()
                    .create(
                        body={
                            "name": "Testes",
                            "mimeType": "application/vnd.google-apps.folder",
                            "parents": [mensal_id],
                        },
                        fields="id",
                        supportsAllDrives=True,
                    ).execute(),
                logger=log,
                context=f"drive.files().create (Testes em {mensal_id})"
            )
            return teste_folder["id"]
        else:
            return mensal_id
    else:
        # Se TESTE, busca/cria pasta 'Testes' dentro de 'Auto Report 2025'
        if TESTE:
            teste_query = (
                f"'{ar25_id}' in parents and mimeType='application/vnd.google-apps.folder' "
                f"and name='Testes' and trashed=false"
            )
            teste_resp = execute_with_retries(
                lambda: service.files()
                    .list(
                        q=teste_query,
                        spaces="drive",
                        fields="files(id)",
                        includeItemsFromAllDrives=True,
                        supportsAllDrives=True,
                    ).execute(),
                logger=log,
                context=f"drive.files().list (Testes em {ar25_id})"
            )
            if teste_resp.get("files"):
                return teste_resp["files"][0]["id"]
            teste_folder = execute_with_retries(
                lambda: service.files()
                    .create(
                        body={
                            "name": "Testes",
                            "mimeType": "application/vnd.google-apps.folder",
                            "parents": [ar25_id],
                        },
                        fields="id",
                        supportsAllDrives=True,
                    ).execute(),
                logger=log,
                context=f"drive.files().create (Testes em {ar25_id})"
            )
            return teste_folder["id"]
        else:
            return ar25_id


# --------------------------------------------------
# Remove arquivos duplicados
# --------------------------------------------------
def _delete_existing_by_name(
    parent_id: str, filename: str, mime: str = "application/vnd.google-apps.presentation"
) -> List[str]:
    service = _drive_service()
    query = (
        f"'{parent_id}' in parents and name='{filename}' and trashed=false "
        f"and mimeType='{mime}'"
    )
    resp = execute_with_retries(
        lambda: service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id)",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            ).execute(),
        logger=log,
        context=f"drive.files().list (duplicatas: {filename} em {parent_id})"
    )
    deleted_ids: List[str] = []
    files = resp.get("files", [])
    if not files:
        return deleted_ids
    def delete_file(file_id):
        try:
            execute_with_retries(
                lambda: service.files().delete(
                    fileId=file_id, supportsAllDrives=True
                ).execute(),
                logger=log,
                context=f"drive.files().delete ({file_id})"
            )
            return file_id
        except HttpError as exc:
            log.warning("Não foi possível apagar duplicata %s: %s", file_id, exc)
            return None
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=min(8, len(files))) as executor:
        futures = [executor.submit(delete_file, f["id"]) for f in files]
        for future in as_completed(futures):
            result = future.result()
            if result:
                deleted_ids.append(result)
    return deleted_ids


# --------------------------------------------------
# Copia template (criando versão)
# --------------------------------------------------
def _copy(
    dest_folder_id: str,
    periodo: Periodo,
    cliente,                     # noqa: ANN001
    template_id: str | None = None,
    freq: str = "SEMANAL",
) -> str:
    service = _drive_service()

    if freq.upper() == "MENSAL":
        meses_pt = [
            "janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
        ]
        mes_idx = periodo.fim.month - 1
        mes_nome = meses_pt[mes_idx].capitalize()
        base_name = f"{mes_nome} - Report Mensal {cliente.nome} V"
        query = (
            f"'{dest_folder_id}' in parents "
            f"and name contains '{base_name}' "
            f"and mimeType='application/vnd.google-apps.presentation' "
            "and trashed=false"
        )
        resp = execute_with_retries(
            lambda: service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="files(name)",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                ).execute(),
            logger=log,
            context=f"drive.files().list (versão mensal: {base_name} em {dest_folder_id})"
        )
        max_version = 0
        version_re = re.compile(rf'^{re.escape(base_name)}(\d+)$')
        for f in resp.get("files", []):
            m = version_re.match(f.get("name", ""))
            if m:
                try:
                    v = int(m.group(1))
                    max_version = max(max_version, v)
                except ValueError:
                    continue
        nova_versao = max_version + 1
        nome_final = f"{base_name}{nova_versao}"
    else:
        base_name = f"{periodo.fim_plus_1:%m/%d} - Report Semanal {cliente.nome} V"
        query = (
            f"'{dest_folder_id}' in parents "
            f"and name contains '{base_name}' "
            f"and mimeType='application/vnd.google-apps.presentation' "
            "and trashed=false"
        )
        resp = execute_with_retries(
            lambda: service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="files(name)",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                ).execute(),
            logger=log,
            context=f"drive.files().list (versão semanal: {base_name} em {dest_folder_id})"
        )
        max_version = 0
        version_re = re.compile(rf'^{re.escape(base_name)}(\d+)$')
        for f in resp.get("files", []):
            m = version_re.match(f.get("name", ""))
            if m:
                try:
                    v = int(m.group(1))
                    max_version = max(max_version, v)
                except ValueError:
                    continue
        nova_versao = max_version + 1
        nome_final = f"{base_name}{nova_versao}"

    template_or_default = template_id or settings.TEMPLATE_PRESENTATION_ID
    copy = execute_with_retries(
        lambda: service.files()
            .copy(
                fileId=template_or_default,
                body={"name": nome_final, "parents": [dest_folder_id]},
                fields="id",
                supportsAllDrives=True,
            ).execute(),
        logger=log,
        context=f"drive.files().copy (template: {template_or_default} → {dest_folder_id}, nome: {nome_final})"
    )
    return copy["id"]

# --------------------------------------------------
# API pública
# --------------------------------------------------
def criar_copia(
    cliente,                # noqa: ANN001
    periodo: Periodo,
    *,
    template_id: str | None = None,
    FREQ: str = "SEMANAL",
) -> str:
    folder_id = _parse_id(cliente.pasta_url, "folder")
    dest = _dest_folder(cliente, folder_id, freq=FREQ)
    pres_id = _copy(dest, periodo, cliente, template_id=template_id, freq=FREQ)
    # Logging assíncrono para não bloquear
    def log_async():
        try:
            log.info("Template copiado", extra={"cliente": cliente.nome, "doc": pres_id})
        except Exception:
            pass
    threading.Thread(target=log_async, daemon=True).start()
    return pres_id
