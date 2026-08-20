"""Tela inicial do aluno — calendário e pendências de avaliação."""

import streamlit as st

from domain.ciclos import obter_disciplina_ativa
from domain.status_inicio_aluno import ResumoTarefa, status_avaliacao_curso, status_avaliacao_pares
from navigation import ROTA_CURSO_AVALIAR, ROTA_PARES_AVALIAR, ir_para
from views.prof_calendario import render as render_calendario


def _render_card(tarefa: ResumoTarefa, rota: str):
    badges = {
        "pendente": "Pendente",
        "feito": "Concluída",
        "perdido": "Não realizada",
        "indisponivel": "Indisponível",
    }
    with st.container(border=True):
        st.caption(badges.get(tarefa.status, ""))
        st.markdown(f"**{tarefa.titulo}**")
        if tarefa.status == "feito":
            st.success(tarefa.mensagem)
        elif tarefa.status == "pendente":
            st.info(tarefa.mensagem)
        elif tarefa.status == "perdido":
            st.warning(tarefa.mensagem)
        else:
            st.write(tarefa.mensagem)
        if tarefa.status == "pendente":
            if st.button(
                f"Ir para {tarefa.titulo}",
                key=f"home_btn_{rota}",
                type="primary",
                width="stretch",
            ):
                ir_para(rota)


def render(usuario: dict):
    st.header("Calendário")
    st.caption(f"Olá, **{usuario['nome']}**. Confira a programação e suas avaliações pendentes.")

    id_disc, nome_disc = obter_disciplina_ativa()
    if nome_disc:
        st.info(f"Disciplina ativa: **{nome_disc}**")
    else:
        st.warning("Nenhuma disciplina ativa no momento.")

    if id_disc:
        render_calendario(
            usuario,
            pode_editar=False,
            id_disciplina=id_disc,
            mostrar_cabecalho=False,
            visao_aluno=True,
        )

    st.subheader("Avaliar")
    email = usuario["email"]
    _render_card(status_avaliacao_pares(email), ROTA_PARES_AVALIAR)
    _render_card(status_avaliacao_curso(email), ROTA_CURSO_AVALIAR)

    st.caption(
        "Consulte frequência, dailies, comentários da banca e notas em "
        "**Meu desempenho e participação**, no menu à esquerda."
    )
