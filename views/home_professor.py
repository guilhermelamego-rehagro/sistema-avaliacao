"""Tela inicial do professor / secretaria."""

import streamlit as st

from auth.supabase_auth import professor_e_orientador, usuario_e_coordenador
from domain.ciclos import obter_disciplina_ativa
from navigation import (
    ROTA_COORD_CONFERIR,
    ROTA_IMPORT_CANVAS,
    ROTA_LANCAR_BANCA,
    ROTA_MODERACAO,
    ROTA_ORIENTADOR,
    ROTA_PARES_ACOMP,
    ROTA_FREQ_CONTROLE,
    ir_para,
)


def _atalho(rotulo: str, descricao: str, rota: str, key: str):
    st.markdown(f"**{rotulo}**")
    st.caption(descricao)
    if st.button(f"Abrir: {rotulo}", key=key, width="stretch"):
        ir_para(rota)


def render(usuario: dict):
    perfil = usuario.get("perfil", "Professor")
    st.header("Início")
    st.caption(f"Olá, **{usuario['nome']}**.")

    _, nome_disc = obter_disciplina_ativa()
    if nome_disc:
        st.info(f"Disciplina ativa: **{nome_disc}**")

    if perfil == "Secretaria":
        _atalho(
            "Controle de frequência",
            "Visão geral de presença por turma.",
            ROTA_FREQ_CONTROLE,
            "home_sec_freq",
        )
        return

    tipo = usuario.get("tipo_professor") or "Orientador"
    if tipo == "Especialista":
        _atalho(
            "Lançar notas da banca",
            "Registre apresentação e conteúdo técnico por grupo.",
            ROTA_LANCAR_BANCA,
            "home_esp_banca",
        )
        return

    if professor_e_orientador(usuario):
        st.subheader("Atalhos")
        _atalho(
            "Pares — acompanhamento",
            "Veja alunos pendentes e médias parciais.",
            ROTA_PARES_ACOMP,
            "home_prof_pares",
        )
        _atalho(
            "Lançar notas da banca",
            "Avaliação de entregas por sala e ciclo.",
            ROTA_LANCAR_BANCA,
            "home_prof_banca",
        )
        _atalho(
            "Avaliação do orientador",
            "Grid de notas por aluno e ciclo.",
            ROTA_ORIENTADOR,
            "home_prof_orient",
        )
        _atalho(
            "Moderação de comentários",
            "Revise feedbacks de pares.",
            ROTA_MODERACAO,
            "home_prof_mod",
        )

    if usuario_e_coordenador(usuario) and st.session_state.get("modo_coordenador"):
        st.subheader("Coordenação")
        st.caption("Modo coordenador ativo.")
        _atalho(
            "Conferir entregas",
            "Matriz grupos × ciclos para lançamentos em lote.",
            ROTA_COORD_CONFERIR,
            "home_coord_conf",
        )
    elif usuario_e_coordenador(usuario):
        st.caption("Ative **Modo coordenador** na barra lateral para configurações e conferência de entregas.")

    if professor_e_orientador(usuario):
        st.markdown("---")
        _atalho(
            "Importar Canvas",
            "Importação de atividades individuais.",
            ROTA_IMPORT_CANVAS,
            "home_prof_canvas",
        )
