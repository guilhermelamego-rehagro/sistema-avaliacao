"""Liberação da nota final parcial para os alunos + painel de boletins."""

from __future__ import annotations

import streamlit as st

from data.sheets import ler_aba
from domain.liberacao_notas import notas_finais_liberadas, salvar_liberacao_notas
from domain.notas import montar_painel_boletins_disciplina
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

    # Marcador visível imediatamente (antes do cálculo pesado) — confirma que a versão nova carregou.
    st.divider()
    st.subheader("Boletins da disciplina")
    st.caption(
        "Presença **realizada** (aulas + encontro presencial, quando houver). "
        "Status: presença < 75% → reprovado por presença; "
        "com presença ≥ 75%: nota < 40 reprovado · 40–69,9 recuperação · ≥ 70 aprovado."
    )

    with st.spinner("Calculando boletins e frequências…"):
        try:
            df_painel = montar_painel_boletins_disciplina(id_disc)
        except Exception as exc:
            st.error(f"Não foi possível montar o painel de boletins: {exc}")
            return

    if df_painel.empty:
        st.warning("Nenhum aluno encontrado nesta disciplina.")
        return

    # Contagens rápidas de status
    if "Status" in df_painel.columns:
        contagem = df_painel["Status"].value_counts()
        cols_m = st.columns(min(len(contagem), 4) or 1)
        for i, (status, qtd) in enumerate(contagem.items()):
            cols_m[i % len(cols_m)].metric(str(status), int(qtd))

    st.dataframe(
        df_painel,
        width="stretch",
        hide_index=True,
        height=min(52 + 35 * len(df_painel), 720),
        column_config={
            "Presença (%)": st.column_config.NumberColumn(format="%.1f"),
        },
    )

    csv = df_painel.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Baixar boletins (CSV)",
        data=csv,
        file_name=f"boletins_{id_disc}.csv",
        mime="text/csv",
        width="stretch",
    )
