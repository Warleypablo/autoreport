"""
Registro de handlers de categoria.

Cada módulo em core/categorias deve expor:
    nome: str
    template_id: str
    coletar_dados(cliente, periodo_ref, periodo_comp) -> dict
    pos_processar(presentation_id, dados) -> None
"""

from importlib import import_module

# Lista de módulos de categoria - use nomes de arquivo válidos em Python.
_MODULE_NAMES = [
    "E-commerce",
    "Lead Com Site",
    "Lead Sem Site",
]

_HANDLERS = {}

for _mod_name in _MODULE_NAMES:
    mod = import_module(f"{__name__}.{_mod_name}")
    _HANDLERS[mod.nome.lower()] = mod


def get_handler(nome: str):
    """
    Retorna o módulo-handler correspondente à categoria pedida.

    Normaliza para minúsculo e lança ValueError caso não exista.
    """
    if not nome:
        raise ValueError("Categoria vazia ou None")

    chave = nome.strip().lower()
    try:
        return _HANDLERS[chave]
    except KeyError as exc:
        raise ValueError(f"Categoria desconhecida: {nome!r}") from exc