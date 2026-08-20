"""Anotações de orientação nas dailies (por sala, grupo e data)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from auth.supabase_auth import professor_e_orientador
from data.sheets import ler_aba
from domain.anotacoes_daily import (
    anotacoes_do_grupo,
    data_daily_padrao,
    datas_dailies_disciplina,
    salvar_anotacao,
)
from domain.cadastros import sala_padrao_orientador
from domain.ciclos import ciclo_na_data
from utils.disciplina import normalizar_id
from utils.logs import registrar_log
from utils.ordenacao import ordenar_grupos_lista
from utils.preferencias_sala import selectbox_sala


def _grupos_da_sala(alunos: pd.DataFrame, sala: str) -> list[str]:
    bloco = alunos
    if sala and sala != "Todas":
        bloco = alunos[alunos["Sala"].astype(str).str.strip() == str(sala).strip()]
    return ordenar_grupos_lista(bloco["Grupo"].dropna().astype(str).unique().tolist())


def render_pagina(usuario: dict):
    st.header("Anotações da daily")
    st.caption(
        "Um texto por grupo e data. A sala vem do cadastro da orientadora e pode ser trocada. "
        "O ciclo é inferido pelo período acadêmico (início do ciclo até a apresentação)."
    )
    from domain.cadastros import carregar_disciplinas
    from utils.disciplina import indice_disciplina_ativa, id_disciplina_por_nome, remapear_coluna_id_disciplina

    df_disc = carregar_disciplinas()
    if df_disc is None or df_disc.empty:
        st.warning("Cadastre uma disciplina antes de anotar dailies.")
        return
    lista = df_disc["Nome_Disciplina"].astype(str).tolist()
    nome = st.selectbox(
        "Disciplina:",
        lista,
        index=indice_disciplina_ativa(df_disc, lista),
        key="daily_nota_disc",
    )
    id_disc = normalizar_id(id_disciplina_por_nome(df_disc, nome))
    df_entrancia = ler_aba("Entrancia_Turma")
    atuais = {
        normalizar_id(row["ID_Disciplina"]): str(row.get("Nome_Disciplina", "")).strip()
        for _, row in df_disc.iterrows()
        if normalizar_id(row.get("ID_Disciplina", ""))
    }
    if atuais:
        df_entrancia = remapear_coluna_id_disciplina(df_entrancia, atuais)
    alunos = df_entrancia[
        df_entrancia["ID_Disciplina"].map(normalizar_id) == id_disc
    ].copy()
    if alunos.empty:
        st.warning("Nenhum aluno nesta disciplina na Entrância.")
        return
    render(usuario, id_disc, alunos)


def render(usuario: dict, id_disciplina: str, alunos: pd.DataFrame):
    id_disc = normalizar_id(id_disciplina)
    datas = datas_dailies_disciplina(id_disc)
    padrao_data = data_daily_padrao(id_disc)
    if datas:
        idx_data = datas.index(padrao_data) if padrao_data in datas else len(datas) - 1
        dia = st.selectbox(
            "Data da daily:",
            datas,
            index=idx_data,
            format_func=lambda d: d.strftime("%d/%m/%Y"),
            key=f"daily_nota_data_{id_disc}",
        )
    else:
        dia = st.date_input(
            "Data da daily:",
            value=padrao_data,
            format="DD/MM/YYYY",
            key=f"daily_nota_data_livre_{id_disc}",
            help="Ainda não há dailies no calendário desta disciplina. Informe a data manualmente.",
        )

    salas = ordenar_grupos_lista(alunos["Sala"].dropna().astype(str).unique().tolist())
    sala_pref = sala_padrao_orientador(usuario, id_disc)
    chave_sala = f"daily_nota_sala_{id_disc}"
    if chave_sala not in st.session_state and sala_pref in salas:
        st.session_state[chave_sala] = sala_pref
    sala = selectbox_sala(
        "Sala:",
        salas,
        key=chave_sala,
        usuario=usuario,
        incluir_todas=False,
    )

    grupos = _grupos_da_sala(alunos, sala)
    if not grupos:
        st.warning("Nenhum grupo nesta sala.")
        return
    grupo = st.selectbox("Grupo:", grupos, key=f"daily_nota_grupo_{id_disc}_{sala}")

    id_ciclo, nome_ciclo = ciclo_na_data(id_disc, dia)
    if nome_ciclo:
        st.caption(f"Ciclo inferido: **{nome_ciclo}**.")
    else:
        st.caption(
            "Sem ciclo acadêmico para esta data. Preencha início do ciclo e apresentação "
            "no cadastro de ciclos para classificar a anotação."
        )

    ja = anotacoes_do_grupo(id_disc, sala, grupo)
    texto_atual = ""
    if not ja.empty:
        mesmo_dia = ja[ja["Data"] == dia.strftime("%d/%m/%Y")]
        if not mesmo_dia.empty:
            texto_atual = str(mesmo_dia.iloc[0]["Texto"])

    with st.form(f"daily_nota_form_{id_disc}_{sala}_{grupo}_{dia}", border=False):
        texto = st.text_area(
            "Anotação desta daily",
            value=texto_atual,
            height=140,
            placeholder="Avanço do grupo, lacunas, combinados para a próxima reunião…",
        )
        enviou = st.form_submit_button("Salvar anotação", type="primary")

    if enviou:
        erro = salvar_anotacao(
            dia=dia,
            id_disciplina=id_disc,
            sala=sala,
            grupo=grupo,
            texto=texto,
            usuario=usuario,
        )
        if erro:
            st.error(erro)
        else:
            registrar_log(
                usuario["email"],
                usuario["nome"],
                f"Anotação daily {id_disc} sala {sala} grupo {grupo} {dia.strftime('%d/%m/%Y')}",
            )
            st.success("Anotação salvada.")
            st.rerun()

    historico = anotacoes_do_grupo(id_disc, sala, grupo)
    if historico.empty:
        st.info("Ainda não há anotações deste grupo nesta sala.")
        return
    st.markdown("**Últimas deste grupo**")
    visao = historico[["Data", "Nome_Ciclo", "Texto"]].rename(
        columns={"Nome_Ciclo": "Ciclo", "Texto": "Anotação"}
    )
    st.dataframe(visao, width="stretch", hide_index=True)


def pode_anotar(usuario: dict) -> bool:
    if professor_e_orientador(usuario):
        return True
    from auth.supabase_auth import usuario_e_coordenador

    return bool(usuario_e_coordenador(usuario) and st.session_state.get("modo_coordenador"))
