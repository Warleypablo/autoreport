# -*- coding: utf-8 -*-
"""
config/settings_cloud.py – Configuração baseada em variáveis de ambiente (para cloud/serverless).

⚠️ Defina todos os segredos como env vars ou segredos do Cloud Run Job.
"""

import os
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# Carrega variáveis do .env localizado na raiz do projeto (se existir)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

def _env(name: str, default=None, cast=None):
    val = os.environ.get(name, default)
    if isinstance(val, str) and val.strip() == "":
        val = default
    if cast and val is not None:
        try:
            return cast(val)
        except Exception:
            return default
    return val

def _cred_path(name: str, default: str) -> Path:
    """Retorna caminho absoluto para arquivo de credencial."""
    raw = os.environ.get(name)
    if isinstance(raw, str) and raw.strip():
        p = Path(raw)
        p = p if p.is_absolute() else BASE_DIR / p
        if p.is_file():
            return p
    p = Path(default)
    return p if p.is_absolute() else BASE_DIR / p

def _env_list(name: str, default=None, sep=","):
    val = os.environ.get(name)
    if val is None:
        return default or []
    return [v.strip() for v in val.split(sep)]

# ─────────────────────────────────────────────
# 1. Planilha Central de Automação
# ─────────────────────────────────────────────
CENTRAL_SHEET_URL: str = _env("CENTRAL_SHEET_URL", "https://docs.google.com/spreadsheets/d/1dl3RTYvGRN4sXQjhracg0ysAfDpLl1y75iC9TIf5mEk/edit")
CENTRAL_TAB_NAME: str = _env("CENTRAL_TAB_NAME", "Automacao-Report")

# ─────────────────────────────────────────────
# 2. Templates Google Slides e Relatório
# ─────────────────────────────────────────────
TEMPLATE_RELATORIO_ID: str = _env("TEMPLATE_RELATORIO_ID", "1eigUHmkHtsbjQ2g3S2Yxlg79HlxH7RdmBt91RIoXtbM")
RELATORIO_FOLDER_ID: str   = _env("RELATORIO_FOLDER_ID", "1O1VMxN7CL0GEWRtglmz862X85btgARTE")
# Opcional: força todas as cópias de apresentações a irem para uma única pasta
# Default já aponta para a pasta compartilhada informada.
FORCE_REPORT_FOLDER_ID: str = _env("FORCE_REPORT_FOLDER_ID", "1O1VMxN7CL0GEWRtglmz862X85btgARTE")
# Templates por categoria (permitem override via env)
TEMPLATE_ECOMMERCE: str     = _env("TEMPLATE_ECOMMERCE", "1w1v0ZxQWylZeocCzYm2yC5Dn5Py_F7CF868HrJLw0GU")
TEMPLATE_LEAD_SEM_SITE: str = _env("TEMPLATE_LEAD_SEM_SITE", "1AGsX-h1JFIaL90vQVjEKYAQljKAvLIrxsV4iJfEtRgM")
TEMPLATE_LEAD_COM_SITE: str = _env("TEMPLATE_LEAD_COM_SITE", "10qFTiJnOrbnQ_7ANdH0TmT-8ZtzSj5XVnEsLj5WG5ac")

# ─────────────────────────────────────────────
# 3a. Credenciais – Service Account 
# ─────────────────────────────────────────────
# O caminho do arquivo geralmente será fornecido pelo Cloud Run Jobs como uma variável de ambiente apontando para o segredo montado como arquivo.
GOOGLE_SERVICE_ACCOUNT_FILE: Path = _cred_path("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/conta_servico_google.json")
GOOGLE_OAUTH_CLIENT_FILE:   Path = _cred_path("GOOGLE_OAUTH_CLIENT_FILE", "")
GOOGLE_TOKEN_FILE:          Path = _cred_path("GOOGLE_TOKEN_FILE", "")
# Service Account genérica (Slides/Drive/Sheets) — opcional e compatível com configs legadas
SERVICE_ACCOUNT_FILE:       Path = _cred_path("SERVICE_ACCOUNT_FILE", "credentials/conta_servico_google.json")
SCOPE_GOOGLE_ACCOUNT: List[str] = _env_list(
    "SCOPE_GOOGLE_ACCOUNT",
    default=[
        "https://www.googleapis.com/auth/analytics.readonly",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/presentations",
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    ]
)

# Credenciais dedicadas ao GA4 (opcional, se quiser separar das demais)
GA4_SERVICE_ACCOUNT_FILE: Path = _cred_path("GA4_SERVICE_ACCOUNT_FILE", "credentials/conta_servico_ga4.json")
GA4_OAUTH_CLIENT_FILE:   Path = _cred_path("GA4_OAUTH_CLIENT_FILE", "")
GA4_TOKEN_FILE:          Path = _cred_path("GA4_TOKEN_FILE", "credentials/token_ga4.json")
SCOPE_GA4: List[str] = _env_list(
    "SCOPE_GA4",
    default=[
        "https://www.googleapis.com/auth/analytics.readonly",
    ]
)

# ─────────────────────────────────────────────
# 3b. Credenciais – OAuth “Desktop App”
# ─────────────────────────────────────────────
# (Deixe vazio, se não usar)
OAUTH_CLIENT_FILE: Path = _cred_path("OAUTH_CLIENT_FILE", "credentials/oauth_client.json")
TOKEN_FILE: Path        = _cred_path("TOKEN_FILE", "credentials/token.json")

# ─────────────────────────────────────────────
# 3c. Seleção dinâmica de credenciais
# ─────────────────────────────────────────────
USE_SERVICE_ACCOUNT: bool = _env("USE_SERVICE_ACCOUNT", "False", cast=lambda v: v.lower() in ["1", "true", "yes"])

# ─────────────────────────────────────────────
# 3d. Credenciais Meta ADS Token
# ─────────────────────────────────────────────
ACCESS_TOKEN_META_SYSTEM: str = _env("ACCESS_TOKEN_META_SYSTEM", "")
ACCESS_TOKEN_META_HUMAN: str  = _env("ACCESS_TOKEN_META_HUMAN", "")
ID_SYSTEM_USER: str           = _env("ID_SYSTEM_USER", "")
BUSINESS_ID_META: str         = _env("BUSINESS_ID_META", "")
APP_ID_META: str              = _env("APP_ID_META", "")

# ─────────────────────────────────────────────
# 4. Escopos das demais APIs Google
# ─────────────────────────────────────────────
SCOPES: List[str] = _env_list(
    "SCOPES",
    default=[
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/presentations",
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    ]
)

# ─────────────────────────────────────────────
# 5. Parâmetros de Execução & Logs
# ─────────────────────────────────────────────
SANDBOX_MODE: bool = _env("SANDBOX_MODE", "False", cast=lambda v: v.lower() in ["1", "true", "yes"])
LOG_PATH: Path = Path(_env("LOG_PATH", "logs"))
TZ: str = _env("TZ", "America/Sao_Paulo")

# ─────────────────────────────────────────────
# 6. Ajustes Futuramente Configuráveis
# ─────────────────────────────────────────────
MAX_RETRIES: int = _env("MAX_RETRIES", 5, cast=int)
BACKOFF_SECONDS: int = _env("BACKOFF_SECONDS", 2, cast=int)
CLIENT_LIMIT: Optional[int] = _env("CLIENT_LIMIT", None, cast=lambda v: int(v) if v is not None else None)

TESTE: bool = _env("TESTE", "False", cast=lambda v: v.lower() in ["1", "true", "yes"])

# ─────────────────────────────────────────────
# 7. Interface Web
# ─────────────────────────────────────────────
FLASK_SECRET_KEY: str = _env("FLASK_SECRET_KEY", "change-me-in-production-please")
ADMIN_PASSWORD: str = _env("ADMIN_PASSWORD", "admin")
WEB_PORT: int = _env("WEB_PORT", 5000, cast=int)
WEB_HOST: str = _env("WEB_HOST", "0.0.0.0")

# ─────────────────────────────────────────────
# 8. PostgreSQL
# ─────────────────────────────────────────────
PG_HOST: str = _env("PG_HOST", "127.0.0.1")
PG_PORT: int = _env("PG_PORT", 5432, cast=int)
PG_DBNAME: str = _env("PG_DBNAME", "dados_turbo")
PG_USER: str = _env("PG_USER", "postgres")
PG_PASSWORD: str = _env("PG_PASSWORD", "")
PG_SCHEMA: str = _env("PG_SCHEMA", "autoreport")

# ─────────────────────────────────────────────
# 9. Não edite abaixo, a menos que saiba o que está fazendo
# ─────────────────────────────────────────────
__all__ = [
    # planilha central
    "CENTRAL_SHEET_URL",
    "CENTRAL_TAB_NAME",
    # templates
    "TEMPLATE_RELATORIO_ID",
    "RELATORIO_FOLDER_ID",
    "TEMPLATE_ECOMMERCE",
    "TEMPLATE_LEAD_SEM_SITE",
    "TEMPLATE_LEAD_COM_SITE",
    "FORCE_REPORT_FOLDER_ID",
    # credenciais padrão
    "SERVICE_ACCOUNT_FILE",
    "OAUTH_CLIENT_FILE",
    "TOKEN_FILE",
    "USE_SERVICE_ACCOUNT",
    # credenciais GA4
    "GOOGLE_OAUTH_CLIENT_FILE",
    "GOOGLE_TOKEN_FILE",
    "GA4_OAUTH_CLIENT_FILE",
    "GA4_TOKEN_FILE",
    "SCOPE_GOOGLE_ACCOUNT",
    "SCOPE_GA4",
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "GA4_SERVICE_ACCOUNT_FILE",
    "APP_ID_META",
    # escopos gerais
    "SCOPES",
    # execução
    "SANDBOX_MODE",
    "LOG_PATH",
    "TZ",
    # tunables
    "MAX_RETRIES",
    "BACKOFF_SECONDS",
    "CLIENT_LIMIT",
    "TESTE",
]


