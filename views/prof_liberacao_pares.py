"""UI de liberação excepcional de pares (coordenação)."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.ciclos import ordenar_ciclos
from domain.encontro_presencial import ciclos_visiveis_avaliacao
from domain.liberacoes_pares import (
    MODOS,
    criar_liberacao,
    fim_do_dia,
    listar_liberacoes_ativas,
    revogar_liberacao,
    validade_padrao_48h,
)
from domain.pares import aluno_ja_enviou_pares
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa, normalizar_id
from utils.logs import registrar_log


def render_painel(usuario: dict):
    st.markdown("---")
    st.subheader("Liberação excepcional de pares")
    st.caption(
        "Libera um ciclo específico para **um aluno**, sem reabrir a janela da turma. "
        "Útil para correção de envio (ex.: corrida no append). "
        "No máx. uma liberação vigente por aluno/disciplina."
    )

    df_disc = ler_aba("Disciplinas")
    df_ciclos = ler_aba("Ciclos")
    df_entrancia = ler_aba("Entrancia_Turma")

    lista_disc = df_disc["Nome_Disciplina"].astype(str).tolist()
    if not lista_disc:
        st.warning("Cadastre uma disciplina.")
        return

    disc_sel = st.selectbox(
        "Disciplina:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
        key="lib_pares_disc",
    )
    id_disc = normalizar_id(id_disciplina_por_nome(df_disc, disc_sel))
    ciclos = ordenar_ciclos(
        ciclos_visiveis_avaliacao(
            df_ciclos[df_ciclos["ID_Disciplina"].map(normalizar_id) == id_disc],
            id_disc,
        )
    )
    if ciclos.empty:
        st.warning("Nenhum ciclo nesta disciplina.")
        return

    nomes_ciclo = ciclos["Nome_Ciclo"].astype(str).tolist()
    ciclo_nome = st.selectbox("Ciclo a liberar:", nomes_ciclo, key="lib_pares_ciclo")
    row_ciclo = ciclos[ciclos["Nome_Ciclo"].astype(str) == ciclo_nome].iloc[0]
    id_ciclo = normalizar_id(row_ciclo["ID_Ciclo"])

    alunos = df_entrancia[df_entrancia["ID_Disciplina"].map(normalizar_id) == id_disc].copy()
    if alunos.empty:
        st.warning("Nenhum aluno na Entrância desta disciplina.")
        return
    alunos["Email_Pessoal"] = alunos["Email_Pessoal"].astype(str).str.strip().str.lower()
    alunos = alunos.drop_duplicates(subset=["Email_Pessoal"]).sort_values("Nome_Completo")
    opcoes = [
        f"{r['Nome_Completo']} <{r['Email_Pessoal']}>"
        for _, r in alunos.iterrows()
    ]
    aluno_op = st.selectbox("Aluno:", opcoes, key="lib_pares_aluno")
    idx = opcoes.index(aluno_op)
    email_aluno = str(alunos.iloc[idx]["Email_Pessoal"]).strip().lower()
    nome_aluno = str(alunos.iloc[idx]["Nome_Completo"]).strip()

    ja = aluno_ja_enviou_pares(id_ciclo, email_aluno)
    if ja:
        st.info("Este aluno **já possui** envio de pares neste ciclo. Use modo **Reenvio** para corrigir.")
        modo_default = "reenvio"
    else:
        st.caption("Aluno ainda **não enviou** pares neste ciclo.")
        modo_default = "primeiro_envio"

    modo = st.radio(
        "Modo:",
        list(MODOS),
        index=list(MODOS).index(modo_default),
        format_func=lambda m: "Primeiro envio" if m == "primeiro_envio" else "Reenvio",
        horizontal=True,
        key="lib_pares_modo",
    )
    validade = st.date_input(
        "Válido até (inclui o dia inteiro):",
        value=(validade_padrao_48h() + timedelta(hours=0)).date(),
        key="lib_pares_validade",
    )
    motivo = st.text_input(
        "Motivo:",
        placeholder="Ex.: reenvio após perda por corrida no Ciclo 1",
        key="lib_pares_motivo",
    )

    if st.button("Conceder liberação", type="primary", key="lib_pares_conceder"):
        erro = criar_liberacao(
            email_aluno=email_aluno,
            nome_aluno=nome_aluno,
            id_disciplina=id_disc,
            id_ciclo=id_ciclo,
            nome_ciclo=ciclo_nome,
            modo=modo,
            valido_ate=fim_do_dia(validade),
            motivo=motivo,
            liberador=usuario,
        )
        if erro:
            st.error(erro)
        else:
            registrar_log(
                usuario["email"],
                usuario["nome"],
                f"Liberação excepcional pares {ciclo_nome} → {email_aluno} ({modo})",
            )
            st.success(f"Liberação concedida para {nome_aluno} até {validade.strftime('%d/%m/%Y')}.")
            st.rerun()

    ativas = listar_liberacoes_ativas(id_disc)
    st.markdown("#### Liberações vigentes nesta disciplina")
    if ativas.empty:
        st.caption("Nenhuma liberação ativa.")
        return

    for _, row in ativas.iterrows():
        c1, c2 = st.columns([4, 1])
        with c1:
            st.markdown(
                f"**{row['Nome_Aluno']}** · {row['Nome_Ciclo']} · "
                f"`{row['Modo']}` · até `{row['Valido_Ate']}`  \n"
                f"Motivo: _{row['Motivo']}_ · por {row['Nome_Liberador'] or row['Email_Liberador']}"
            )
        with c2:
            if st.button("Revogar", key=f"lib_pares_rev_{row['ID']}", width="stretch"):
                erro = revogar_liberacao(str(row["ID"]), ator=usuario)
                if erro:
                    st.error(erro)
                else:
                    registrar_log(
                        usuario["email"],
                        usuario["nome"],
                        f"Revogou liberação pares {row['ID']}",
                    )
                    st.rerun()
