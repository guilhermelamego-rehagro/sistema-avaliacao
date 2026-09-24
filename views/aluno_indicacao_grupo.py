"""Aluno vencedor: escolher colega para o próximo grupo."""

from __future__ import annotations

import streamlit as st

from domain.indicacao_grupo import (
    confirmar_indicacao,
    indicacao_do_vencedor,
    janelas_abertas_para_vencedor,
    pool_escolha,
)
from utils.logs import registrar_log_acesso


def render(usuario: dict):
    st.header("Indicar colega para o grupo")
    registrar_log_acesso(usuario["email"], usuario["nome"], "Abriu indicação de grupo")

    email = str(usuario.get("email", "")).strip().lower()
    nome = str(usuario.get("nome", "")).strip()

    janelas = janelas_abertas_para_vencedor(email)
    if janelas.empty:
        st.info(
            "Não há janela aberta em que você precise indicar um colega agora. "
            "Quando for o caso, o convite aparece aqui."
        )
        return

    for _, j in janelas.iterrows():
        id_j = str(j.get("ID_Janela", "")).strip()
        nome_ciclo = str(j.get("Nome_Ciclo", "")).strip() or str(j.get("ID_Ciclo", "")).strip()
        di = str(j.get("Data_Inicio", "")).strip()
        dfim = str(j.get("Data_Fim", "")).strip()

        ja = indicacao_do_vencedor(id_j, email)
        with st.container(border=True):
            st.markdown(f"**{nome_ciclo}**")
            st.caption(f"Janela: {di} a {dfim}")

            if ja:
                st.success(
                    f"Indicação confirmada: **{ja['nome_escolhido']}**. "
                    f"Registrado em {ja['confirmado_em']}."
                )
                st.caption("O colega indicado não recebe aviso de quem o escolheu.")
                continue

            pool = pool_escolha(id_j, email)
            if pool.empty:
                st.warning("Não há colegas disponíveis para indicação nesta oferta.")
                continue

            opcoes = {
                f"{str(r.get('Nome_Completo', '')).strip()} · "
                f"Sala {str(r.get('Sala', '')).strip()} · "
                f"Grupo {str(r.get('Grupo', '')).strip()}": (
                    str(r.get("Email_Pessoal", "")).strip().lower(),
                    str(r.get("Nome_Completo", "")).strip(),
                )
                for _, r in pool.iterrows()
            }
            escolha_lab = st.selectbox(
                "Escolha um colega da oferta:",
                list(opcoes.keys()),
                key=f"aluno_ind_sel_{id_j}",
            )
            st.caption(
                "Ao confirmar, sua escolha fica registrada. "
                "O colega indicado não vê quem o escolheu."
            )
            if st.button("Confirmar indicação", type="primary", key=f"aluno_ind_ok_{id_j}"):
                email_e, nome_e = opcoes[escolha_lab]
                erro = confirmar_indicacao(id_j, email, nome, email_e, nome_e)
                if erro:
                    st.error(erro)
                else:
                    registrar_log_acesso(
                        email,
                        nome,
                        f"Confirmou indicação grupo janela={id_j} escolhido={email_e}",
                    )
                    st.success(f"Indicação confirmada: **{nome_e}**.")
                    st.rerun()
