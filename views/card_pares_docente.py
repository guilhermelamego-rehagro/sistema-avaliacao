"""Card da avaliação de pares no calendário docente: ciclo aberto, próximo e alertas de status."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from domain.ciclos import hoje_normalizado
from domain.painel_pares import (
    ABERTA,
    BLOQUEADA,
    ENCERRADA,
    FUTURA,
    FUTURA_BLOQUEADA,
    SEM_JANELA,
    situacao_pares_disciplina,
)

_ROTULO_SITUACAO = {
    ABERTA: "🟢 Aberta",
    BLOQUEADA: "🔴 Bloqueada (status inativo)",
    FUTURA: "🗓️ Agendada",
    FUTURA_BLOQUEADA: "⚠️ Agendada, mas não vai abrir (status inativo)",
    ENCERRADA: "Encerrada",
    SEM_JANELA: "Sem datas de pares",
}
_ONDE_AJUSTAR = "Coordenação → Cadastro de ciclos"


def _data_br(valor) -> str:
    return pd.Timestamp(valor).strftime("%d/%m") if pd.notna(valor) else "—"


def _quando(valor, hoje: pd.Timestamp) -> str:
    dias = (pd.Timestamp(valor).normalize() - hoje).days
    if dias == 0:
        return "hoje"
    if dias == 1:
        return "amanhã"
    return f"em {dias} dias"


def render(id_disc: str):
    try:
        sit = situacao_pares_disciplina(id_disc)
    except Exception as exc:
        st.caption(f"Não foi possível ler os ciclos para o card de pares: {exc}")
        return
    if sit.empty:
        return

    hoje = hoje_normalizado()
    with st.container(border=True):
        st.markdown("#### Avaliação de pares")

        abertas = sit[sit["Situacao"] == ABERTA]
        for _, c in abertas.iterrows():
            fim = c["Encerramento"]
            prazo = f" até **{_data_br(fim)}** (termina {_quando(fim, hoje)})" if pd.notna(fim) else ""
            st.success(f"**{c['Nome_Ciclo']}** aberta{prazo}. **{c['Enviaram']} de {c['Turma']}** alunos já enviaram.")
            if c["Turma"]:
                st.progress(min(c["Enviaram"] / c["Turma"], 1.0))

        bloqueadas = sit[sit["Situacao"] == BLOQUEADA]
        for _, c in bloqueadas.iterrows():
            st.error(
                f"**{c['Nome_Ciclo']}**: a janela de pares começou em {_data_br(c['Abertura'])}, "
                "mas o status está **inativo** e os alunos **não estão vendo** a avaliação. "
                f"Mude o status para **ativo** em {_ONDE_AJUSTAR}."
            )

        futuras = sit[sit["Situacao"].isin([FUTURA, FUTURA_BLOQUEADA])]
        if not futuras.empty:
            prox = futuras.iloc[0]
            texto = (
                f"Próxima: **{prox['Nome_Ciclo']}** abre em **{_data_br(prox['Abertura'])}** "
                f"({_quando(prox['Abertura'], hoje)}) e vai até {_data_br(prox['Encerramento'])}."
            )
            if abertas.empty and bloqueadas.empty:
                st.info(texto)
            else:
                st.caption(texto)
        elif abertas.empty and bloqueadas.empty:
            encerradas = sit[sit["Situacao"] == ENCERRADA]
            if not encerradas.empty:
                ult = encerradas.iloc[-1]
                st.info(f"Nenhuma avaliação aberta. **{ult['Nome_Ciclo']}** encerrou em {_data_br(ult['Encerramento'])}.")

        nao_abrirao = sit.loc[sit["Situacao"] == FUTURA_BLOQUEADA, "Nome_Ciclo"].tolist()
        if nao_abrirao:
            st.warning(
                f"**{', '.join(nao_abrirao)}** com status **inativo**: quando a data chegar, a avaliação "
                f"**não vai abrir**. Para abrir pelas datas, deixe o status **ativo** em {_ONDE_AJUSTAR}."
            )
        sem_janela = sit.loc[sit["Situacao"] == SEM_JANELA, "Nome_Ciclo"].tolist()
        if sem_janela:
            st.caption(f"Sem datas de pares cadastradas: {', '.join(sem_janela)}.")

        with st.expander("Todos os ciclos da disciplina"):
            st.dataframe(
                pd.DataFrame(
                    {
                        "Ciclo": sit["Nome_Ciclo"],
                        "Abertura": sit["Abertura"].map(_data_br),
                        "Encerramento": sit["Encerramento"].map(_data_br),
                        "Status": sit["Status"],
                        "Situação": sit["Situacao"].map(_ROTULO_SITUACAO),
                        "Enviaram": [
                            f"{e}/{t}" if s in (ABERTA, ENCERRADA) else "—"
                            for e, t, s in zip(sit["Enviaram"], sit["Turma"], sit["Situacao"])
                        ],
                    }
                ),
                hide_index=True,
                width="stretch",
            )
