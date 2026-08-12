"""Autenticação Supabase para o portal de avaliações."""

from __future__ import annotations

import streamlit as st
from supabase import Client, create_client

SENHA_MINIMA = 6


@st.cache_resource
def cliente_anon() -> Client:
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["anon_key"])


@st.cache_resource
def cliente_admin() -> Client:
    return create_client(
        st.secrets["supabase"]["url"], st.secrets["supabase"]["service_role_key"]
    )


def validar_senha(senha: str) -> str | None:
    if len(senha) < SENHA_MINIMA:
        return f"A senha deve ter pelo menos {SENHA_MINIMA} caracteres."
    return None


def restaurar_sessao_supabase() -> Client | None:
    access = st.session_state.get("sb_access_token")
    refresh = st.session_state.get("sb_refresh_token")
    if not access or not refresh:
        return None
    client = cliente_anon()
    try:
        client.auth.set_session(access, refresh)
        return client
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _buscar_perfil_cached(user_id: str) -> dict | None:
    resposta = (
        cliente_admin()
        .table("perfis_usuario")
        .select("*")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if resposta.data:
        return resposta.data[0]
    return None


def buscar_perfil(user_id: str) -> dict | None:
    return _buscar_perfil_cached(user_id)


def montar_usuario_logado(session, perfil: dict) -> dict:
    return {
        "id": perfil["id"],
        "email": perfil["email"],
        "nome": perfil["nome"],
        "perfil": perfil["perfil"],
        "tipo_professor": perfil.get("tipo_professor"),
        "coordenador": bool(perfil.get("coordenador", False)),
        "deve_trocar_senha": perfil.get("deve_trocar_senha", False),
    }


def fazer_login(email: str, senha: str) -> tuple[dict | None, str | None]:
    email = email.strip().lower()
    client = cliente_anon()
    try:
        auth = client.auth.sign_in_with_password({"email": email, "password": senha})
    except Exception as e:
        msg = str(e)
        if "Invalid login credentials" in msg:
            return None, "E-mail ou senha incorretos."
        return None, "Não foi possível entrar. Tente novamente."

    if not auth.session or not auth.user:
        return None, "Falha na autenticação."

    perfil = buscar_perfil(auth.user.id)
    if not perfil:
        return None, "Usuário autenticado, mas sem perfil cadastrado. Contate o suporte."
    if not perfil.get("ativo", True):
        return None, "Cadastro inativo. Contate a secretaria."

    st.session_state["sb_access_token"] = auth.session.access_token
    st.session_state["sb_refresh_token"] = auth.session.refresh_token
    usuario = montar_usuario_logado(auth.session, perfil)
    st.session_state["usuario_logado"] = usuario
    return usuario, None


def trocar_senha(nova_senha: str) -> str | None:
    erro = validar_senha(nova_senha)
    if erro:
        return erro

    client = restaurar_sessao_supabase()
    if not client:
        return "Sessão expirada. Faça login novamente."

    try:
        client.auth.update_user({"password": nova_senha})
    except Exception as e:
        return f"Não foi possível alterar a senha: {e}"

    user_id = st.session_state["usuario_logado"]["id"]
    cliente_admin().table("perfis_usuario").update(
        {"deve_trocar_senha": False}
    ).eq("id", user_id).execute()

    st.session_state["usuario_logado"]["deve_trocar_senha"] = False
    return None


def fazer_logout():
    client = restaurar_sessao_supabase()
    if client:
        try:
            client.auth.sign_out()
        except Exception:
            pass

    for chave in list(st.session_state.keys()):
        del st.session_state[chave]


def professor_e_orientador(usuario: dict) -> bool:
    if usuario.get("perfil") != "Professor":
        return False
    tipo = usuario.get("tipo_professor") or "Orientador"
    return tipo in {"Orientador", "Ambos"}


def professor_e_especialista(usuario: dict) -> bool:
    if usuario.get("perfil") != "Professor":
        return False
    tipo = usuario.get("tipo_professor") or "Orientador"
    return tipo in {"Especialista", "Ambos", "Orientador"}


def usuario_e_coordenador(usuario: dict) -> bool:
    if usuario.get("perfil") != "Professor":
        return False
    if usuario.get("coordenador"):
        return True
    emails_cfg = st.secrets.get("coordenacao", {}).get("emails", [])
    email = str(usuario.get("email", "")).lower().strip()
    return email in [str(e).lower().strip() for e in emails_cfg]
