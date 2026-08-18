"""Lançamento manual de presença nos dias do encontro presencial."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.cadastros import carregar_disciplinas
from domain.encontro_presencial import (
    STATUS_PRESENCA,
    carregar_presenca_encontro,
    datas_encontro_ativas,
    disciplina_tem_encontro_presencial,
    salvar_presenca_encontro,
)
from utils.disciplina import normalizar_id
from utils.logs import registrar_log
from utils.ordenacao import ordenar_grupos_lista
from utils.preferencias_sala import selectbox_sala


def render(usuario: dict):
    st.header("Presença no encontro presencial")
    st.caption(
        "Lance Presente ou Falta em cada dia cadastrado. "
        "O lançamento vale na frequência das aulas (ajuste manual) e fica registrado neste encontro."
    )

    df_disc = carregar_disciplinas()
    presenciais = df_disc[df_disc["Encontro_Presencial"].astype(str).str.strip() == "Sim"]
    if presenciais.empty:
        st.info("Nenhuma disciplina está marcada com encontro presencial no cadastro.")
        return

    opcoes = [
        f"{row['ID_Disciplina']} — {row['Nome_Disciplina']}"
        for _, row in presenciais.iterrows()
    ]
    disc_sel = st.selectbox("Disciplina:", opcoes, key="enc_pres_disc")
    id_disc = disc_sel.split(" — ")[0].strip()
    if not disciplina_tem_encontro_presencial(id_disc):
        st.warning("Esta disciplina não tem encontro presencial.")
        return

    datas = datas_encontro_ativas(id_disc)
    if datas.empty:
        st.warning("Cadastre as datas do encontro em **Cadastro de disciplinas**.")
        return

    rotulos = []
    mapa = {}
    for _, row in datas.iterrows():
        data_ref = pd.Timestamp(row["_parsed"]).date()
        desc = str(row.get("Descricao", "")).strip()
        rotulo = data_ref.strftime("%d/%m/%Y")
        if desc:
            rotulo = f"{rotulo} — {desc}"
        rotulos.append(rotulo)
        mapa[rotulo] = data_ref

    data_sel = st.selectbox("Dia do encontro:", rotulos, key="enc_pres_data")
    data_ref = mapa[data_sel]

    df_entrancia = ler_aba("Entrancia_Turma")
    alunos = df_entrancia[
        df_entrancia["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disc)
    ].copy()
    if alunos.empty:
        st.warning("Nenhum aluno vinculado a esta disciplina na entrância.")
        return

    salas = ordenar_grupos_lista(alunos["Sala"].dropna().astype(str).unique().tolist())
    grupos = ordenar_grupos_lista(alunos["Grupo"].dropna().astype(str).unique().tolist())
    c1, c2, c3 = st.columns(3)
    with c1:
        sala_sel = selectbox_sala("Sala:", salas, key="enc_pres_sala", usuario=usuario)
    grupo_sel = c2.selectbox("Grupo:", ["Todos"] + grupos, key="enc_pres_grupo")
    nome_busca = c3.text_input("Buscar aluno:", key="enc_pres_nome")

    filtrados = alunos.copy()
    if sala_sel != "Todas":
        filtrados = filtrados[filtrados["Sala"].astype(str).str.strip() == sala_sel]
    if grupo_sel != "Todos":
        filtrados = filtrados[filtrados["Grupo"].astype(str).str.strip() == grupo_sel]
    if nome_busca:
        filtrados = filtrados[
            filtrados["Nome_Completo"].astype(str).str.contains(nome_busca, case=False, na=False)
        ]
    if filtrados.empty:
        st.warning("Nenhum aluno encontrado com esses filtros.")
        return

    ja = carregar_presenca_encontro(id_disc, data_ref)
    mapa_status = {}
    if not ja.empty:
        for _, row in ja.iterrows():
            email = str(row.get("Email_Aluno", "")).strip().lower()
            mapa_status[email] = str(row.get("Status", "")).strip()

    grid = pd.DataFrame(
        {
            "Nome_Aluno": filtrados["Nome_Completo"].astype(str),
            "Sala": filtrados["Sala"].astype(str).str.strip(),
            "Grupo": filtrados["Grupo"].astype(str).str.strip(),
            "Email_Aluno": filtrados["Email_Pessoal"].astype(str).str.strip().str.lower(),
            "Status": [
                mapa_status.get(str(e).strip().lower(), "")
                for e in filtrados["Email_Pessoal"].tolist()
            ],
        }
    ).sort_values("Nome_Aluno")

    chave_work = f"enc_pres_work_{id_disc}_{data_ref}_{sala_sel}_{grupo_sel}_{nome_busca}"
    if st.session_state.get("enc_pres_work_key") != chave_work:
        st.session_state["enc_pres_work_key"] = chave_work
        st.session_state["enc_pres_work"] = grid.reset_index(drop=True)

    b1, b2, _ = st.columns([1, 1, 2])
    if b1.button("Marcar filtrados como Presente"):
        atual = st.session_state["enc_pres_work"].copy()
        atual["Status"] = "Presente"
        st.session_state["enc_pres_work"] = atual
        st.rerun()
    if b2.button("Marcar filtrados como Falta"):
        atual = st.session_state["enc_pres_work"].copy()
        atual["Status"] = "Falta"
        st.session_state["enc_pres_work"] = atual
        st.rerun()

    edited = st.data_editor(
        st.session_state["enc_pres_work"],
        column_config={
            "Nome_Aluno": st.column_config.TextColumn("Aluno", disabled=True),
            "Sala": st.column_config.TextColumn("Sala", disabled=True),
            "Grupo": st.column_config.TextColumn("Grupo", disabled=True),
            "Email_Aluno": None,
            "Status": st.column_config.SelectboxColumn(
                "Presença",
                options=[""] + STATUS_PRESENCA,
                help="Vazio não é gravado.",
            ),
        },
        column_order=["Nome_Aluno", "Sala", "Grupo", "Status"],
        hide_index=True,
        width="stretch",
        disabled=["Nome_Aluno", "Sala", "Grupo"],
        key=f"enc_pres_grid_{chave_work}",
    )
    st.session_state["enc_pres_work"] = edited

    preenchidos = edited[edited["Status"].astype(str).str.strip().isin(STATUS_PRESENCA)]
    st.caption(
        f"{len(preenchidos)} de {len(edited)} aluno(s) com presença preenchida neste recorte."
    )

    if st.button("Salvar presença deste dia", type="primary"):
        erro = salvar_presenca_encontro(id_disc, data_ref, edited, usuario)
        if erro:
            st.error(erro)
        else:
            registrar_log(
                usuario["email"],
                usuario["nome"],
                f"Lançou presença do encontro {id_disc} em {data_ref.strftime('%d/%m/%Y')}",
            )
            st.success("Presença salva para este dia.")
            st.rerun()
