# -*- coding: utf-8 -*-
"""core.progress_bar
~~~~~~~~~~~~~~~~~~~~
Redimensiona as **duas** barras de progresso (meta de faturamento e meta de
investimento) dentro do Slides copiado pelo ``template_manager``.

***Correção v2*** – conserva a matriz original e altera **somente** o
``scaleX``. Isto evita distorção vertical e mantém a esquerda fixa sem
mexer em ``translateX``:

1. Lê a transformação completa (`scaleX`, `scaleY`, `translateX`, etc.).
2. Calcula `novo_scaleX = original_scaleX * percentual`.
3. Usa ``updatePageElementTransform`` com ``applyMode = "ABSOLUTE"``
   e a **mesma** matriz, trocando só o `scaleX`.

Uso (mesmo de antes):
```python
from core import progress_bar
progress_bar.redimensionar(
    presentation_id,
    meta_per_fat=dados["META_PER_FAT"],
    meta_per_invest=dados["META_PER_INVEST"],
)
```

Um *tam_max* manual não é mais necessário: a função calcula a largura real
via `scaleX_original`.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utils.logger import get_logger                   # type: ignore
from googleapiclient.discovery import build
from core.cred_manager import load_google_account
from utils.retry import execute_with_retries

log = get_logger(__name__)

__all__ = ["redimensionar"]

DEBUG_ID = False #Flag de DEBUG de IDs do slide

# ──────────────────────────────────────────────────────────────────────────────
# Constantes do template (IDs das formas)
# ──────────────────────────────────────────────────────────────────────────────
_BAR_TITLE_FAT = "barra_faturamento"   # barra de meta de faturamento
_BAR_TITLE_INV = "barra_investimento"  # barra de meta de investimento

# no início do arquivo
_MIN_PCT = 0.0001


# ──────────────────────────────────────────────────────────────────────────────
# Slides API helper
# ──────────────────────────────────────────────────────────────────────────────

def _get_slides_service():
    """Retorna instância autorizada do Google Slides API."""
    return build(
        "slides",
        "v1",
        credentials=load_google_account(),
        cache_discovery=False,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Utilidades internas
# ──────────────────────────────────────────────────────────────────────────────

def _clamp(value: float, min_v: float = 0.0, max_v: float = 1.0) -> float:
    return max(min_v, min(max_v, value))


# ─────── helpers.py (ou dentro de progress_bar) ───────────────────────────────
def pct_to_float(raw: str | int | float | None) -> float:
    """
    Converte valores como “26,47%”, “26.47”, 26.47, 0.2647, "-", "" ou None
    em um float entre 0 e 1.

    Regras:
    • "-", "–", "—", string vazia ou None  →   0.0
    • vírgula ou ponto como separador      →   aceito
    • presença (ou ausência) de '%'        →   aceito
    • números > 1 são interpretados como ‘x %’ e divididos por 100
    """
    # → nulo / traço / vazio  ⇒  0
    if raw in (None, "", "-", "–", "—"):
        return _MIN_PCT

    # → já numérico (int/float)
    if isinstance(raw, (int, float)):
        val = float(raw)
        return val / 100 if val > 1 else val

    # → string: limpar e converter
    if not isinstance(raw, str):
        raise TypeError(f"Formato inesperado para porcentagem: {type(raw)}")

    cleaned = (
        raw.strip()
        .replace("%", "")
        .replace(" ", "")
        .replace(",", ".")
    )

    if cleaned == "":        # ex: só espaços ou "%"
        return _MIN_PCT

    val = float(cleaned)     # ainda pode lançar ValueError legítimo
    return val / 100 if val > 1 else val


def _find_element_meta(el: dict, key: str) -> tuple[str, dict] | None:
    """
    Procura recursivamente por `key`, que pode ser title ou objectId.
    Se encontrar, devolve (objectId, transform).
    """
    if el.get("objectId") == key or el.get("title") == key:
        return el["objectId"], el["transform"]

    # Caso seja um grupo, desce nos filhos
    if "elementGroup" in el:
        for child in el["elementGroup"].get("children", []):
            found = _find_element_meta(child, key)
            if found:
                return found
    return None

def _get_id_and_tf(
    service,
    presentation_id: str,
    slide_id: str,
    key: str,
) -> tuple[str, dict]:
    """
    Devolve (objectId real, transform) do elemento cujo objectId OU title = `key`.
    Faz varredura recursiva para pegar shapes dentro de grupos.
    """
    page = execute_with_retries(
        lambda: service.presentations()
            .pages()
            .get(
                presentationId=presentation_id,
                pageObjectId=slide_id,
                fields="pageElements(objectId,title,transform,elementGroup)",
            )
            .execute(),
        logger=log,
        context=f"slides.pages().get (slide_id={slide_id}, campos=transform+title+children)"
    )


    for el in page.get("pageElements", []):
        found = _find_element_meta(el, key)
        if found:
            return found

    raise ValueError(f"Elemento '{key}' não encontrado no slide {slide_id}.")


def _build_absolute_request(obj_id: str, tf: Dict[str, float], pct: float) -> Dict:
    """Copia a matriz original e altera apenas o scaleX."""
    pct = _clamp(pct)
    new_tf = {
        **tf,  # copia todos (scaleX, scaleY, shearX, shearY, translate…)
        "scaleX": tf.get("scaleX", 1) * pct,
    }
    new_tf["unit"] = "EMU"
    return {
        "updatePageElementTransform": {
            "objectId": obj_id,
            "applyMode": "ABSOLUTE",
            "transform": new_tf,
        }
    }

def _debug_listar_ids(service, presentation_id: str, slide_id: str) -> None:
    """
    Loga objectId, tipo de elemento e o 1º trecho de texto (ou alt-title)
    de cada PageElement do slide indicado.
    """

    print("\n\n debug de IDS \n\n")

    try:
        page = execute_with_retries(
            lambda: service.presentations()
                .pages()
                .get(
                    presentationId=presentation_id,
                    pageObjectId=slide_id,
                    fields="pageElements(objectId,title,shape)",
                )
                .execute(),
            logger=log,
            context=f"slides.pages().get (slide_id={slide_id}, campos=objectId+title+shape)"
        )
    except HttpError as exc:
        log.error("Falha ao listar IDs: %s", exc)
        return

    print("=== LISTA DE ELEMENTOS DO SLIDE ===")
    for el in page.get("pageElements", []):
        obj_id = el.get("objectId")
        tipo   = el.get("pageElementType", "UNKNOWN")
        title  = el.get("title") or ""

        texto = ""
        if el.get("shape"):
            for run in el["shape"].get("text", {}).get("textElements", []):
                if "textRun" in run:
                    texto = run["textRun"]["content"].strip()
                    break

        # Mostra alt-title se existir, senão o início do texto do shape
        label = title if title else texto[:40]
        print(f"ID={obj_id:<12} | {tipo:<15} | {label}")

# ──────────────────────────────────────────────────────────────────────────────
# Função pública
# ──────────────────────────────────────────────────────────────────────────────

def redimensionar(
    presentation_id: str,
    *,
    slide_id: str | None = None,
    meta_per_fat: float | int,
    meta_per_inv: float | int,
) -> None:
    """Refaz larguras das barras mantendo sua altura e posição originais."""

    try:
        fat_pct = pct_to_float(meta_per_fat)
        inv_pct = pct_to_float(meta_per_inv)
    except (ValueError, TypeError) as exc:
        log.error("Percentuais inválidos: %s", exc)
        raise

    service = _get_slides_service()

    # Slide único? Descobre.
    if slide_id is None:
        slide_id = execute_with_retries(
            lambda: service.presentations()
                .get(presentationId=presentation_id, fields="slides(objectId)")
                .execute(),
            logger=log,
            context=f"slides.presentations().get (slides(objectId) de {presentation_id})"
        )["slides"][0]["objectId"]


    if DEBUG_ID:
            _debug_listar_ids(service, presentation_id, slide_id)

    try:
        # Transforms originais
        obj_fat, tf_fat = _get_id_and_tf(service, presentation_id, slide_id, _BAR_TITLE_FAT)
        obj_inv, tf_inv = _get_id_and_tf(service, presentation_id, slide_id, _BAR_TITLE_INV)

        # Monta batch
        requests: List[Dict] = [
            _build_absolute_request(obj_fat, tf_fat, fat_pct),
            _build_absolute_request(obj_inv, tf_inv, inv_pct),
        ]

        execute_with_retries(
            lambda: service.presentations().batchUpdate(
                presentationId=presentation_id,
                body={"requests": requests},
            ).execute(),
            logger=log,
            context=f"slides.batchUpdate ({presentation_id}, {len(requests)} requests)"
        )


        log.info(
            "Barras redimensionadas (fat: %.2f, inv: %.2f)", fat_pct, inv_pct,
            extra={"doc": presentation_id},
        )

    except HttpError as exc:
        log.error("Falha no batchUpdate (%s): %s", presentation_id, exc)
        raise
