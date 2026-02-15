from __future__ import annotations
"""Aplica cor vermelha (#D32F2F) às variações negativas em uma apresentação
Google Slides.

Este módulo extrai a parte de *formatação de variações negativas* originalmente
implementada em ``core.slide_filler`` para um utilitário independente. Ele NÃO
realiza substituição de texto, remoção de páginas ou manipulação de imagens –
apenas pinta de vermelho quaisquer valores de placeholder que contenham a seta
"↓" e correspondam a chaves de variação pré‑definidas.

Uso simples
-----------
>>> from core.variation_styler import aplicar_vermelho
>>> aplicar_vermelho(presentation_id, placeholders)
"""

from typing import Dict, List, Set

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utils.logger import get_logger  # type: ignore
from core.cred_manager import load_google_account  # type: ignore
from utils.retry import execute_with_retries

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes e helpers
# ---------------------------------------------------------------------------


# RGB aproximado de #D32F2F (material red 700) em escala 0‑1
_NEGATIVE_COLOR = {"red": 0.878, "green": 0.4, "blue": 0.4}

# Métricas para as quais a lógica é invertida (↓ é bom, ↑ é ruim)
_INVERTED_METRICS = {
    "cpl", "cpl_face", "cpl_goog",
    "cps",
    "cpa", "cpa_face", "cpa_goog",
}

# Métricas convencionais (↓ é ruim, ↑ é bom)
# (não é necessário listar, pois é o padrão)    


def _get_slides_service():  # noqa: D401
    """Instância autorizada da API Google Slides."""
    return build(
        "slides",
        "v1",
        credentials=load_google_account(),
        cache_discovery=False,
    )

# ---------------------------------------------------------------------------
# Funções auxiliares para identificar variações negativas
# ---------------------------------------------------------------------------

def _normalize_key(ph_key: str) -> str:
    """Remove chaves {{ }} e converte para minúsculas."""
    return ph_key.strip("{}").lower()


def _is_variation(ph_key: str, _METRIC_VAR_KEYS: Set[str]) -> bool:
    """Retorna *True* se o placeholder for de variação."""
    return _normalize_key(ph_key) in _METRIC_VAR_KEYS



def _is_negative(value: str) -> bool:
    """Detecta variação negativa pela presença da seta para baixo."""
    return "↓" in value

def _is_positive(value: str) -> bool:
    """Detecta variação positiva pela presença da seta para cima."""
    return "↑" in value



from typing import Tuple

def _coletar_valores_estilizar(ph: Dict[str, str], _METRIC_VAR_KEYS: Set[str]) -> Tuple[Set[str], Set[str]]:
    """Extrai subconjuntos de *values* que devem ser vermelhos e verdes."""
    vermelhos: Set[str] = set()
    verdes: Set[str] = set()
    for chave, val in ph.items():
        if val is None:
            continue
        norm_key = _normalize_key(chave)
        is_inverted = any(inv in norm_key for inv in _INVERTED_METRICS)
        if _is_variation(chave, _METRIC_VAR_KEYS):
            if is_inverted:
                # Para CPA/CPS: ↑ é ruim (vermelho), ↓ é bom (verde)
                if _is_positive(str(val)):
                    vermelhos.add(str(val))
                elif _is_negative(str(val)):
                    verdes.add(str(val))
            else:
                # Para demais: ↓ é ruim (vermelho), ↑ é bom (verde)
                if _is_negative(str(val)):
                    vermelhos.add(str(val))
                elif _is_positive(str(val)):
                    verdes.add(str(val))
    return vermelhos, verdes



def _build_style_requests(
    service,
    presentation_id: str,
    vermelhos: Set[str],
    verdes: Set[str],
) -> List[dict]:
    """Gera `updateTextStyle` para shapes contendo *valores* vermelhos ou verdes."""
    if not vermelhos and not verdes:
        return []

    # Busca leve: somente objectId + texto
    presentation = execute_with_retries(
        lambda: service.presentations().get(
            presentationId=presentation_id,
            fields="slides/pageElements(objectId,shape/text)",
        ).execute(),
        logger=log,
        context=f"slides.presentations().get ({presentation_id}, slides/pageElements)"
    )

    requests: List[dict] = []

    for slide in presentation.get("slides", []):
        for element in slide.get("pageElements", []):
            shape = element.get("shape", {})
            text_elts = shape.get("text", {}).get("textElements", [])
            if not text_elts:
                continue

            texto_completo = "".join(
                te.get("textRun", {}).get("content", "") for te in text_elts
            )

            if any(neg in texto_completo for neg in vermelhos):
                requests.append(
                    {
                        "updateTextStyle": {
                            "objectId": element["objectId"],
                            "textRange": {"type": "ALL"},
                            "style": {
                                "foregroundColor": {
                                    "opaqueColor": {"rgbColor": _NEGATIVE_COLOR}
                                }
                            },
                            "fields": "foregroundColor",
                        }
                    }
                )
            # Para valores positivos, não faz nada (mantém cor padrão do template)
    return requests


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def aplicar_vermelho(presentation_id: str, placeholders: Dict[str, str], _METRIC_VAR_KEYS: Set[str]) -> None:  # noqa: D401
    """Pinta de vermelho (ruim) ou verde (bom) os textos que representem variações.

    Para CPA/CPS, ↓ é verde (bom), ↑ é vermelho (ruim). Para demais, ↓ é vermelho (ruim), ↑ é verde (bom).
    """
    # Garante sempre o prefixo "var_" para cada métrica de variação
    variation_keys: Set[str] = {
        k if k.startswith("var_") else f"var_{k}"
        for k in _METRIC_VAR_KEYS
    }

    vermelhos, verdes = _coletar_valores_estilizar(placeholders, variation_keys)
    if not vermelhos and not verdes:
        log.debug("Nenhuma variação relevante encontrada – nada a estilizar.")
        return

    service = _get_slides_service()
    style_requests = _build_style_requests(service, presentation_id, vermelhos, verdes)

    if not style_requests:
        log.debug("Nenhum shape encontrado para estilizar em %s", presentation_id)
        return

    try:
        execute_with_retries(
            lambda: service.presentations().batchUpdate(
                presentationId=presentation_id, body={"requests": style_requests}
            ).execute(),
            logger=log,
            context=f"slides.batchUpdate (style: {presentation_id}, {len(style_requests)} requests)"
        )
        log.info(
            "Estilo vermelho/verde aplicado (%d ocorrências)", len(style_requests),
            extra={"doc": presentation_id},
        )
    except HttpError as exc:  # noqa: BLE001
        log.error("Falha ao aplicar estilo vermelho/verde (%s): %s", presentation_id, exc)
        raise