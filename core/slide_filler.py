from __future__ import annotations
"""core.slide_filler (2025-07-09)

Preenche automaticamente placeholders de texto e imagens no template Google
Slides já copiado pelo *template_manager*.

OBS.: A coloração de variações negativas foi **extraída** para
``core.variation_styler``. Este módulo agora só cuida de:
• replaceAllText dos placeholders;
• replaceImage das criativas na página 3;
• remoção opcional de páginas (ex.: GA4);
• logging de execução.
"""

from typing import Dict, List
import threading

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utils.logger import get_logger  # type: ignore
from core.cred_manager import load_google_account  # type: ignore
from core.variation_styler import aplicar_vermelho  # nova dependência
from utils.retry import execute_with_retries

log = get_logger(__name__)

__all__ = ["preencher"]

# ---------------------------------------------------------------------------
# API Slides helper (thread-safe)
# ---------------------------------------------------------------------------

_thread_local = threading.local()

def _get_slides_service():
    if not hasattr(_thread_local, "slides_service"):
        _thread_local.slides_service = build(
            "slides",
            "v1",
            credentials=load_google_account(),
            cache_discovery=False,
        )
    return _thread_local.slides_service

def remover_slide(presentation_id: str, slide_id: str) -> None:  # noqa: D401
    """Remove uma página da apresentação (deleteObject)."""
    service = _get_slides_service()
    execute_with_retries(
        lambda: service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [{"deleteObject": {"objectId": slide_id}}]},
        ).execute(),
        logger=log,
        context=f"slides.batchUpdate (remover_slide: {presentation_id}/{slide_id})"
    )

# ---------------------------------------------------------------------------
# replaceAllText helpers
# ---------------------------------------------------------------------------

def _build_requests(ph: Dict[str, str]) -> List[dict]:  # noqa: D401
    """Transforma ``ph`` em lista de requests ``replaceAllText``."""
    reqs: List[dict] = []
    for placeholder, value in ph.items():
        if value is None:
            value = "-"
        reqs.append(
            {
                "replaceAllText": {
                    "containsText": {"text": placeholder, "matchCase": True},
                    "replaceText": str(value),
                }
            }
        )
    return reqs

# ---------------------------------------------------------------------------
# Imagens – página 3 do template
# ---------------------------------------------------------------------------

# OK manter o lru_cache AQUI, pois apenas cacheia o dicionário retornado,
# não o objeto service! Não há problema em usar cache para funções
# que retornam dados simples e são thread-safe!
from functools import lru_cache

@lru_cache(maxsize=16)
def _get_img_id_map_cached(presentation_id: str, meta_ads_slide: str) -> dict[str, str]:
    """Varre a página ``img_page_id`` e devolve ``{nome: objectId_real}`` (com cache)."""
    service = _get_slides_service()
    page = execute_with_retries(
        lambda: service.presentations()
            .pages()
            .get(
                presentationId=presentation_id,
                pageObjectId=meta_ads_slide,
                fields="pageElements(objectId,title,elementGroup)",
            )
            .execute(),
        logger=log,
        context=f"slides.pages().get({presentation_id}/{meta_ads_slide})"
    )


    def _walk(el: dict) -> list[dict]:  # DFS para grupos aninhados
        children = [el]
        if "elementGroup" in el:
            for ch in el["elementGroup"].get("children", []):
                children.extend(_walk(ch))
        return children

    id_map: dict[str, str] = {}
    for el in page.get("pageElements", []):
        for node in _walk(el):
            oid = node.get("objectId")
            title = node.get("title")
            for key in (oid, title):
                if key and key.startswith("img_adf"):
                    id_map[key] = oid
    return id_map

def _build_replace_image_requests(ph: Dict[str, str], id_map: dict[str, str]) -> List[dict]:  # noqa: E501
    """Cria ``ReplaceImageRequest`` para placeholders ``{{img_adfX}}``."""
    reqs = [
        {
            "replaceImage": {
                "imageObjectId": id_map[placeholder.strip("{}")],
                "url": url,
                "imageReplaceMethod": "CENTER_INSIDE",
            }
        }
        for placeholder, url in ph.items()
        if placeholder.startswith("{{img_")
        and url and url != "-" and url != "__NO_IMAGE__"
        and id_map.get(placeholder.strip("{}"))
    ]
    # Logging só se debug
    if log.isEnabledFor(10):
        for idx, r in enumerate(reqs):
            log.debug("IMG_REQ[%s] → %s", idx, r["replaceImage"]["url"])
    return reqs

# ---------------------------------------------------------------------------
# Função pública
# ---------------------------------------------------------------------------

def preencher(presentation_id: str, placeholders: Dict[str, str], meta_ads_slide: str) -> None:  # noqa: D401,E501
    """Alimenta a apresentação *presentation_id* com os valores de *placeholders*.

    • Substitui texto (replaceAllText)
    • Troca criativas na página 3 (replaceImage)
    • Delega a coloração de variações negativas para ``core.variation_styler``.
    Otimizado para performance: cache, menos laços, e requests agrupados.
    """
    if not placeholders:
        log.warning("Sem placeholders – Slides não será modificado.")
        return

    service = _get_slides_service()

    # 1) Texto
    text_reqs = _build_requests(placeholders)

    # 2) Imagens (usa cache)
    id_map = _get_img_id_map_cached(presentation_id, meta_ads_slide)

    # Exclui imagens base para placeholders com marcador __NO_IMAGE__
    delete_img_reqs = [
        {"deleteObject": {"objectId": id_map[key]}}
        for placeholder, url in placeholders.items()
        if placeholder.startswith("{{img_") and url == "__NO_IMAGE__"
        and (key := placeholder.strip("{}")) in id_map
    ]

    img_reqs = _build_replace_image_requests(placeholders, id_map)

    all_reqs: List[dict] = text_reqs + delete_img_reqs + img_reqs

    if all_reqs:
        try:
            # Otimização: batchUpdate já é atômico, mas pode-se dividir em chunks se necessário
            execute_with_retries(
                lambda: service.presentations().batchUpdate(
                    presentationId=presentation_id, body={"requests": all_reqs}
                ).execute(),
                logger=log,
                context=f"slides.batchUpdate (preenchimento: {presentation_id}, {len(all_reqs)} reqs)"
            )
            log.info(
                "Slides preenchidos (%d requests)", len(all_reqs),
                extra={"doc": presentation_id},
            )
        except HttpError as e:
            erro_msg = str(e)
            if "replaceImage" in erro_msg:
                # loga todas as imagens tentadas (pode customizar se souber qual foi o erro)
                for idx, r in enumerate(img_reqs, start=len(text_reqs)):
                    url = r["replaceImage"]["url"]
                    log.error(
                        "Erro ao inserir imagem: URL inválida ou inacessível: %s [IMG_REQ[%s]]", url, idx,
                        extra={"doc": presentation_id},
                    )
            else:
                # loga normalmente se for outro erro
                log.error(
                    "Falha ao atualizar slides: %s", erro_msg,
                    extra={"doc": presentation_id},
                )
            # Não lança novamente, apenas loga e segue
