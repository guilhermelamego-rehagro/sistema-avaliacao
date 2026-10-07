"""Tela da secretaria: relatório estático de notas finais por disciplina, com histórico de alterações."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from data import supabase_relatorio_secretaria as repo
from domain.liberacao_notas import notas_finais_liberadas
from domain.relatorio_secretaria import TEXTO, fmt_data_hora
from utils.ordenacao import chave_ordenacao_texto

_COLUNAS_LOG = {
    "alterado_em": "Data",
    "nome": "Aluno",
    "turma": "Turma",
    "campo": "Campo",
    "antes": "Antes",
    "depois": "Depois",
    "alterado_por_nome": "Publicado por",
}


def _excel(notas: pd.DataFrame, alteracoes: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        notas.to_excel(writer, index=False, sheet_name="Notas", na_rep="")
        alteracoes.to_excel(writer, index=False, sheet_name="Alterações")
    return buf.getvalue()


def render(usuario: dict) -> None:
    st.header("Relatório de notas finais")
    st.caption(
        "Por aluno: nota total de cada ciclo, atividades, dailies, presença, nota final e situação. "
        "O relatório é publicado pelos professores quando liberam a nota final e só muda quando eles "
        "publicam uma atualização; cada mudança aparece em **Histórico de alterações**."
    )
    try:
        publicados = repo.listar()
    except repo.RelatorioIndisponivel:
        st.error("Relatório indisponível no momento. Tente novamente em instantes.")
        return
    disponiveis = {
        (p.get("nome_disciplina") or p["id_disciplina"]): p["id_disciplina"]
        for p in sorted(publicados, key=lambda p: chave_ordenacao_texto(p.get("nome_disciplina") or ""))
        if notas_finais_liberadas(p["id_disciplina"])
    }
    if not disponiveis:
        st.info("Nenhuma disciplina com notas finais liberadas ainda.")
        return

    nome_disc = st.selectbox("Disciplina:", list(disponiveis), key="sec_rel_disc")
    id_disc = disponiveis[nome_disc]
    try:
        relatorio = repo.ler(id_disc)
        alteracoes = repo.listar_alteracoes(id_disc)
    except repo.RelatorioIndisponivel:
        st.error("Relatório indisponível no momento. Tente novamente em instantes.")
        return
    if relatorio is None:
        st.info("Relatório ainda não publicado para esta disciplina.")
        return

    colunas = list(relatorio.get("colunas") or [])
    df = pd.DataFrame(relatorio.get("linhas") or [], columns=["Email", *colunas])
    for col in colunas:
        if col not in TEXTO:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values(["Turma", "Nome"], key=lambda s: s.map(chave_ordenacao_texto), kind="stable")

    st.caption(
        f"Publicado em **{fmt_data_hora(relatorio['gerado_em'])}** por {relatorio.get('gerado_por_nome') or '—'} "
        f"· {len(df)} alunos."
    )

    f1, f2, f3 = st.columns([2, 1.2, 1.2])
    busca = f1.text_input("Filtrar por aluno:", key=f"sec_rel_busca_{id_disc}", placeholder="Nome (parcial)").strip()
    turmas = sorted({t for t in df["Turma"] if t}, key=chave_ordenacao_texto)
    turmas_sel = f2.multiselect("Turma:", turmas, key=f"sec_rel_turma_{id_disc}")
    situacoes_sel = f3.multiselect("Situação:", sorted(set(df["Status"])), key=f"sec_rel_status_{id_disc}")

    vista = df
    if busca:
        vista = vista[vista["Nome"].str.contains(busca, case=False, na=False, regex=False)]
    if turmas_sel:
        vista = vista[vista["Turma"].isin(turmas_sel)]
    if situacoes_sel:
        vista = vista[vista["Status"].isin(situacoes_sel)]

    contagem = vista["Status"].value_counts()
    if not contagem.empty:
        cols_m = st.columns(min(len(contagem), 4))
        for i, (status, qtd) in enumerate(contagem.items()):
            cols_m[i % len(cols_m)].metric(str(status), int(qtd))

    if relatorio.get("legendas"):
        with st.expander("Legenda dos cabeçalhos", expanded=False):
            st.caption(" · ".join(relatorio["legendas"]))

    config: dict = {
        "Turma": st.column_config.TextColumn("Turma", width="small"),
        "Pres.%": st.column_config.NumberColumn("Pres.%", format="%.1f", width="small"),
        "Final": st.column_config.NumberColumn("Final", format="%.0f", width="small"),
        "Status": st.column_config.TextColumn("Situação", width="medium"),
    }
    for col in colunas:
        config.setdefault(col, st.column_config.NumberColumn(col, format="%.1f", width="small"))
    st.dataframe(
        vista.drop(columns=["Email"]).set_index("Nome"),
        width="stretch",
        height=min(52 + 35 * len(vista), 720),
        column_config=config,
    )

    log = pd.DataFrame(alteracoes, columns=list(_COLUNAS_LOG))
    log["alterado_em"] = log["alterado_em"].map(fmt_data_hora)
    log = log.rename(columns=_COLUNAS_LOG)
    st.subheader(f"Histórico de alterações ({len(log)})")
    if log.empty:
        st.caption("Nenhuma alteração registrada.")
    else:
        st.caption("Mais recentes primeiro. Notas com 1 casa decimal; nota final arredondada para inteiro.")
        st.dataframe(log, hide_index=True, width="stretch", height=min(38 + 35 * len(log), 420))

    st.download_button(
        "Baixar relatório (Excel)",
        data=_excel(vista.rename(columns={"Status": "Situação"}), log),
        file_name=f"relatorio_notas_{id_disc}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"sec_rel_xlsx_{id_disc}",
        help="Alunos do filtro atual (com e-mail) na aba Notas e o histórico completo na aba Alterações.",
    )
