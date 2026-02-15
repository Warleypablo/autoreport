# -*- coding: utf-8 -*-
"""Global settings for the report automation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Load environment variables from the usual locations so executar.bat / .env
# files can inject secrets without editing this module.
BASE_DIR = Path(__file__).resolve().parents[1]
_ENV_FILES = [
    BASE_DIR / ".env",
    BASE_DIR.parent / ".env",
    BASE_DIR.parent / "auto-report-main" / ".env",
]

for env_file in _ENV_FILES:
    if env_file.is_file():
        load_dotenv(env_file, override=False)


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int | None = None) -> int | None:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_list(name: str, default: List[str] | None = None, sep: str = ",") -> List[str]:
    value = os.environ.get(name)
    if value is None:
        return list(default or [])
    return [item.strip() for item in value.split(sep) if item.strip()]


def _env_path(name: str, default: str | Path = "") -> Path:
    value = os.environ.get(name)
    if value:
        return Path(value)
    if isinstance(default, Path):
        return default
    return Path(default) if default else Path()


# ---------------------------------------------------------------------------
# 1. Central spreadsheet
# ---------------------------------------------------------------------------
CENTRAL_SHEET_URL: str = _env(
    "CENTRAL_SHEET_URL",
    "https://docs.google.com/spreadsheets/d/16anfCyr7F7RpPhUAPf2A4yJYfD-S9pcaaSdfvClfHb4/edit",
)
CENTRAL_TAB_NAME: str = _env("CENTRAL_TAB_NAME", "Automacao Report")

# ---------------------------------------------------------------------------
# 2. Template files
# ---------------------------------------------------------------------------
TEMPLATE_RELATORIO_ID: str = _env(
    "TEMPLATE_RELATORIO_ID",
    "1eigUHmkHtsbjQ2g3S2Yxlg79HlxH7RdmBt91RIoXtbM",
)
RELATORIO_FOLDER_ID: str = _env(
    "RELATORIO_FOLDER_ID",
    "1q9gfYTrrHQKJ9RZMTx6cMw-Qlw4piBJv",
)

# ---------------------------------------------------------------------------
# 3a. Service account credentials
# ---------------------------------------------------------------------------
SERVICE_ACCOUNT_FILE: Path = _env_path("SERVICE_ACCOUNT_FILE")
GOOGLE_SERVICE_ACCOUNT_FILE: Path = _env_path(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    Path("credentials/conta_servico_google.json"),
)
GOOGLE_OAUTH_CLIENT_FILE: Path = _env_path("GOOGLE_OAUTH_CLIENT_FILE")
GOOGLE_TOKEN_FILE: Path = _env_path(
    "GOOGLE_TOKEN_FILE",
    Path("credentials/token_google_account.json"),
)
SCOPE_GOOGLE_ACCOUNT: List[str] = _env_list(
    "SCOPE_GOOGLE_ACCOUNT",
    default=[
        "https://www.googleapis.com/auth/analytics.readonly",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/presentations",
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    ],
)

# ---------------------------------------------------------------------------
# 3b. OAuth desktop credentials
# ---------------------------------------------------------------------------
OAUTH_CLIENT_FILE: Path = _env_path("OAUTH_CLIENT_FILE", Path("credentials/oauth_client.json"))
TOKEN_FILE: Path = _env_path("TOKEN_FILE", Path("credentials/token.json"))

# ---------------------------------------------------------------------------
# 3c. Credential selection flags
# ---------------------------------------------------------------------------
USE_SERVICE_ACCOUNT: bool = _env_bool("USE_SERVICE_ACCOUNT", False)

# ---------------------------------------------------------------------------
# 3d. GA4 dedicated credentials
# ---------------------------------------------------------------------------
GA4_SERVICE_ACCOUNT_FILE: Path = _env_path(
    "GA4_SERVICE_ACCOUNT_FILE",
    Path("credentials/conta_servico_ga4.json"),
)
GA4_OAUTH_CLIENT_FILE: Path = _env_path("GA4_OAUTH_CLIENT_FILE")
GA4_TOKEN_FILE: Path = _env_path("GA4_TOKEN_FILE", Path("credentials/token_ga4.json"))
SCOPE_GA4: List[str] = _env_list(
    "SCOPE_GA4",
    default=["https://www.googleapis.com/auth/analytics.readonly"],
)

# ---------------------------------------------------------------------------
# 4. Meta / Facebook credentials
# ---------------------------------------------------------------------------
ACCESS_TOKEN_META_SYSTEM: str = _env(
    "ACCESS_TOKEN_META_SYSTEM",
    "EAAKaZCjrNuMkBQG8f9S0wjH9vsjJFERZBqIhD5hJoViOyJGfUX1PKouZBZAHFz3NdZCIiZAi5SeQLmJASexEIhOPKIBs9VtMzB5EtntKMZCqrE8HlDIADFrqfPNNW3vs4iiJ6MFieMQoup6cskDQtLoC2oDgk5iI3RS6XSbWZBza58lJmZB94HvmY9GDjIoCfkRma",
)
ACCESS_TOKEN_META_HUMAN: str = _env(
    "ACCESS_TOKEN_META_HUMAN",
    "EAAKaZCjrNuMkBQG8f9S0wjH9vsjJFERZBqIhD5hJoViOyJGfUX1PKouZBZAHFz3NdZCIiZAi5SeQLmJASexEIhOPKIBs9VtMzB5EtntKMZCqrE8HlDIADFrqfPNNW3vs4iiJ6MFieMQoup6cskDQtLoC2oDgk5iI3RS6XSbWZBza58lJmZB94HvmY9GDjIoCfkRma",
)
ID_SYSTEM_USER: str = _env("ID_SYSTEM_USER", "61577933153988")
BUSINESS_ID_META: str = _env("BUSINESS_ID_META", "497455154418877")
APP_ID_META: str = _env("APP_ID_META", "")

# ---------------------------------------------------------------------------
# 5. Google API scopes in general
# ---------------------------------------------------------------------------
SCOPES: List[str] = _env_list(
    "SCOPES",
    default=[
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/presentations",
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    ],
)

# ---------------------------------------------------------------------------
# 6. Execution parameters
# ---------------------------------------------------------------------------
SANDBOX_MODE: bool = _env_bool("SANDBOX_MODE", False)
LOG_PATH: Path = _env_path("LOG_PATH", Path("logs"))
TZ: str = _env("TZ", "America/Sao_Paulo")

MAX_RETRIES: int = _env_int("MAX_RETRIES", 5) or 5
BACKOFF_SECONDS: int = _env_int("BACKOFF_SECONDS", 2) or 2
CLIENT_LIMIT: int | None = _env_int("CLIENT_LIMIT", None)

# ---------------------------------------------------------------------------
# Do not edit below unless you know what you are doing
# ---------------------------------------------------------------------------
__all__ = [
    # planilha central
    "CENTRAL_SHEET_URL",
    "CENTRAL_TAB_NAME",
    # templates
    "TEMPLATE_RELATORIO_ID",
    "RELATORIO_FOLDER_ID",
    # credenciais padrão
    "SERVICE_ACCOUNT_FILE",
    "OAUTH_CLIENT_FILE",
    "TOKEN_FILE",
    "USE_SERVICE_ACCOUNT",
    # credenciais GA4
    "GA4_OAUTH_CLIENT_FILE",
    "GA4_TOKEN_FILE",
    "SCOPE_GA4",
    "GA4_SERVICE_ACCOUNT_FILE",
    # escopos gerais
    "SCOPES",
    # execucao
    "SANDBOX_MODE",
    "LOG_PATH",
    "TZ",
    # tunables
    "MAX_RETRIES",
    "BACKOFF_SECONDS",
    "CLIENT_LIMIT",
]
