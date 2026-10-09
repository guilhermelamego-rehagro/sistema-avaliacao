"""Tela do aluno: boletim com componentes e nota final."""

import pandas as pd
import streamlit as st

from domain.atividades_notas import atividades_liberadas, nome_curto_atividade, notas_efetivas
from domain.ciclos import obter_disciplina_ativa
from domain.liberacao_notas import notas_finais_liberadas
from domain.notas import calcular_boletim_aluno, nota_final_boletim, status_academico
from domain.presenca import matriz_frequencia_turma
from data.sheets import ler_aba
from utils.logs import registrar_log_acesso

_SITUACAO = {"Reprovado": "Reprovado por nota", "Reprovado (presença)": "Reprovado por frequência"}


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

    df_boletim = calcular_boletim_aluno(
        usuario["email"], str(id_disc), grupo, sala, somente_atividades_liberadas=True
    )
    liberado = notas_finais_liberadas(str(id_disc))

    if liberado:
        _render_resultado_final(usuario["email"], str(id_disc), nota_final_boletim(df_boletim))
    else:
        st.caption(
            "A nota final ainda não foi calculada. Abaixo, o detalhamento por componente."
        )

    st.subheader("Detalhamento por componente")
    cols_exibir = [
        c
        for c in (
            "Componente",
            "Peso (%)",
            "Nota (0-100)",
            "Contribuição",
            "Detalhe",
        )
        if c in df_boletim.columns
    ]
    st.dataframe(
        df_boletim[cols_exibir],
        width="stretch",
        hide_index=True,
        column_config={
            "Peso (%)": st.column_config.NumberColumn(format="%.1f"),
            "Nota (0-100)": st.column_config.NumberColumn(format="%.1f"),
            "Contribuição": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    _render_atividades_liberadas(usuario["email"], str(id_disc))


def _presenca_aulas(email: str, id_disc: str) -> tuple[int, int]:
    """(presenças, aulas já realizadas) — mesma conta da Liberação de notas; dailies ficam de fora."""
    matriz = matriz_frequencia_turma(id_disc, pd.DataFrame({"Email_Pessoal": [email]}))
    if matriz.empty:
        return 0, 0
    vivido = matriz[~matriz["Status_Tecnico"].isin(["Futuro", "Erro"])]
    return int((vivido["Status_Aluno"] == "Presente").sum()), len(vivido)


def _render_resultado_final(email: str, id_disc: str, nota_final: float | None) -> None:
    presencas, aulas = _presenca_aulas(email, id_disc)
    pct = presencas / aulas * 100 if aulas else None
    status = status_academico(pct, nota_final)

    c1, c2, c3 = st.columns(3)
    c1.metric("Nota final", "Pendente" if nota_final is None else f"{nota_final:.0f}")
    c2.metric(
        "Presença nas aulas",
        "—" if pct is None else f"{pct:.1f}%".replace(".", ","),
        help="Aulas da disciplina (sem as dailies, que já entram como nota).",
    )
    c3.metric("Situação", _SITUACAO.get(status, status))
    if aulas:
        c2.caption(f"{presencas} de {aulas} aulas")

    nota_txt = "" if nota_final is None else f"{nota_final:.0f}"
    if status == "Aprovado":
        st.success(f"Você foi aprovado(a): nota final {nota_txt} (mínimo 70) e presença de pelo menos 75%.")
    elif status == "Recuperação":
        st.warning(
            f"Sua nota final ({nota_txt}) ficou entre 40 e 69: você está em recuperação. "
            "A coordenação vai orientar os próximos passos."
        )
    elif status == "Reprovado":
        st.error(f"Sua nota final ({nota_txt}) ficou abaixo de 40, o mínimo para a recuperação.")
    elif status == "Reprovado (presença)":
        st.error(
            "Sua presença nas aulas ficou abaixo de 75%, o mínimo exigido. "
            "A reprovação por frequência vale independentemente da nota."
        )
    else:
        st.info("Ainda há componentes sem nota; a situação final aparece quando todos forem lançados.")
    st.caption(
        "A nota final soma os componentes com os pesos da disciplina. Aprovação: nota a partir de 70 e "
        "presença a partir de 75%; recuperação: nota de 40 a 69."
    )


def _render_atividades_liberadas(email: str, id_disc: str):
    liberadas = atividades_liberadas(id_disc)
    if not liberadas:
        return
    df = notas_efetivas(id_disc)
    df = df[(df["Email_Aluno"] == email.strip().lower()) & df["ID_Atividade"].isin(liberadas)]
    if df.empty:
        return
    st.subheader("Atividades individuais")
    tabela = pd.DataFrame(
        {
            "Atividade": df["Atividade"].map(nome_curto_atividade),
            "Prazo": df["Prazo"],
            "Nota (0-100)": df["Nota"],
        }
    )
    tabela["_prazo"] = pd.to_datetime(tabela["Prazo"], format="%d/%m/%Y", errors="coerce")
    st.dataframe(
        tabela.sort_values("_prazo").drop(columns="_prazo"),
        width="stretch",
        hide_index=True,
        column_config={"Nota (0-100)": st.column_config.NumberColumn(format="%.1f")},
    )
