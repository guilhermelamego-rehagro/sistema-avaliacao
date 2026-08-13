"""Mantém, em cada tela, o último filtro de sala usado na sessão."""

from __future__ import annotations

import streamlit as st

from utils.ordenacao import ordenar_grupos_lista


def selectbox_sala(
    label: str,
    salas: list,
    *,
    key: str,
    usuario: dict | None = None,
    incluir_todas: bool = True,
) -> str:
    salas = ordenar_grupos_lista([str(s).strip() for s in salas if str(s).strip()])
    opcoes = (["Todas"] + salas) if incluir_todas else salas
    if not opcoes:
        return "Todas" if incluir_todas else ""
    if key in st.session_state and st.session_state[key] not in opcoes:
        del st.session_state[key]
    return st.selectbox(label, opcoes, key=key)


def multiselect_sala(salas: list, *, key: str, usuario: dict | None = None) -> list[str]:
    salas = ordenar_grupos_lista([str(s).strip() for s in salas if str(s).strip()])
    if key in st.session_state:
        atual = st.session_state.get(key) or []
        if not isinstance(atual, list):
            atual = [atual] if atual else []
        st.session_state[key] = [s for s in atual if s in salas]
    return st.multiselect("Filtrar por Sala:", salas, key=key)
