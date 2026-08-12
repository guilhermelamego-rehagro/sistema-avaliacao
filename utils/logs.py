"""Registro de acessos na planilha Log_Acessos."""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from data.sheets import planilha


def registrar_log(email: str, nome: str, acao: str):
    chave_log = f"log_{acao}_{email}"
    if st.session_state.get(chave_log):
        return
    try:
        aba_log = planilha.worksheet("Log_Acessos")
        agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
        aba_log.append_row([agora, email, nome, acao])
        st.session_state[chave_log] = True
    except Exception:
        pass


def registrar_log_acesso(email: str, nome: str, acao: str):
    registrar_log(email, nome, acao)
