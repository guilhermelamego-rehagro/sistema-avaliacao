"""Janela de avaliação da banca — configuração do coordenador."""

import streamlit as st

from data.sheets import ler_aba
from domain.ciclos import ciclos_da_disciplina, indice_ciclo_academico_padrao, ordenar_ciclos
from domain.encontro_presencial import ciclos_visiveis_avaliacao
from domain.entregas import avaliacao_entregas_aberta, obter_config_entregas, salvar_config_entregas
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.logs import registrar_log


def render(usuario: dict):
    st.header("Janela de avaliação da banca")
    st.caption(
        "Defina o período em que professores podem lançar as notas da banca para cada ciclo."
    )

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox(
        "Disciplina:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
        key="coord_janela_disc",
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
        key="coord_janela_ciclo",
    )
    id_ciclo = str(ciclos[ciclos["Nome_Ciclo"].astype(str) == ciclo_sel].iloc[0]["ID_Ciclo"]).strip()

    st.subheader("Período permitido")
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
        registrar_log(usuario["email"], usuario["nome"], f"Janela banca {ciclo_sel}")
        st.success("Janela salva!")
        st.rerun()
