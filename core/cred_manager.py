# -*- coding: utf-8 -*-
"""core.cred_manager
Centraliza TODOS os carregamentos de credenciais Google.

Funções públicas
----------------
load_oauth() → credencial Sheets/Slides/Drive (scopes em settings.SCOPES)
load_google_account()     → credencial exclusiva p/ GA4   (scope em settings.SCOPE_GOOGLE_ACCOUNT)

Se precisar de novas contas (ex.: BigQuery), crie outro `load_…()` aqui.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import google.auth

from config import settings
from utils.logger import get_logger

import yaml # type: ignore
import os
from google.ads.googleads.client import GoogleAdsClient # type: ignore
# Caminho padrão (fallback legacy)
_YAML_PATH = Path(__file__).resolve().parent.parent / "credentials" / "google-ads.yaml"
_GOOGLE_ADS_CLIENT: Optional[GoogleAdsClient] = None


log = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────
def _sa_if_exists(json_path: Path, scopes: List[str]) -> Optional[Credentials]:
    if json_path.is_file():
        try:
            creds = service_account.Credentials.from_service_account_file(
                json_path, scopes=scopes
            )
            log.info("Usando Service Account: %s", json_path.name)
            return creds
        except Exception:  # noqa: BLE001
            log.warning("Service Account inválida (%s) – ignorando.", json_path)
    return None


def _oauth_if_exists(client_path: Path, token_path: Path, scopes: List[str]) -> Optional[Credentials]:
    if not client_path.is_file():
        return None

    creds: Credentials | None = None
    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(token_path, scopes=scopes)
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json())
            except Exception:  # noqa: BLE001
                log.warning("Refresh token falhou (%s); refazendo login…", token_path.name)
                creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(client_path, scopes=scopes)
        creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        log.info("Token salvo em %s", token_path)

    log.info("Usando OAuth: %s", client_path.name)
    return creds


def _adc(scopes: List[str]) -> Credentials:
    creds, _ = google.auth.default(scopes=scopes)
    log.info("Usando Application Default Credentials (ADC)")
    return creds


# ──────────────────────────────────────────────────────────────────────────────
# Funções públicas
# ──────────────────────────────────────────────────────────────────────────────
def load_oauth() -> Credentials:
    """Credencial para Sheets / Slides / Drive (escopos múltiplos)."""
    scopes = settings.SCOPES

    # 1) Service Account global (se houver)
    sa_path = Path(getattr(settings, "SERVICE_ACCOUNT_FILE", ""))
    creds = _sa_if_exists(sa_path, scopes)
    if creds:
        return creds

    # 2) OAuth “Desktop App” global
    client = Path(getattr(settings, "OAUTH_CLIENT_FILE", ""))
    token  = Path(getattr(settings, "TOKEN_FILE", "credentials/token.json"))
    creds = _oauth_if_exists(client, token, scopes)
    if creds:
        return creds

    # 3) Fallback – ADC (ex.: servidor GCE com Workload Identity)
    return _adc(scopes)


def load_google_account() -> Credentials:
    """Credencial *exclusiva* para a Analytics Data API."""
    scopes = settings.SCOPE_GOOGLE_ACCOUNT

    # 1) Service Account dedicada (caso não queira OAuth)
    sa_path = Path(getattr(settings, "GOOGLE_SERVICE_ACCOUNT_FILE", ""))
    creds = _sa_if_exists(sa_path, scopes)
    if creds:
        return creds

    # 2) OAuth dedicada ao GA4
    client = Path(settings.GOOGLE_OAUTH_CLIENT_FILE)
    token  = Path(settings.GOOGLE_TOKEN_FILE)
    creds = _oauth_if_exists(client, token, scopes)
    if creds:
        return creds

    # 3) Como último recurso, tenta ADC
    return _adc(scopes)

def _build_google_ads_client() -> GoogleAdsClient:
    global _GOOGLE_ADS_CLIENT
    if _GOOGLE_ADS_CLIENT is None:
        _GOOGLE_ADS_CLIENT = GoogleAdsClient.load_from_storage(str(_YAML_PATH))
    return _GOOGLE_ADS_CLIENT

def _build_google_ads_client_cloud() -> GoogleAdsClient:
    """
    Retorna um singleton de GoogleAdsClient procurando credenciais na ordem:

    1. GOOGLE_ADS_YAML        → conteúdo YAML completo (segreto inline)
    2. GOOGLE_ADS_YAML_PATH   → caminho para o yaml montado como arquivo
    3. _YAML_PATH             → arquivo na árvore do repositório (dev/fallback)

    Levanta FileNotFoundError se nenhuma fonte for encontrada ou inválida.
    """
    global _GOOGLE_ADS_CLIENT
    if _GOOGLE_ADS_CLIENT is not None:
        return _GOOGLE_ADS_CLIENT

    # ─── 1) Secret inline ───────────────────────────────────────
    yaml_inline = os.getenv("GOOGLE_ADS_YAML")
    if yaml_inline:
        try:
            config_dict = yaml.safe_load(yaml_inline)
            _GOOGLE_ADS_CLIENT = GoogleAdsClient.load_from_dict(config_dict)
            log.info("GoogleAdsClient carregado do env GOOGLE_ADS_YAML")
            return _GOOGLE_ADS_CLIENT
        except Exception as exc:
            log.warning("Falha ao carregar GOOGLE_ADS_YAML inline: %s", exc)

    # ─── 2) Caminho fornecido via env ───────────────────────────
    yaml_path_env = os.getenv("GOOGLE_ADS_YAML_PATH")
    if yaml_path_env and Path(yaml_path_env).is_file():
        try:
            _GOOGLE_ADS_CLIENT = GoogleAdsClient.load_from_storage(yaml_path_env)
            log.info("GoogleAdsClient carregado de GOOGLE_ADS_YAML_PATH=%s", yaml_path_env)
            return _GOOGLE_ADS_CLIENT
        except Exception as exc:
            log.warning("Falha ao carregar arquivo %s: %s", yaml_path_env, exc)

    # ─── 3) Fallback local ─────────────────────────────────────
    if _YAML_PATH.is_file():
        _GOOGLE_ADS_CLIENT = GoogleAdsClient.load_from_storage(str(_YAML_PATH))
        log.info("GoogleAdsClient carregado do fallback %s", _YAML_PATH)
        return _GOOGLE_ADS_CLIENT

    # Nada deu certo → explodir
    raise FileNotFoundError(
        "Não foi possível localizar credenciais do Google Ads.\n"
        "Verifique se uma das opções abaixo está configurada:\n"
        "  • Variável de ambiente GOOGLE_ADS_YAML (YAML inline)\n"
        "  • Variável de ambiente GOOGLE_ADS_YAML_PATH (caminho para arquivo)\n"
        f"  • Arquivo local {_YAML_PATH}"
    )