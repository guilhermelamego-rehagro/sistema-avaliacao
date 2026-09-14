"""Dashboard de resultados da avaliação do curso (coordenação)."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.dashboard_curso import (
    ITENS_TEXTO,
    carregar_respostas_curso,
    contagem_respondentes,
    filtrar_respostas,
    media_didatica_professores,
    media_itens_metricas,
    nps_do_recorte,
    textos_abertos,
)
from utils.logs import registrar_log_acesso


def render(usuario: dict):
    st.header("Dashboard — avaliação do curso")
    st.caption(
        "Resultados a partir de **Respostas_Curso**. "
        "NPS = % promotores (9–10) − % detratores (0–6), com neutros (7–8) no total."
    )
    registrar_log_acesso(usuario["email"], usuario["nome"], "Dashboard avaliação do curso")

    df = carregar_respostas_curso()
    if df.empty:
        st.warning("Ainda não há respostas de avaliação do curso na planilha.")
        return

    df_disc = ler_aba("Disciplinas")
    df_ciclos = ler_aba("Ciclos")

    disciplinas = sorted(
        {d for d in df.get("Disciplina", pd.Series(dtype=str)).dropna().astype(str).str.strip().tolist() if d}
    )
    if not disciplinas and df_disc is not None and not df_disc.empty:
        disciplinas = df_disc["Nome_Disciplina"].astype(str).tolist()

    opcoes_disc = ["Todas"] + disciplinas
    idx_disc = 0
    if df_disc is not None and not df_disc.empty and disciplinas:
        ativa = df_disc[df_disc["Status"].astype(str).str.strip().str.lower() == "ativo"]
        if not ativa.empty:
            nome_ativa = str(ativa.iloc[0]["Nome_Disciplina"]).strip()
            if nome_ativa in disciplinas:
                idx_disc = disciplinas.index(nome_ativa) + 1

    c1, c2 = st.columns(2)
    with c1:
        disc_sel = st.selectbox(
            "Disciplina:",
            opcoes_disc,
            index=idx_disc,
            key="dash_curso_disc",
        )

    ciclos_opcoes: list[tuple[str, str]] = [("Todos", "Todos")]
    if disc_sel != "Todas" and df_ciclos is not None and not df_ciclos.empty:
        id_disc = ""
        match = df_disc[df_disc["Nome_Disciplina"].astype(str) == disc_sel]
        if not match.empty:
            id_disc = str(match.iloc[0]["ID_Disciplina"]).strip()
        ciclos_disc = (
            df_ciclos[df_ciclos["ID_Disciplina"].astype(str).str.strip() == id_disc]
            if id_disc
            else df_ciclos
        )
        for _, row in ciclos_disc.iterrows():
            ciclos_opcoes.append(
                (str(row["ID_Ciclo"]).strip(), str(row["Nome_Ciclo"]).strip())
            )
    elif {"ID_Ciclo", "Ciclo"}.issubset(df.columns):
        for id_c, nome in df[["ID_Ciclo", "Ciclo"]].drop_duplicates().itertuples(index=False):
            ciclos_opcoes.append((str(id_c).strip(), str(nome).strip() or str(id_c)))

    labels = [
        "Todos" if cid == "Todos" else f"{nome} ({cid})" for cid, nome in ciclos_opcoes
    ]
    with c2:
        escolha = st.selectbox("Ciclo:", labels, key="dash_curso_ciclo")
    id_ciclo_sel = ciclos_opcoes[labels.index(escolha)][0]

    recorte = filtrar_respostas(
        df,
        id_ciclo=None if id_ciclo_sel == "Todos" else id_ciclo_sel,
        disciplina=None if disc_sel == "Todas" else disc_sel,
    )
    if recorte.empty:
        st.info("Nenhuma resposta neste filtro.")
        return

    n_alunos = contagem_respondentes(recorte)
    nps = nps_do_recorte(recorte)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Respondentes", n_alunos)
    m2.metric("NPS", f"{nps.nps:.1f}" if nps.nps is not None else "—")
    m3.metric("Promotores", f"{nps.promotores} ({nps.pct_promotores}%)")
    m4.metric("Detratores", f"{nps.detratores} ({nps.pct_detratores}%)")
    st.caption(
        f"Passivos (7–8): **{nps.passivos}** ({nps.pct_passivos}%) · "
        f"base NPS: **{nps.respondentes}** resposta(s)."
    )

    st.subheader("Métricas gerais (0–5)")
    metricas = media_itens_metricas(recorte)
    if metricas.empty:
        st.caption("Sem notas de métricas neste recorte.")
    else:
        st.dataframe(metricas, width="stretch", hide_index=True)
        st.bar_chart(metricas.set_index("Item")["Média"])

    st.subheader("Didática dos professores (0–5)")
    didatica = media_didatica_professores(recorte)
    if didatica.empty:
        st.caption("Sem avaliações de didática neste recorte.")
    else:
        st.dataframe(didatica, width="stretch", hide_index=True)

    st.subheader("Comentários abertos")
    abas = st.tabs(list(ITENS_TEXTO))
    for aba, item in zip(abas, ITENS_TEXTO):
        with aba:
            textos = textos_abertos(recorte, item)
            if textos.empty:
                st.caption("Nenhum comentário.")
            else:
                st.dataframe(textos, width="stretch", hide_index=True)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        metricas.to_excel(writer, index=False, sheet_name="Metricas")
        didatica.to_excel(writer, index=False, sheet_name="Didatica")
        pd.DataFrame(
            [
                {
                    "NPS": nps.nps,
                    "Respondentes_NPS": nps.respondentes,
                    "Promotores": nps.promotores,
                    "Passivos": nps.passivos,
                    "Detratores": nps.detratores,
                    "Respondentes_unicos": n_alunos,
                }
            ]
        ).to_excel(writer, index=False, sheet_name="NPS")
        for item in ITENS_TEXTO:
            textos_abertos(recorte, item).to_excel(writer, index=False, sheet_name=item[:31])
    st.download_button(
        "Baixar Excel do recorte",
        data=buffer.getvalue(),
        file_name="dashboard_avaliacao_curso.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
