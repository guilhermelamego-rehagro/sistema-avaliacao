"""Tela do orientador: configurar componentes e pesos da disciplina."""

import pandas as pd
import streamlit as st

from config import TIPOS_COMPONENTE_LABEL
from data.sheets import ler_aba
from domain.componentes import (
    carregar_componentes_disciplina,
    label_para_tipo,
    novo_componente_vazio,
    opcoes_tipo_label,
    salvar_componentes_disciplina,
)
from utils.logs import registrar_log


def render(usuario: dict):
    st.header("Componentes da disciplina")
    st.caption(
        "Cadastre os componentes da disciplina, defina o **tipo** (regra de cálculo) "
        "e o **peso**. A soma dos pesos deve ser **100%**."
    )
    st.info(
        "**Ciclo e Entrega final** usam a mesma fórmula: "
        "orientador (60%) + pares (40%), multiplicado pela nota do grupo.\n\n"
        "O comportamento da **Entrega final** depende da disciplina:\n"
        "- **Sem avaliação própria:** grupo, pares e orientador são os do último ciclo "
        "(em geral o Ciclo 4).\n"
        "- **Com encontro presencial e avaliação própria:** vincule a um ciclo **próprio**. "
        "Essa opção é perguntada ao ativar a disciplina com encontro presencial."
    )

    df_disc = ler_aba("Disciplinas")
    lista = df_disc["Nome_Disciplina"].unique().tolist()
    ativas = df_disc[df_disc["Status"].astype(str).str.lower().isin(["ativo", "ativa"])]
    idx = 0
    if not ativas.empty and ativas.iloc[0]["Nome_Disciplina"] in lista:
        idx = lista.index(ativas.iloc[0]["Nome_Disciplina"])

    disc_sel = st.selectbox("Disciplina:", lista, index=idx)
    id_disc = str(df_disc[df_disc["Nome_Disciplina"] == disc_sel].iloc[0]["ID_Disciplina"]).strip()

    df_ciclos = ler_aba("Ciclos")
    ciclos_disc = df_ciclos[df_ciclos["ID_Disciplina"].astype(str).str.strip() == id_disc]
    opcoes_ciclos = [""] + [
        f"{r['ID_Ciclo']} | {r['Nome_Ciclo']}"
        for _, r in ciclos_disc.iterrows()
    ]

    chave = f"comp_edit_{id_disc}"
    if chave not in st.session_state:
        st.session_state[chave] = carregar_componentes_disciplina(id_disc)

    df_edit = st.session_state[chave].copy()

    def _fmt_ciclo(id_ciclo: str) -> str:
        id_c = str(id_ciclo).strip()
        if not id_c:
            return ""
        match = ciclos_disc[ciclos_disc["ID_Ciclo"].astype(str).str.strip() == id_c]
        if not match.empty:
            return f"{id_c} | {match.iloc[0]['Nome_Ciclo']}"
        return id_c

    df_edit["ID_Ciclo"] = df_edit["ID_Ciclo"].apply(_fmt_ciclo)
    df_edit["Tipo_Label"] = df_edit["Tipo"].map(TIPOS_COMPONENTE_LABEL).fillna(df_edit["Tipo"])

    c1, c2, c3 = st.columns(3)
    peso_total = float(df_edit["Peso"].sum())
    if abs(peso_total - 100) < 0.01:
        c1.success(f"Peso total: **{peso_total:.1f}%** ✓")
    else:
        c1.warning(f"Peso total: **{peso_total:.1f}%** (meta: 100%)")
    c2.metric("Componentes", len(df_edit))

    if c3.button("➕ Adicionar componente", width="stretch"):
        prox = int(df_edit["Ordem"].max()) + 1 if not df_edit.empty else 1
        df_edit = pd.concat(
            [df_edit, pd.DataFrame([novo_componente_vazio(id_disc, prox)])],
            ignore_index=True,
        )
        df_edit["Tipo_Label"] = df_edit["Tipo"].map(TIPOS_COMPONENTE_LABEL).fillna(df_edit["Tipo"])
        st.session_state[chave] = df_edit
        st.rerun()

    st.markdown("#### Grid de componentes")
    edited = st.data_editor(
        df_edit[
            ["ID_Componente", "Nome", "Tipo_Label", "Peso", "Ordem", "ID_Ciclo", "Ativo"]
        ],
        column_config={
            "ID_Componente": st.column_config.TextColumn("ID", disabled=True),
            "Nome": st.column_config.TextColumn("Nome exibido", required=True),
            "Tipo_Label": st.column_config.SelectboxColumn(
                "Tipo",
                options=opcoes_tipo_label(),
                required=True,
            ),
            "Peso": st.column_config.NumberColumn("Peso %", min_value=0, max_value=100, step=0.5),
            "Ordem": st.column_config.NumberColumn("Ordem", min_value=1, step=1),
            "ID_Ciclo": st.column_config.SelectboxColumn(
                "Vínculo ciclo",
                options=opcoes_ciclos,
                help="Obrigatório para tipos Ciclo e Entrega final. Formato: ID | Nome",
            ),
            "Ativo": st.column_config.SelectboxColumn("Ativo", options=["Sim", "Não"]),
        },
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        key=f"editor_{id_disc}",
    )

    st.info(
        "**Tipos fixos (regra de cálculo):**\n"
        "- **Ciclo / Entrega final** → orientador (60%) + pares (40%), multiplicado pela nota do grupo\n"
        "- **Reunião diária** → % de presença nas dailies\n"
        "- **Avaliação individual** → média das atividades (Canvas ou manual)"
    )

    if st.button("💾 Salvar configuração", type="primary", width="stretch"):
        df_save = edited.copy()
        df_save["Tipo"] = df_save["Tipo_Label"].apply(label_para_tipo)
        df_save["ID_Disciplina"] = id_disc

        for idx_row, row in df_save.iterrows():
            vinculo = str(row.get("ID_Ciclo", "")).strip()
            if "|" in vinculo:
                df_save.at[idx_row, "ID_Ciclo"] = vinculo.split("|")[0].strip()
            else:
                df_save.at[idx_row, "ID_Ciclo"] = vinculo

        erro = salvar_componentes_disciplina(id_disc, df_save)
        if erro:
            st.error(erro)
        else:
            registrar_log(usuario["email"], usuario["nome"], f"Salvou componentes - {disc_sel}")
            st.session_state[chave] = carregar_componentes_disciplina(id_disc)
            st.success("Configuração salva na planilha!")
            st.rerun()
