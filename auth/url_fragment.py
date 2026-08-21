"""Lê o fragmento (#...) da URL no navegador — necessário para recovery do Supabase."""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_COMPONENT = components.declare_component(
    "url_fragment",
    path=str(Path(__file__).parent / "url_fragment_frontend"),
)


def ler_fragmento_url():
    """
    Retorna o hash atual (ex.: '#access_token=...'), '' se não houver,
    'redirecting' se o JS estiver promovendo o hash para query params,
    ou None enquanto o componente ainda carrega (com limite de tentativas).
    """
    # Chave nova a cada tentativa de recovery evita valor cacheado de visita anterior.
    if "_url_fragment_key" not in st.session_state:
        st.session_state["_url_fragment_key"] = f"uf_{time.time_ns()}"

    valor = _COMPONENT(
        key=st.session_state["_url_fragment_key"],
        default=None,
    )

    tentativas = int(st.session_state.get("_url_fragment_tentativas", 0))
    if valor is None:
        tentativas += 1
        st.session_state["_url_fragment_tentativas"] = tentativas
        # Evita loop infinito em "Validando link…".
        if tentativas >= 8:
            st.session_state.pop("_url_fragment_tentativas", None)
            st.session_state.pop("_url_fragment_key", None)
            return ""
        return None

    st.session_state.pop("_url_fragment_tentativas", None)
    if valor == "redirecting":
        return "redirecting"
    st.session_state.pop("_url_fragment_key", None)
    return valor
