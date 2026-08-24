"""Link da disciplina na plataforma (Canvas) conforme a oferta ativa."""

from __future__ import annotations

import streamlit as st

from domain.ciclos import obter_disciplina_ativa
from domain.planejamento import carregar_ofertas, resumo_participantes
from utils.disciplina import normalizar_id


def _link_valido(valor) -> str:
    texto = str(valor or "").strip()
    if not texto or texto.lower() in {"nan", "none"}:
        return ""
    if texto.startswith(("http://", "https://")):
        return texto
    return ""


@st.cache_data(ttl=300, show_spinner=False)
def link_plataforma_para_aluno(email: str, id_disciplina: str) -> str:
    """URL do Canvas da oferta ativa em que o aluno participa (ou única oferta ativa)."""
    id_disc = normalizar_id(id_disciplina)
    email_limpo = str(email or "").strip().lower()
    if not id_disc or not email_limpo:
        return ""

    ofertas = carregar_ofertas()
    ativas = ofertas[
        (ofertas["ID_Disciplina"].map(normalizar_id) == id_disc)
        & (ofertas["Status"].astype(str).str.strip() == "Ativa")
    ]
    com_link: list[tuple[str, str]] = []
    for _, row in ativas.iterrows():
        link = _link_valido(row.get("Link_Plataforma"))
        if link:
            com_link.append((normalizar_id(row["ID_Oferta"]), link))

    if not com_link:
        return ""
    if len(com_link) == 1:
        return com_link[0][1]

    for id_oferta, link in com_link:
        resumo = resumo_participantes(id_oferta)
        alunos = resumo.get("alunos")
        if alunos is not None and not alunos.empty:
            emails = set(alunos["Email_Aluno"].astype(str).str.strip().str.lower())
            if email_limpo in emails:
                return link

    return ""


def link_plataforma_disciplina_ativa(email: str) -> str:
    id_disc, _ = obter_disciplina_ativa()
    if not id_disc:
        return ""
    return link_plataforma_para_aluno(email, str(id_disc))
