"""Tela do aluno: boletim com componentes e nota final."""

import streamlit as st

from domain.ciclos import obter_disciplina_ativa
from domain.liberacao_notas import notas_finais_liberadas
from domain.notas import calcular_boletim_aluno, nota_final_boletim
from data.sheets import ler_aba
from utils.logs import registrar_log_acesso


def render(usuario: dict):
    st.header("Minhas notas")
    registrar_log_acesso(usuario["email"], usuario["nome"], "Visualizou Minhas Notas")

    id_disc, nome_disc = obter_disciplina_ativa()
    if not id_disc:
        st.warning("Nenhuma disciplina ativa no momento.")
        return

    df_entrancia = ler_aba("Entrancia_Turma")
    vinculo = df_entrancia[
        (df_entrancia["Email_Pessoal"].astype(str).str.lower().str.strip() == usuario["email"])
        & (df_entrancia["ID_Disciplina"].astype(str).str.strip() == str(id_disc).strip())
    ]
    if vinculo.empty:
        st.error("Vínculo com a disciplina ativa não encontrado.")
        return

    grupo = str(vinculo.iloc[0]["Grupo"])
    sala = str(vinculo.iloc[0].get("Sala", "")).strip()
    st.info(f"**Disciplina:** {nome_disc} | **Grupo:** {grupo} | **Sala:** {sala or '—'}")

    df_boletim = calcular_boletim_aluno(usuario["email"], str(id_disc), grupo, sala)
    liberado = notas_finais_liberadas(str(id_disc))

    if liberado:
        nota_final = nota_final_boletim(df_boletim)
        if nota_final is not None:
            st.metric("Nota final parcial da disciplina", f"{nota_final:.1f}")
        else:
            st.metric("Nota final parcial da disciplina", "Pendente")
        st.caption(
            "A nota final considera os pesos configurados pelo orientador "
            "para os componentes já avaliados."
        )
    else:
        st.caption(
            "A nota final ainda não foi calculada. Abaixo, o detalhamento por componente."
        )

    st.subheader("Detalhamento por componente")
    st.dataframe(
        df_boletim,
        width="stretch",
        hide_index=True,
        column_config={
            "Peso (%)": st.column_config.NumberColumn(format="%.1f"),
            "Nota (0-100)": st.column_config.NumberColumn(format="%.1f"),
            "Contribuição": st.column_config.NumberColumn(format="%.2f"),
        },
    )
