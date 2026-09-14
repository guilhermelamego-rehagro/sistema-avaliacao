"""Modo 'visualizar como aluno' para orientadores e coordenadores."""

from __future__ import annotations

import streamlit as st

from auth.supabase_auth import professor_e_orientador, usuario_e_coordenador
from utils.logs import registrar_log
from utils.ordenacao import chave_ordenacao_texto


def pode_impersonar(usuario: dict | None) -> bool:
    if not usuario:
        return False
    if usuario.get("perfil") != "Professor":
        return False
    return professor_e_orientador(usuario) or usuario_e_coordenador(usuario)


def usuario_ator() -> dict | None:
    """Usuário autenticado de verdade (não a persona do aluno)."""
    return st.session_state.get("usuario_real") or st.session_state.get("usuario_logado")


def esta_impersonando() -> bool:
    return bool(st.session_state.get("impersonando"))


def bloqueia_escrita_aluno() -> bool:
    """Modo leitura: impede envios/gravações em nome do aluno."""
    return esta_impersonando()


def alvo_impersonacao() -> dict | None:
    return st.session_state.get("impersonando")


def listar_alunos_para_impersonar() -> list[dict]:
    """Lista alunos da Base_Alunos (nome + e-mail), ordenados."""
    from data.sheets import ler_aba

    try:
        df = ler_aba("Base_Alunos")
    except Exception:
        return []
    if df is None or df.empty:
        return []

    col_email = "Email_Pessoal" if "Email_Pessoal" in df.columns else None
    col_nome = "Nome_Completo" if "Nome_Completo" in df.columns else None
    if not col_email:
        return []

    saida: list[dict] = []
    vistos: set[str] = set()
    for _, row in df.iterrows():
        if "Perfil" in df.columns:
            perfil = str(row.get("Perfil") or "").strip()
            if perfil and perfil.lower() != "aluno":
                continue
        email = str(row.get(col_email) or "").strip().lower()
        if not email or "@" not in email or email in vistos:
            continue
        nome = str(row.get(col_nome) or email).strip() if col_nome else email
        vistos.add(email)
        saida.append({"email": email, "nome": nome})

    return sorted(
        saida,
        key=lambda a: (chave_ordenacao_texto(a["nome"]), a["email"]),
    )


def _persona_aluno(email: str, nome: str) -> dict:
    return {
        "id": f"impersonate:{email}",
        "email": email.strip().lower(),
        "nome": (nome or email).strip(),
        "perfil": "Aluno",
        "tipo_professor": None,
        "coordenador": False,
        "deve_trocar_senha": False,
        "_impersonado": True,
    }


def iniciar_impersonacao(email: str, nome: str) -> str | None:
    """
    Troca usuario_logado para a persona do aluno.
    Retorna mensagem de erro ou None.
    """
    atual = st.session_state.get("usuario_logado")
    if not atual:
        return "Sessão inválida."
    ator = st.session_state.get("usuario_real") or atual
    if not pode_impersonar(ator):
        return "Sem permissão para visualizar como aluno."
    if esta_impersonando():
        return "Já está visualizando como aluno. Saia do modo atual primeiro."

    email_n = (email or "").strip().lower()
    nome_n = (nome or email_n).strip()
    if not email_n or "@" not in email_n:
        return "Selecione um aluno válido."

    st.session_state["usuario_real"] = dict(ator)
    st.session_state["impersonando"] = {"email": email_n, "nome": nome_n}
    st.session_state["usuario_logado"] = _persona_aluno(email_n, nome_n)
    st.session_state["escolha_menu"] = "inicio"
    st.session_state["modo_coordenador"] = False

    registrar_log(
        ator.get("email") or "",
        ator.get("nome") or "",
        f"Impersonação: entrou como {email_n} ({nome_n})",
        dedupe=False,
    )
    return None


def encerrar_impersonacao() -> None:
    alvo = st.session_state.get("impersonando") or {}
    real = st.session_state.get("usuario_real")
    if real:
        registrar_log(
            real.get("email") or "",
            real.get("nome") or "",
            f"Impersonação: saiu (era {alvo.get('email') or '?'})",
            dedupe=False,
        )
        st.session_state["usuario_logado"] = dict(real)
        from navigation import rota_padrao

        st.session_state["escolha_menu"] = rota_padrao(real, real.get("perfil") or "Professor")
    st.session_state.pop("impersonando", None)
    st.session_state.pop("usuario_real", None)


def render_banner_impersonacao() -> None:
    if not esta_impersonando():
        return
    alvo = alvo_impersonacao() or {}
    ator = st.session_state.get("usuario_real") or {}
    c1, c2 = st.columns([4, 1])
    with c1:
        st.warning(
            f"**Modo visualização** — você ({ator.get('nome') or ator.get('email')}) "
            f"está vendo como **{alvo.get('nome')}** `<{alvo.get('email')}>`. "
            "Envios e gravações em nome do aluno estão bloqueados."
        )
    with c2:
        if st.button("Sair do modo aluno", type="primary", width="stretch", key="btn_sair_impersonacao"):
            encerrar_impersonacao()
            st.rerun()


def render_seletor_sidebar(usuario_menu: dict) -> None:
    """
    Mostra seletor na sidebar do professor (quando não impersona)
    ou atalho de saída (quando impersona — menu já é o do aluno).
    """
    if esta_impersonando():
        alvo = alvo_impersonacao() or {}
        ator = st.session_state.get("usuario_real") or {}
        st.sidebar.divider()
        st.sidebar.caption(
            f"Visualizando como aluno\n\n"
            f"**{alvo.get('nome')}**\n`{alvo.get('email')}`\n\n"
            f"Ator: {ator.get('nome') or ator.get('email')}"
        )
        if st.sidebar.button("Sair do modo aluno", width="stretch", key="sidebar_sair_impersonacao"):
            encerrar_impersonacao()
            st.rerun()
        return

    if not pode_impersonar(usuario_menu):
        return

    st.sidebar.divider()
    with st.sidebar.expander("Visualizar como aluno", expanded=False):
        st.caption(
            "Abre o portal na visão do aluno (somente leitura). "
            "Útil para conferir lançamentos reais."
        )
        alunos = listar_alunos_para_impersonar()
        if not alunos:
            st.caption("Nenhum aluno encontrado na Base_Alunos.")
            return
        busca = st.text_input("Buscar", key="impersonate_busca", placeholder="Nome ou e-mail")
        q = (busca or "").strip().lower()
        filtrados = [
            a
            for a in alunos
            if not q or q in a["nome"].lower() or q in a["email"]
        ][:80]
        if not filtrados:
            st.caption("Nenhum resultado.")
            return
        rotulos = {f"{a['nome']} <{a['email']}>": a for a in filtrados}
        escolha = st.selectbox(
            "Aluno",
            options=list(rotulos.keys()),
            key="impersonate_select",
            label_visibility="collapsed",
        )
        if st.button("Entrar na visão do aluno", type="primary", width="stretch", key="impersonate_go"):
            alvo = rotulos[escolha]
            erro = iniciar_impersonacao(alvo["email"], alvo["nome"])
            if erro:
                st.error(erro)
            else:
                st.rerun()
