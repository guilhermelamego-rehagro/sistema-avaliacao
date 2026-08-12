"""Liberação da nota final parcial para os alunos."""

import streamlit as st

from data.sheets import ler_aba
from domain.liberacao_notas import notas_finais_liberadas, salvar_liberacao_notas
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.logs import registrar_log


def render(usuario: dict):
    st.header("Liberação de notas finais")
    st.caption(
        "Enquanto a nota final **não estiver liberada**, o aluno vê apenas o detalhamento "
        "por componente em **Minhas notas (boletim)**."
    )

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox(
        "Disciplina:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
        key="lib_notas_disc",
    )
    id_disc = id_disciplina_por_nome(df_disc, disc_sel)

    liberado = notas_finais_liberadas(id_disc)
    if liberado:
        st.success("Nota final **liberada** para os alunos desta disciplina.")
    else:
        st.info("Nota final **oculta** — alunos veem só o grid por componente.")

    c1, c2 = st.columns(2)
    if c1.button("Liberar nota final", type="primary", width="stretch"):
        salvar_liberacao_notas(id_disc, True, usuario["email"], usuario["nome"])
        registrar_log(usuario["email"], usuario["nome"], f"Liberou nota final — {disc_sel}")
        st.success("Nota final liberada!")
        st.rerun()

    if c2.button("Ocultar nota final", width="stretch"):
        salvar_liberacao_notas(id_disc, False, usuario["email"], usuario["nome"])
        registrar_log(usuario["email"], usuario["nome"], f"Ocultou nota final — {disc_sel}")
        st.success("Nota final ocultada para os alunos.")
        st.rerun()
