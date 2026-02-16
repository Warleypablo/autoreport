# -*- coding: utf-8 -*-
"""web/sync.py - Sync clients from Google Sheets to PostgreSQL."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime

from utils.logger import get_logger

log = get_logger(__name__)

# Portuguese prepositions that stay lowercase in names
_LOWER_PARTS = {"de", "da", "do", "das", "dos", "e"}


def _normalize_name(raw: str | None) -> str | None:
    """Normalize a name: strip, collapse spaces, title case with PT-BR rules.

    'JOAO DA SILVA' -> 'Joao da Silva'
    '  maria  ' -> 'Maria'
    """
    if not raw or not raw.strip():
        return None
    name = re.sub(r"\s+", " ", raw.strip())
    parts = []
    for i, p in enumerate(name.split(" ")):
        low = p.lower()
        if i > 0 and low in _LOWER_PARTS:
            parts.append(low)
        else:
            parts.append(p.capitalize())
    return " ".join(parts)


def sync_clientes_from_sheets() -> dict:
    """Fetch all clients from Google Sheets and UPSERT into PG clientes table.

    Returns {"synced": int, "errors": list[str]}.
    """
    from core.leitura_central import fetch_clientes
    from config import settings
    from web.pg_db import get_standalone_conn

    errors: list[str] = []
    synced = 0

    try:
        clientes = fetch_clientes(
            atualizar=False,
            only=None,
            sheet_url=settings.CENTRAL_SHEET_URL,
            tab_name=settings.CENTRAL_TAB_NAME,
        )
    except Exception as exc:
        log.exception("Erro ao buscar clientes da planilha para sync")
        return {"synced": 0, "errors": [str(exc)]}

    conn = get_standalone_conn()
    try:
        cur = conn.cursor()
        for c in clientes:
            try:
                # Extract known extra fields (normalize names)
                gestor = _normalize_name(c.extras.get("GESTOR"))
                squad = c.extras.get("SQUAD") or None
                status_auto = c.extras.get("STATUS (AUTO)", "")
                ultima_geracao = c.extras.get("ULTIMA VEZ GERADO (AUTO)", "")

                # Collect remaining extras (exclude private keys)
                extra_cols = {
                    k: v for k, v in c.extras.items()
                    if not k.startswith("_")
                    and k not in ("STATUS (AUTO)", "ULTIMA VEZ GERADO (AUTO)",
                                  "GESTOR", "SQUAD")
                }

                cur.execute(
                    """INSERT INTO clientes
                       (nome, categoria, gestor, squad, painel_url, pasta_url,
                        id_google_ads, id_meta_ads, id_ga4,
                        status_auto, ultima_geracao, extras, synced_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
                       ON CONFLICT (nome) DO UPDATE SET
                           categoria = EXCLUDED.categoria,
                           gestor = EXCLUDED.gestor,
                           squad = EXCLUDED.squad,
                           painel_url = EXCLUDED.painel_url,
                           pasta_url = EXCLUDED.pasta_url,
                           id_google_ads = EXCLUDED.id_google_ads,
                           id_meta_ads = EXCLUDED.id_meta_ads,
                           id_ga4 = EXCLUDED.id_ga4,
                           status_auto = EXCLUDED.status_auto,
                           ultima_geracao = EXCLUDED.ultima_geracao,
                           extras = EXCLUDED.extras,
                           synced_at = NOW(),
                           updated_at = NOW()""",
                    (
                        c.nome, c.categoria, gestor, squad,
                        c.painel_url, c.pasta_url,
                        c.id_google_ads, c.id_meta_ads, c.id_ga4,
                        status_auto, ultima_geracao,
                        json.dumps(extra_cols, ensure_ascii=False),
                    ),
                )
                synced += 1
            except Exception as exc:
                errors.append(f"{c.nome}: {exc}")
                log.warning("Erro ao sincronizar cliente %s: %s", c.nome, exc)

        conn.commit()
        log.info("Sync concluido: %d clientes sincronizados, %d erros", synced, len(errors))
    except Exception as exc:
        conn.rollback()
        log.exception("Erro geral no sync de clientes")
        errors.append(str(exc))
    finally:
        conn.close()

    return {"synced": synced, "errors": errors}
