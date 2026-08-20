"""Tela inicial do professor / secretaria."""

import streamlit as st

from auth.supabase_auth import professor_e_orientador, usuario_e_coordenador
from domain.anotacoes_daily import datas_dailies_disciplina
from domain.ciclos import hoje_normalizado, obter_disciplina_ativa
from navigation import (
    ROTA_COORD_CONFERIR,
    ROTA_FREQ_PROGRAMACAO,
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
            "Programação de aulas e dailies",
            "Agenda de aulas e reuniões que entram na frequência.",
            ROTA_FREQ_PROGRAMACAO,
            "home_sec_prog",
        )
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
            "Programação de aulas e dailies",
            "Veja (e, no modo coordenador, lance) as datas que entram na frequência.",
            ROTA_FREQ_PROGRAMACAO,
            "home_prof_prog",
        )
        _atalho(
            "Avaliação de pares",
            "Alunos pendentes e prévia de resultados.",
            ROTA_PARES_ACOMP,
            "home_prof_pares",
        )
        _atalho(
            "Lançar notas da banca",
            "Avaliação de entregas por sala e ciclo.",
            ROTA_LANCAR_BANCA,
            "home_prof_banca",
        )
        id_ativa, _ = obter_disciplina_ativa()
        from views.prof_anotacoes_daily import pode_anotar
        from navigation import ROTA_ANOTACOES_DAILY

        if (
            pode_anotar(usuario)
            and id_ativa
            and hoje_normalizado().date() in datas_dailies_disciplina(id_ativa)
        ):
            _atalho(
                "Anotações da daily",
                "Hoje tem daily. Registre o texto de orientação por grupo.",
                ROTA_ANOTACOES_DAILY,
                "home_prof_daily",
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
            "Conferir notas grupos",
            "Matriz grupos × ciclos para lançamentos em lote.",
            ROTA_COORD_CONFERIR,
            "home_coord_conf",
        )
    elif usuario_e_coordenador(usuario):
        st.caption("Ative **Modo coordenador** na barra lateral para configurações e conferência de notas.")

    if professor_e_orientador(usuario):
        st.markdown("---")
        _atalho(
            "Importar Canvas",
            "Importação de atividades individuais.",
            ROTA_IMPORT_CANVAS,
            "home_prof_canvas",
        )
