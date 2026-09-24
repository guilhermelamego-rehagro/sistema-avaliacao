"""Tela inicial do aluno — calendário e pendências de avaliação."""

import streamlit as st

from domain.ciclos import obter_disciplina_ativa
from domain.plataforma import link_plataforma_disciplina_ativa
from domain.status_inicio_aluno import ResumoTarefa, status_avaliacao_curso, status_avaliacao_pares
from navigation import ROTA_CURSO_AVALIAR, ROTA_PARES_AVALIAR, ir_para
from views.prof_calendario import render as render_calendario

try:
    from navigation import ROTA_INDICACAO_GRUPO_ALUNO
except ImportError:
    ROTA_INDICACAO_GRUPO_ALUNO = "indicacao_grupo_aluno"


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
    link_plataforma = link_plataforma_disciplina_ativa(usuario["email"])
    if nome_disc:
        if link_plataforma:
            col_info, col_link = st.columns([4, 1])
            with col_info:
                st.info(f"Disciplina ativa: **{nome_disc}**")
            with col_link:
                st.link_button(
                    "Disciplina na plataforma",
                    link_plataforma,
                    help="Abrir o curso no Canvas",
                    width="stretch",
                )
        else:
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

    try:
        from domain.indicacao_grupo import janelas_abertas_para_vencedor

        janelas_ind = janelas_abertas_para_vencedor(email)
    except Exception:
        janelas_ind = None
    if janelas_ind is not None and not janelas_ind.empty:
        with st.container(border=True):
            st.caption("Pendente")
            st.markdown("**Indicar colega para o grupo**")
            st.info(
                "Você ficou entre os melhores do ciclo e pode indicar um colega "
                "da oferta para o próximo agrupamento."
            )
            if st.button(
                "Ir para indicação",
                key="home_btn_indicacao_grupo",
                type="primary",
                width="stretch",
            ):
                ir_para(ROTA_INDICACAO_GRUPO_ALUNO)

    st.caption(
        "Consulte frequência, dailies, comentários da banca e notas em "
        "**Meu desempenho e participação**, no menu à esquerda."
    )
