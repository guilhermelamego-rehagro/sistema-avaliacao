"""Faixa com a hora do último cálculo dos boletins e o andamento do recálculo em segundo plano."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from domain import boletim_calculado as boletim

_TZ = ZoneInfo("America/Sao_Paulo")


def _texto_concluido(concluido: datetime | None) -> str:
    if concluido is None:
        return "Ainda não há cálculo completo da turma."
    return f"Notas do cálculo de {concluido.astimezone(_TZ):%d/%m às %H:%M}."


def render_status(id_disc: str, usuario: dict, concluido: datetime | None, *, chave: str) -> None:
    """Enquanto houver cálculo em curso, a faixa se atualiza sozinha a cada poucos segundos."""
    versao_vista = boletim.versao(id_disc)
    rodando = boletim.andamento(id_disc) is not None or bool(boletim.em_atualizacao(id_disc))

    @st.fragment(run_every=5 if rodando else None)
    def _faixa():
        andamento = boletim.andamento(id_disc)
        parciais = boletim.em_atualizacao(id_disc)
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        if andamento is not None:
            progresso = f" ({andamento.feito} de {andamento.total} alunos)" if andamento.total else ""
            c1.info(
                f"⏳ Recalculando as notas da turma em segundo plano{progresso}. Pode usar outras telas; "
                f"enquanto isso valem as notas do último cálculo. {_texto_concluido(concluido)}"
            )
            return
        if parciais:
            c1.info(f"⏳ Atualizando a nota até agora de {len(parciais)} aluno(s)…")
            return
        if boletim.versao(id_disc) != versao_vista:
            c1.success("Há notas recalculadas.")
            if c2.button("Mostrar notas novas", key=f"{chave}_mostrar", width="stretch", type="primary"):
                st.rerun()
            return
        c1.caption(
            f"{_texto_concluido(concluido)} O cálculo é refeito no primeiro acesso do dia da equipe e ao salvar "
            "notas do orientador por aqui; para incluir outros lançamentos de agora, recalcule (leva alguns minutos)."
        )
        if c2.button("Recalcular notas", key=f"{chave}_recalcular", width="stretch"):
            boletim.recalcular(id_disc, autor=str(usuario.get("email", "")).lower())
            st.rerun()

    _faixa()
