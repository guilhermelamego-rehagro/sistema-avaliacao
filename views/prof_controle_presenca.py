"""Controle de presença em aulas e dailies (professor/secretaria)."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.presenca import carregar_base_presenca, compilar_grid_dailies, compilar_grid_frequencia
from domain.cadastros import carregar_disciplinas
from utils.disciplina import normalizar_id, remapear_coluna_id_disciplina
from utils.ordenacao import ordenar_grupos_lista
from utils.preferencias_sala import multiselect_sala


def _ordenacao_natural(lista) -> list:
    return ordenar_grupos_lista([str(x) for x in lista])


def render(usuario: dict, tipo: str = "aulas"):
    eh_dailies = tipo == "dailies"
    st.header("Controle de dailies" if eh_dailies else "Controle de frequência")
    if eh_dailies:
        st.caption("Participação nas reuniões de orientação (dailies) por aluno e data.")

    df_entrancia = ler_aba("Entrancia_Turma")
    df_disciplinas = ler_aba("Disciplinas")
    df_alunos_base = ler_aba("Base_Alunos")
    atuais = {
        normalizar_id(row["ID_Disciplina"]): str(row.get("Nome_Disciplina", "")).strip()
        for _, row in carregar_disciplinas().iterrows()
        if normalizar_id(row.get("ID_Disciplina", ""))
    }
    if atuais:
        df_entrancia = remapear_coluna_id_disciplina(df_entrancia, atuais)

    lista_opcoes = df_disciplinas.apply(
        lambda x: f"{x['ID_Disciplina']} - {x['Nome_Disciplina']}", axis=1
    ).tolist()
    idx_ativo = 0
    ativas = df_disciplinas[df_disciplinas["Status"].astype(str).str.strip().str.lower() == "ativo"]
    if not ativas.empty:
        id_ativo = str(ativas.iloc[0]["ID_Disciplina"]).strip()
        for i, val in enumerate(lista_opcoes):
            if val.startswith(id_ativo):
                idx_ativo = i
                break

    disc_sel = st.selectbox(
        "Selecione a Disciplina para análise:",
        lista_opcoes,
        index=idx_ativo,
        key=f"presenca_disc_{tipo}",
    )
    id_disciplina_sel = disc_sel.split(" - ")[0]

    alunos_turma = df_entrancia[
        df_entrancia["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disciplina_sel)
    ].copy()
    if alunos_turma.empty:
        st.warning(
            "Nenhum aluno na Entrância com este código de disciplina. "
            "Se o cadastro foi recodificado (ex.: 20263TRI → TRIB), os vínculos da aba "
            "Entrancia_Turma na planilha de produção ainda podem estar no código antigo."
        )

    if "Email_Pessoal" in df_alunos_base.columns and "Turma_Ingresso" in df_alunos_base.columns:
        alunos_turma = pd.merge(
            alunos_turma,
            df_alunos_base[["Email_Pessoal", "Turma_Ingresso"]],
            on="Email_Pessoal",
            how="left",
        )

    with st.spinner("Compilando presença..."):
        memoria_cache = carregar_base_presenca()
        memoria_cache["entrancia"] = df_entrancia
        if eh_dailies:
            df_resumo, df_raw = compilar_grid_dailies(
                id_disciplina_sel, alunos_turma, memoria_cache
            )
        else:
            df_resumo, df_raw = compilar_grid_frequencia(
                id_disciplina_sel, alunos_turma, memoria_cache
            )

    if df_raw.empty:
        st.info(
            "Nenhuma daily registrada ainda para esta disciplina."
            if eh_dailies
            else "Nenhuma aula registrada ainda para esta disciplina."
        )
        return

    datas_unicas = df_raw[["Data_Sort", "Data_Visual"]].drop_duplicates().sort_values("Data_Sort")
    colunas_datas_ordenadas = datas_unicas["Data_Visual"].tolist()

    df_pivot = (
        df_raw.pivot(index="Email_Cru", columns="Data_Visual", values="Status")
        .reset_index()
        .fillna("-")
    )
    df_final = pd.merge(df_resumo, df_pivot, on="Email_Cru", how="left")

    turmas_opcoes = _ordenacao_natural(df_final["Turma"].unique())
    salas_opcoes = _ordenacao_natural(df_final["Sala"].unique())
    grupos_opcoes = _ordenacao_natural(df_final["Grupo"].unique())

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    turma_filtro = c1.multiselect("Filtrar por Turma:", turmas_opcoes, key=f"presenca_turma_{tipo}")
    with c2:
        sala_filtro = multiselect_sala(salas_opcoes, key=f"presenca_sala_{tipo}", usuario=usuario)
    grupo_filtro = c3.multiselect("Filtrar por Grupo:", grupos_opcoes, key=f"presenca_grupo_{tipo}")

    c4, c5, c6 = st.columns([2, 2, 1.4])
    nome_busca = c4.text_input("Buscar por Nome do Aluno:", key=f"presenca_nome_{tipo}")
    faixa_projetada = c5.slider(
        "Filtrar por % Projetada:",
        min_value=0.0,
        max_value=100.0,
        value=(0.0, 100.0),
        format="%.0f%%",
        key=f"presenca_faixa_{tipo}",
    )
    filtro_seguidas = c6.checkbox(
        "2 ou mais faltas seguidas",
        value=False,
        key=f"presenca_seguidas_{tipo}",
        help=(
            "Mostra só quem está com 2 ou mais faltas consecutivas "
            "nas últimas aulas/dailies já realizadas desta modalidade. "
            "Conexão abaixo de 30 min conta como falta."
        ),
    )

    opcao_todas = "(todas as datas)"
    mapa_datas: dict[str, pd.Timestamp] = {}
    for _, row_data in datas_unicas.iterrows():
        data_ref = pd.Timestamp(row_data["Data_Sort"]).normalize()
        rotulo = data_ref.strftime("%d/%m/%Y")
        mapa_datas[rotulo] = data_ref
    data_falta = st.selectbox(
        "Faltantes em uma data:",
        [opcao_todas] + list(mapa_datas.keys()),
        key=f"presenca_data_falta_{tipo}",
        help=(
            "Lista só quem faltou na data escolhida. "
            "Conexão abaixo de 30 min conta como falta."
        ),
    )

    if turma_filtro:
        df_final = df_final[df_final["Turma"].isin(turma_filtro)]
    if sala_filtro:
        df_final = df_final[df_final["Sala"].isin(sala_filtro)]
    if grupo_filtro:
        df_final = df_final[df_final["Grupo"].isin(grupo_filtro)]
    if nome_busca:
        df_final = df_final[df_final["Nome"].str.contains(nome_busca, case=False, na=False)]

    df_final = df_final[
        (df_final["% Projetado"] >= faixa_projetada[0])
        & (df_final["% Projetado"] <= faixa_projetada[1])
    ]
    if filtro_seguidas:
        df_final = df_final[df_final["Faltas seguidas"] >= 2]
    if data_falta != opcao_todas:
        data_ref = mapa_datas[data_falta]
        df_dia = df_raw.copy()
        df_dia["Data_Norm"] = pd.to_datetime(df_dia["Data_Sort"], errors="coerce").dt.normalize()
        emails_faltaram = df_dia[
            (df_dia["Data_Norm"] == data_ref)
            & (df_dia["Status"].isin(["❌", "⏳"]))
        ]["Email_Cru"]
        df_final = df_final[df_final["Email_Cru"].isin(emails_faltaram)]

    if df_final.empty:
        if data_falta != opcao_todas:
            aviso = f"Nenhum aluno faltou em {data_falta} com os filtros atuais."
        elif filtro_seguidas:
            aviso = "Nenhum aluno com 2 ou mais faltas seguidas nesta modalidade."
        else:
            aviso = "Nenhum aluno encontrado com esses filtros."
        st.warning(aviso)
        return

    if data_falta != opcao_todas:
        st.warning(
            f"**{len(df_final)}** aluno(s) faltaram em **{data_falta}** "
            f"{'nas dailies' if eh_dailies else 'nas aulas'}."
        )
    if filtro_seguidas:
        st.warning(
            f"**{len(df_final)}** aluno(s) com 2 ou mais faltas seguidas "
            f"{'nas dailies' if eh_dailies else 'nas aulas'} — priorize a abordagem."
        )
        df_final = df_final.sort_values(["Faltas seguidas", "Nome"], ascending=[False, True])
    else:
        df_final = df_final.sort_values("Nome")

    df_final = df_final.set_index("Nome")
    cols_fixas = ["Turma", "Sala", "Grupo", "% Realizado", "% Projetado", "Faltas seguidas"]
    cols_finais = cols_fixas + [c for c in colunas_datas_ordenadas if c in df_final.columns]
    df_final = df_final[cols_finais]

    df_excel = df_final.copy().replace({"✅": "P", "❌": "F", "⏳": "C", "✏️": "A", "📅": "N"})
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_excel.to_excel(writer, index=True, sheet_name="Dailies" if eh_dailies else "Frequencia")

    col_exp, _ = st.columns([1, 2])
    col_exp.download_button(
        label="📥 Exportar Dados para Excel (.xlsx)",
        data=buffer.getvalue(),
        file_name=f"{'Dailies' if eh_dailies else 'Controle_Frequencia'}_{id_disciplina_sel}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"presenca_xlsx_{tipo}",
    )

    config_colunas = {
        "% Realizado": st.column_config.NumberColumn("% Realizado", format="%.1f %%"),
        "% Projetado": st.column_config.NumberColumn("% Projetado", format="%.1f %%"),
        "Faltas seguidas": st.column_config.NumberColumn(
            "Faltas seguidas",
            help="Faltas consecutivas nas últimas sessões já realizadas.",
            format="%d",
        ),
    }
    if eh_dailies:
        st.caption(
            "Legenda: ✅ Participou | ❌ Faltou | 📅 Daily futura. "
            "**Faltas seguidas** conta só as últimas dailies já realizadas."
        )
    else:
        st.caption(
            "Legenda na tela: ✅ Presente | ❌ Falta | ⏳ Conectado (<30min) | "
            "✏️ Ajuste Manual | 📅 Aula futura. "
            "**Faltas seguidas** conta só as últimas aulas já realizadas "
            "(conexão < 30 min entra como falta)."
        )
    st.dataframe(df_final, width="stretch", column_config=config_colunas)
