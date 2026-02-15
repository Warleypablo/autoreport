from __future__ import annotations

from typing import Optional, Sequence

import re

from utils.retry import execute_with_retries


def a1_escape_sheet_name(sheet_name: str) -> str:
    """Return a sheet name safely escaped for A1 notation.

    Google Sheets expects sheet names with spaces/special chars to be wrapped
    in single quotes, with internal quotes doubled.
    """
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'"


def a1_range(sheet_name: str, cell_range: Optional[str] = None) -> str:
    """Build a safe A1 range using a quoted sheet name."""
    sheet_part = a1_escape_sheet_name(sheet_name)
    if cell_range:
        return f"{sheet_part}!{cell_range}"
    return sheet_part


def _norm_sheet_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().casefold()


def resolve_sheet_title(
    service,
    spreadsheet_id: str,
    desired_title: str,
    logger=None,
) -> str:
    """Resolve a sheet title, falling back to the first tab if missing."""
    try:
        meta = execute_with_retries(
            lambda: service.spreadsheets()
                .get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title")
                .execute(),
            logger=logger,
            context=f"sheets.get ({spreadsheet_id}, sheets.properties.title)",
        )
    except Exception as exc:  # noqa: BLE001
        if logger:
            logger.warning(
                "Falha ao listar abas (%s). Usando '%s'.",
                exc,
                desired_title,
            )
        return desired_title

    sheets = meta.get("sheets", []) if isinstance(meta, dict) else []
    titles: Sequence[str] = [
        s.get("properties", {}).get("title", "")
        for s in sheets
        if isinstance(s, dict)
    ]
    titles = [t for t in titles if t]
    if not titles:
        return desired_title

    if desired_title in titles:
        return desired_title

    desired_norm = _norm_sheet_title(desired_title)
    for t in titles:
        if _norm_sheet_title(t) == desired_norm:
            if logger and t != desired_title:
                logger.warning(
                    "Aba '%s' não existe exatamente. Usando '%s'.",
                    desired_title,
                    t,
                )
            return t

    if logger:
        logger.warning(
            "Aba '%s' não existe em %s. Usando primeira aba '%s'.",
            desired_title,
            spreadsheet_id,
            titles[0],
        )
    return titles[0]
