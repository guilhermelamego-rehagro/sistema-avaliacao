"""Lembra a última sala usada por professoras orientadoras."""

from __future__ import annotations

import streamlit as st

from auth.supabase_auth import cliente_admin, professor_e_orientador
from utils.ordenacao import ordenar_grupos_lista

_CHAVE = "pref_sala"


def _deve_lembrar(usuario: dict) -> bool:
    return usuario.get("perfil") == "Professor" and professor_e_orientador(usuario)


def sala_lembrada(usuario: dict) -> str:
    valor = st.session_state.get(_CHAVE) or usuario.get("ultima_sala") or ""
    return str(valor).strip()


def lembrar_sala(usuario: dict, sala: str | None):
    if not _deve_lembrar(usuario):
        return
    sala = str(sala or "").strip()
    if not sala or sala == "Todas":
        return
    if sala_lembrada(usuario) == sala:
        st.session_state[_CHAVE] = sala
        return
    st.session_state[_CHAVE] = sala
    usuario["ultima_sala"] = sala
    user_id = usuario.get("id")
    if not user_id:
        return
    try:
        cliente_admin().auth.admin.update_user_by_id(
            user_id, {"user_metadata": {"ultima_sala": sala}}
        )
    except Exception:
        pass


def selectbox_sala(
    label: str,
    salas: list,
    *,
    key: str,
    usuario: dict,
    incluir_todas: bool = True,
) -> str:
    salas = ordenar_grupos_lista([str(s).strip() for s in salas if str(s).strip()])
    opcoes = (["Todas"] + salas) if incluir_todas else salas
    if not opcoes:
        return "Todas" if incluir_todas else ""
    pref = sala_lembrada(usuario)
    if key not in st.session_state:
        if pref in salas:
            st.session_state[key] = pref
        elif incluir_todas:
            st.session_state[key] = "Todas"
        else:
            st.session_state[key] = salas[0]
    atual = st.session_state.get(key)
    if atual not in opcoes:
        st.session_state[key] = pref if pref in salas else opcoes[0]
    escolhido = st.selectbox(label, opcoes, key=key)
    lembrar_sala(usuario, escolhido)
    return escolhido


def multiselect_sala(salas: list, *, key: str, usuario: dict) -> list[str]:
    salas = ordenar_grupos_lista([str(s).strip() for s in salas if str(s).strip()])
    pref = sala_lembrada(usuario)
    if key not in st.session_state:
        st.session_state[key] = [pref] if pref in salas else []
    atual = [s for s in st.session_state.get(key, []) if s in salas]
    st.session_state[key] = atual
    escolhido = st.multiselect("Filtrar por Sala:", salas, key=key)
    if len(escolhido) == 1:
        lembrar_sala(usuario, escolhido[0])
    return escolhido
