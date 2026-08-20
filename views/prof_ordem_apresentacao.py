"""Ordem de apresentação por sala — lançada pelas professoras orientadoras."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.ciclos import ciclos_da_disciplina, indice_ciclo_academico_padrao, ordenar_ciclos
from domain.encontro_presencial import ciclos_visiveis_avaliacao
from domain.entregas import (
    carregar_ordem_apresentacao,
    grupos_da_sala,
    lista_ordenada_grupos,
    salvar_ordem_apresentacao,
)
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.logs import registrar_log
from utils.preferencias_sala import selectbox_sala


def _chave_lista_ordem(id_disc: str, id_ciclo: str, sala: str) -> str:
    return f"ordem_apres_{id_disc}_{id_ciclo}_{sala}"


def _render_ordem_sala(
    id_disc: str,
    id_ciclo: str,
    ciclo_sel: str,
    entrancia: pd.DataFrame,
    usuario: dict,
):
    salas = sorted(entrancia["Sala"].dropna().astype(str).unique().tolist())
    if not salas:
        st.warning("Nenhuma sala cadastrada na entrância.")
        return

    sala_sel = selectbox_sala(
        "Sala:",
        salas,
        key=f"ordem_sala_{id_disc}_{id_ciclo}",
        usuario=usuario,
        incluir_todas=False,
    )
    grupos_base = grupos_da_sala(entrancia, sala_sel)
    if not grupos_base:
        st.info("Nenhum grupo nesta sala.")
        return

    ordem_map = carregar_ordem_apresentacao(id_disc, id_ciclo, sala_sel)
    chave = _chave_lista_ordem(id_disc, id_ciclo, sala_sel)
    if chave not in st.session_state:
        st.session_state[chave] = lista_ordenada_grupos(grupos_base, ordem_map)

    lista = st.session_state[chave]
    for g in grupos_base:
        if g not in lista:
            lista.append(g)
    lista = [g for g in lista if g in grupos_base]
    st.session_state[chave] = lista

    st.caption("Use os botões para reorganizar a ordem de apresentação desta sala.")
    for i, grupo in enumerate(st.session_state[chave]):
        c1, c2, c3 = st.columns([5, 1, 1])
        c1.markdown(f"**{i + 1}.** Grupo **{grupo}**")
        if c2.button("⬆", key=f"ordem_up_{id_disc}_{id_ciclo}_{sala_sel}_{i}", disabled=i == 0):
            lst = st.session_state[chave]
            lst[i - 1], lst[i] = lst[i], lst[i - 1]
            st.session_state[chave] = lst
            st.rerun()
        if c3.button(
            "⬇",
            key=f"ordem_down_{id_disc}_{id_ciclo}_{sala_sel}_{i}",
            disabled=i == len(st.session_state[chave]) - 1,
        ):
            lst = st.session_state[chave]
            lst[i + 1], lst[i] = lst[i], lst[i + 1]
            st.session_state[chave] = lst
            st.rerun()

    if st.button("💾 Salvar ordem desta sala", key=f"ordem_salvar_{id_disc}_{id_ciclo}_{sala_sel}"):
        mapa = {g: i + 1 for i, g in enumerate(st.session_state[chave])}
        salvar_ordem_apresentacao(id_disc, id_ciclo, sala_sel, mapa)
        registrar_log(
            usuario["email"],
            usuario["nome"],
            f"Ordem apresentação {ciclo_sel} sala {sala_sel}",
        )
        st.success(f"Ordem salva para a sala **{sala_sel}**!")
        st.rerun()


def render(usuario: dict):
    st.header("Ordem de apresentação")
    st.caption(
        "Defina a sequência em que os grupos se apresentam em cada sala. "
        "Essa ordem aparece em **Lançar notas da banca**."
    )

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox(
        "Disciplina:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
        key="ordem_disc",
    )
    id_disc = id_disciplina_por_nome(df_disc, disc_sel)

    df_ciclos = ler_aba("Ciclos")
    ciclos = ciclos_da_disciplina(df_ciclos, id_disc)
    ciclos = ordenar_ciclos(ciclos_visiveis_avaliacao(ciclos, id_disc))
    if ciclos.empty:
        st.warning("Nenhum ciclo cadastrado.")
        return

    nomes_ciclos = ciclos["Nome_Ciclo"].astype(str).tolist()
    ciclo_sel = st.selectbox(
        "Ciclo:",
        nomes_ciclos,
        index=indice_ciclo_academico_padrao(ciclos, nomes_ciclos),
        key="ordem_ciclo",
    )
    id_ciclo = str(ciclos[ciclos["Nome_Ciclo"].astype(str) == ciclo_sel].iloc[0]["ID_Ciclo"]).strip()

    df_entrancia = ler_aba("Entrancia_Turma")
    entrancia = df_entrancia[df_entrancia["ID_Disciplina"].astype(str).str.strip() == id_disc]
    _render_ordem_sala(id_disc, id_ciclo, ciclo_sel, entrancia, usuario)
