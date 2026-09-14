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
    gerar_pdf_recorte,
    media_didatica_professores,
    media_itens_metricas,
    metricas_comparativo_tabela,
    metricas_por_ciclo,
    nps_do_recorte,
    nps_por_ciclo,
    tabela_periodos_ciclos,
    textos_abertos,
)
from utils.logs import registrar_log_acesso


def _disciplinas_disponiveis(df: pd.DataFrame, df_disc: pd.DataFrame) -> list[str]:
    disciplinas = sorted(
        {
            d
            for d in df.get("Disciplina", pd.Series(dtype=str)).dropna().astype(str).str.strip().tolist()
            if d
        }
    )
    if not disciplinas and df_disc is not None and not df_disc.empty:
        disciplinas = sorted(
            {str(n).strip() for n in df_disc["Nome_Disciplina"].tolist() if str(n).strip()}
        )
    return disciplinas


def _default_disciplinas(disciplinas: list[str], df_disc: pd.DataFrame) -> list[str]:
    if not disciplinas:
        return []
    if df_disc is None or df_disc.empty:
        return [disciplinas[0]]
    ativa = df_disc[df_disc["Status"].astype(str).str.strip().str.lower() == "ativo"]
    if not ativa.empty:
        nome_ativa = str(ativa.iloc[0]["Nome_Disciplina"]).strip()
        if nome_ativa in disciplinas:
            return [nome_ativa]
    return [disciplinas[0]]


def _opcoes_ciclos(
    df: pd.DataFrame,
    df_ciclos: pd.DataFrame,
    df_disc: pd.DataFrame,
    discs_sel: list[str],
) -> list[tuple[str, str]]:
    """Lista (id_ciclo, rotulo) para multiselect."""
    ids_disc: set[str] = set()
    if discs_sel and df_disc is not None and not df_disc.empty:
        for nome in discs_sel:
            match = df_disc[df_disc["Nome_Disciplina"].astype(str).str.strip() == nome]
            for _, row in match.iterrows():
                ids_disc.add(str(row["ID_Disciplina"]).strip())

    opcoes: list[tuple[str, str]] = []
    vistos: set[str] = set()

    if df_ciclos is not None and not df_ciclos.empty and "ID_Ciclo" in df_ciclos.columns:
        base = df_ciclos.copy()
        if ids_disc and "ID_Disciplina" in base.columns:
            base = base[base["ID_Disciplina"].astype(str).str.strip().isin(ids_disc)]
        for _, row in base.iterrows():
            cid = str(row["ID_Ciclo"]).strip()
            if not cid or cid in vistos:
                continue
            nome = str(row.get("Nome_Ciclo", "")).strip() or cid
            vistos.add(cid)
            opcoes.append((cid, f"{nome} ({cid})"))

    if not opcoes and {"ID_Ciclo", "Ciclo"}.issubset(df.columns):
        subset = df
        if discs_sel and "Disciplina" in df.columns:
            subset = df[df["Disciplina"].isin(discs_sel)]
        for id_c, nome in subset[["ID_Ciclo", "Ciclo"]].drop_duplicates().itertuples(index=False):
            cid = str(id_c).strip()
            if not cid or cid in vistos:
                continue
            rotulo = f"{str(nome).strip() or cid} ({cid})"
            vistos.add(cid)
            opcoes.append((cid, rotulo))

    return opcoes


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

    disciplinas = _disciplinas_disponiveis(df, df_disc)
    default_disc = _default_disciplinas(disciplinas, df_disc)

    discs_sel = st.multiselect(
        "Disciplinas:",
        options=disciplinas,
        default=default_disc,
        key="dash_curso_discs",
        help="Deixe vazio para todas as disciplinas com resposta.",
    )

    opcoes_ciclo = _opcoes_ciclos(df, df_ciclos, df_disc, discs_sel)
    mapa_label = {rotulo: cid for cid, rotulo in opcoes_ciclo}
    labels_ciclo = [rotulo for _, rotulo in opcoes_ciclo]

    ciclos_labels_sel = st.multiselect(
        "Ciclos:",
        options=labels_ciclo,
        default=labels_ciclo,
        key="dash_curso_ciclos",
        help="Deixe vazio para todos os ciclos do filtro de disciplina.",
    )
    ids_ciclo_sel = [mapa_label[lb] for lb in ciclos_labels_sel if lb in mapa_label]

    modo = st.radio(
        "Modo dos gráficos:",
        options=["Comparar ciclos", "Acumulado do filtro"],
        horizontal=True,
        key="dash_curso_modo",
        help=(
            "**Comparar ciclos**: um valor por ciclo selecionado. "
            "**Acumulado**: junta todas as respostas do filtro num único resultado."
        ),
    )

    recorte = filtrar_respostas(
        df,
        id_ciclo=ids_ciclo_sel or None,
        disciplina=discs_sel or None,
    )
    if recorte.empty:
        st.info("Nenhuma resposta neste filtro.")
        return

    ids_para_datas = ids_ciclo_sel or sorted(
        {str(c).strip() for c in recorte.get("ID_Ciclo", pd.Series(dtype=str)).dropna().tolist() if str(c).strip()}
    )
    periodos = tabela_periodos_ciclos(df_ciclos, ids_para_datas)
    if not periodos.empty:
        st.subheader("Período dos ciclos")
        st.dataframe(
            periodos.rename(
                columns={
                    "Inicio_ciclo": "Início do ciclo",
                    "Fim_ciclo": "Fim do ciclo",
                    "Abertura_pares": "Abertura das pares",
                    "Encerramento_pares": "Encerramento das pares",
                    "Disciplina_ID": "ID disciplina",
                }
            ),
            width="stretch",
            hide_index=True,
        )

    n_alunos = contagem_respondentes(recorte)
    nps = nps_do_recorte(recorte)
    metricas = media_itens_metricas(recorte)
    didatica = media_didatica_professores(recorte)
    nps_ciclos = nps_por_ciclo(recorte)
    met_ciclos = metricas_por_ciclo(recorte)
    met_tabela = metricas_comparativo_tabela(met_ciclos)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Respondentes", n_alunos)
    m2.metric("NPS (acumulado)", f"{nps.nps:.1f}" if nps.nps is not None else "—")
    m3.metric("Promotores", f"{nps.promotores} ({nps.pct_promotores}%)")
    m4.metric("Detratores", f"{nps.detratores} ({nps.pct_detratores}%)")
    st.caption(
        f"Passivos (7–8): **{nps.passivos}** ({nps.pct_passivos}%) · "
        f"base NPS: **{nps.respondentes}** resposta(s)."
    )

    if modo == "Comparar ciclos":
        st.subheader("NPS por ciclo")
        if nps_ciclos.empty:
            st.caption("Sem NPS por ciclo neste recorte.")
        else:
            chart_nps = nps_ciclos.set_index("Rotulo")[["NPS"]].copy()
            st.bar_chart(chart_nps)
            st.dataframe(
                nps_ciclos[["Disciplina", "Ciclo", "NPS", "Respondentes", "Promotores", "Passivos", "Detratores"]],
                width="stretch",
                hide_index=True,
            )

        st.subheader("Métricas por ciclo (0–5)")
        st.caption("Cada critério em uma linha; colunas = disciplina · ciclo; valor = média (N).")
        if met_tabela.empty or len(met_tabela.columns) <= 1:
            st.caption("Sem métricas por ciclo neste recorte.")
        else:
            st.dataframe(met_tabela, width="stretch", hide_index=True)
    else:
        st.subheader("Métricas gerais (0–5) — acumulado")
        if metricas.empty:
            st.caption("Sem notas de métricas neste recorte.")
        else:
            st.dataframe(metricas, width="stretch", hide_index=True)
            st.bar_chart(metricas.set_index("Item")["Média"])

    st.subheader("Didática dos professores (0–5) — acumulado do filtro")
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
        periodos.to_excel(writer, index=False, sheet_name="Periodos")
        metricas.to_excel(writer, index=False, sheet_name="Metricas")
        nps_ciclos.to_excel(writer, index=False, sheet_name="NPS_por_ciclo")
        met_tabela.to_excel(writer, index=False, sheet_name="Metricas_comparativo")
        met_ciclos.to_excel(writer, index=False, sheet_name="Metricas_por_ciclo")
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
                    "Modo_grafico": modo,
                }
            ]
        ).to_excel(writer, index=False, sheet_name="NPS")
        for item in ITENS_TEXTO:
            textos_abertos(recorte, item).to_excel(writer, index=False, sheet_name=item[:31])

    c_dl1, c_dl2 = st.columns(2)
    with c_dl1:
        st.download_button(
            "Baixar Excel do recorte",
            data=buffer.getvalue(),
            file_name="dashboard_avaliacao_curso.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with c_dl2:
        try:
            pdf_bytes = gerar_pdf_recorte(
                disciplinas=discs_sel,
                ciclos_info=periodos,
                nps=nps,
                n_alunos=n_alunos,
                metricas=metricas,
                didatica=didatica,
                modo_grafico=modo,
                nps_ciclos=nps_ciclos if modo == "Comparar ciclos" else None,
                metricas_tabela=met_tabela if modo == "Comparar ciclos" else None,
            )
            st.download_button(
                "Baixar PDF do recorte",
                data=pdf_bytes,
                file_name="dashboard_avaliacao_curso.pdf",
                mime="application/pdf",
            )
        except Exception as exc:
            st.caption(f"PDF indisponível neste ambiente ({exc}). Use o Excel.")
