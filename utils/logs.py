"""Registro de acessos na planilha Log_Acessos."""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from data.sheets import planilha

# Eventos de segurança: cada tentativa conta (não deduplicar na sessão).
_ACOES_SEM_DEDUPE = frozenset(
    {
        "Falha de login",
        "Solicitou recuperação de senha",
        "Solicitou recuperação (senha temporária)",
    }
)


def _atribuir_impersonacao(email: str, nome: str, acao: str) -> tuple[str, str, str]:
    """
    Em modo impersonação, o log fica no ator real e a ação cita o aluno alvo.
    Entrada/saída do modo já vêm prefixadas com 'Impersonação:' e não são alteradas.
    """
    if not st.session_state.get("impersonando"):
        return email, nome, acao
    real = st.session_state.get("usuario_real")
    if not real:
        return email, nome, acao
    if str(acao).startswith("Impersonação"):
        return (
            str(real.get("email") or email).strip().lower(),
            str(real.get("nome") or nome).strip(),
            acao,
        )
    alvo = st.session_state.get("impersonando") or {}
    email_alvo = str(alvo.get("email") or "?").strip().lower()
    return (
        str(real.get("email") or email).strip().lower(),
        str(real.get("nome") or nome).strip(),
        f"Impersonação (como {email_alvo}): {acao}",
    )


def registrar_log(email: str, nome: str, acao: str, *, dedupe: bool | None = None):
    """
    Grava linha em Log_Acessos.
    Por padrão deduplica por (ação, e-mail) na sessão Streamlit (evita
    regravação em reruns). Eventos de segurança e dedupe=False gravam sempre.
    """
    email_n, nome_n, acao_n = _atribuir_impersonacao(
        (email or "").strip().lower(),
        (nome or "").strip(),
        acao,
    )
    nome_n = nome_n or email_n
    if dedupe is None:
        dedupe = acao_n not in _ACOES_SEM_DEDUPE and not str(acao_n).startswith(
            "Impersonação:"
        )
    chave_log = f"log_{acao_n}_{email_n}"
    if dedupe and st.session_state.get(chave_log):
        return
    try:
        aba_log = planilha.worksheet("Log_Acessos")
        agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
        aba_log.append_row([agora, email_n, nome_n, acao_n])
        if dedupe:
            st.session_state[chave_log] = True
    except Exception:
        pass


def registrar_log_acesso(email: str, nome: str, acao: str):
    registrar_log(email, nome, acao)
