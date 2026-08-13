"""Configurações exclusivas do coordenador."""

import pandas as pd
import streamlit as st

from data.sheets import ler_aba, ler_aba_frequencia
from domain.ciclos import indice_ciclo_padrao, ordenar_ciclos
from domain.entregas import (
    avaliacao_entregas_aberta,
    carregar_ordem_apresentacao,
    grupos_da_sala,
    lista_ordenada_grupos,
    obter_config_entregas,
    salvar_config_entregas,
    salvar_ordem_apresentacao,
)
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.logs import registrar_log
from utils.preferencias_sala import selectbox_sala


def _chave_lista_ordem(id_disc: str, id_ciclo: str, sala: str) -> str:
    return f"coord_ordem_{id_disc}_{id_ciclo}_{sala}"


def _render_ordem_sala(id_disc: str, id_ciclo: str, ciclo_sel: str, entrancia: pd.DataFrame, usuario: dict):
    salas = sorted(entrancia["Sala"].dropna().astype(str).unique().tolist())
    if not salas:
        st.warning("Nenhuma sala cadastrada na entrância.")
        return

    sala_sel = selectbox_sala(
        "Sala:",
        salas,
        key=f"coord_sala_{id_disc}_{id_ciclo}",
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
    for g in grupos_base:
        if g not in lista:
            lista.append(g)
    st.session_state[chave] = lista

    st.caption("Use os botões para reorganizar a ordem de apresentação desta sala.")
    for i, grupo in enumerate(st.session_state[chave]):
        c1, c2, c3 = st.columns([5, 1, 1])
        c1.markdown(f"**{i + 1}.** Grupo **{grupo}**")
        if c2.button("⬆", key=f"coord_up_{id_disc}_{id_ciclo}_{sala_sel}_{i}", disabled=i == 0):
            lst = st.session_state[chave]
            lst[i - 1], lst[i] = lst[i], lst[i - 1]
            st.session_state[chave] = lst
            st.rerun()
        if c3.button("⬇", key=f"coord_down_{id_disc}_{id_ciclo}_{sala_sel}_{i}", disabled=i == len(st.session_state[chave]) - 1):
            lst = st.session_state[chave]
            lst[i + 1], lst[i] = lst[i], lst[i + 1]
            st.session_state[chave] = lst
            st.rerun()

    if st.button("💾 Salvar ordem desta sala", key=f"coord_salvar_ordem_{id_disc}_{id_ciclo}_{sala_sel}"):
        mapa = {g: i + 1 for i, g in enumerate(st.session_state[chave])}
        salvar_ordem_apresentacao(id_disc, id_ciclo, sala_sel, mapa)
        registrar_log(usuario["email"], usuario["nome"], f"Ordem apresentação {ciclo_sel} sala {sala_sel}")
        st.success(f"Ordem salva para a sala **{sala_sel}**!")
        st.rerun()


def render(usuario: dict):
    st.header("Configurações do coordenador")
    st.caption("Janela de entregas, ordem de apresentação por sala e calendário acadêmico.")

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox(
        "Disciplina:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
        key="coord_disc",
    )
    id_disc = id_disciplina_por_nome(df_disc, disc_sel)

    df_ciclos = ler_aba("Ciclos")
    ciclos = df_ciclos[df_ciclos["ID_Disciplina"].astype(str).str.strip() == id_disc]
    ciclos = ordenar_ciclos(ciclos)
    if ciclos.empty:
        st.warning("Nenhum ciclo cadastrado.")
        return

    nomes_ciclos = ciclos["Nome_Ciclo"].astype(str).tolist()
    ciclo_sel = st.selectbox(
        "Ciclo:",
        nomes_ciclos,
        index=indice_ciclo_padrao(ciclos, nomes_ciclos),
        key="coord_ciclo",
    )
    id_ciclo = str(ciclos[ciclos["Nome_Ciclo"].astype(str) == ciclo_sel].iloc[0]["ID_Ciclo"]).strip()

    df_entrancia = ler_aba("Entrancia_Turma")
    entrancia = df_entrancia[df_entrancia["ID_Disciplina"].astype(str).str.strip() == id_disc]

    aba_janela, aba_ordem, aba_cal = st.tabs(
        ["📅 Janela de entregas", "🔢 Ordem de apresentação", "📆 Calendário"]
    )

    with aba_janela:
        st.subheader("Período permitido para avaliação de entregas")
        config = obter_config_entregas(id_disc, id_ciclo)
        aberta, msg = avaliacao_entregas_aberta(id_disc, id_ciclo)
        if msg:
            st.info(msg.replace("**", ""))
        elif aberta:
            st.success("Janela aberta (ou sem restrição de datas).")

        c_ini, c_fim = st.columns(2)
        val_ini = c_ini.text_input(
            "Data inicial (dd/mm/aaaa):",
            value=config["data_inicio"] if config else "",
            placeholder="Ex.: 14/07/2026",
        )
        val_fim = c_fim.text_input(
            "Data final (dd/mm/aaaa):",
            value=config["data_fim"] if config else "",
            placeholder="Ex.: 18/07/2026",
        )
        st.caption("Deixe em branco para liberar o lançamento a qualquer momento.")
        if st.button("Salvar janela de avaliação", type="primary"):
            salvar_config_entregas(id_disc, id_ciclo, val_ini, val_fim, usuario["email"])
            registrar_log(usuario["email"], usuario["nome"], f"Janela entregas {ciclo_sel}")
            st.success("Janela salva!")
            st.rerun()

    with aba_ordem:
        st.subheader("Ordem de apresentação por sala")
        _render_ordem_sala(id_disc, id_ciclo, ciclo_sel, entrancia, usuario)

    with aba_cal:
        st.subheader("Datas de aulas e reuniões diárias")
        st.caption(
            "Edite quais datas contam para frequência (Calendario_Aulas) "
            "e para nota de dailies (Calendario_Dailies)."
        )
        try:
            df_aulas = ler_aba_frequencia("Calendario_Aulas")
            st.markdown("**Calendário de Aulas**")
            st.data_editor(df_aulas, width="stretch", num_rows="dynamic", key="coord_cal_aulas")
        except Exception as e:
            st.warning(f"Não foi possível carregar Calendario_Aulas: {e}")

        try:
            df_dailies = ler_aba_frequencia("Calendario_Dailies")
            st.markdown("**Calendário de Dailies**")
            st.data_editor(df_dailies, width="stretch", num_rows="dynamic", key="coord_cal_dailies")
        except Exception as e:
            st.warning(f"Não foi possível carregar Calendario_Dailies: {e}")

        st.info(
            "A persistência automática do calendário será habilitada na próxima etapa. "
            "Por ora, use a planilha de frequência diretamente se precisar alterar com urgência."
        )
