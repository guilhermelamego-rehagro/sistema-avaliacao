"""Formação de grupos por oferta — salas/grupos pré-carregados (ambiente teste)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data.supabase_academico import AmbienteProducaoError, academico_habilitado
from domain.formacao_grupos import (
    atribuir_grupo,
    contagens_grupos,
    criar_grupo,
    criar_sala,
    grupos_da_oferta,
    listar_ofertas,
    mapa_nomes_disciplinas,
    oferta_padrao_id,
    roster_oferta,
    salas_da_oferta,
    atualizar_grupo,
    rotulo_oferta,
)
from utils.logs import registrar_log
from utils.ordenacao import ordenar_grupos_lista


def render(usuario: dict):
    st.header("Formação de grupos")
    st.caption(
        "Por oferta: salas e grupos já importados aparecem preenchidos. "
        "Aluno herda a sala do grupo."
    )

    if not academico_habilitado():
        st.warning("Disponível apenas com ambiente=teste.")
        return

    try:
        ofertas = listar_ofertas()
        nomes_disc = mapa_nomes_disciplinas()
    except AmbienteProducaoError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"Erro ao carregar ofertas: {exc}")
        return

    if not ofertas:
        st.info("Nenhuma oferta cadastrada.")
        return

    mapa = {rotulo_oferta(o, nomes_disc): o for o in ofertas}
    padrao = oferta_padrao_id(ofertas)
    rotulos = list(mapa.keys())
    idx = 0
    if padrao:
        for i, o in enumerate(ofertas):
            if o["id_oferta"] == padrao:
                idx = i
                break

    escolha = st.selectbox("Oferta", options=rotulos, index=idx, key="fg_oferta")
    oferta = mapa[escolha]
    id_oferta = oferta["id_oferta"]

    try:
        salas = salas_da_oferta(id_oferta)
        grupos = grupos_da_oferta(id_oferta)
        roster = roster_oferta(id_oferta)
    except Exception as exc:
        st.error(f"Erro ao carregar formação: {exc}")
        return

    cont = contagens_grupos(roster, grupos)
    n_sem = cont.get("__sem__", 0)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Matrículas", len(roster))
    m2.metric("Sem grupo", n_sem)
    m3.metric("Grupos", len(grupos))
    m4.metric("Salas", len(salas))

    col_esq, col_dir = st.columns([1.1, 1.9])

    with col_esq:
        st.subheader("Salas e grupos")
        sala_por_id = {s["id"]: s for s in salas}
        if not grupos and not salas:
            st.info("Nenhuma sala/grupo nesta oferta. Crie abaixo.")
        else:
            linhas = []
            for g in grupos:
                sala = sala_por_id.get(g.get("sala_id") or "")
                linhas.append(
                    {
                        "Grupo": g.get("nome") or "",
                        "Sala": (sala or {}).get("nome") or "—",
                        "Alunos": cont.get(g["id"], 0),
                    }
                )
            st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")

        with st.expander("Criar sala"):
            with st.form("fg_nova_sala"):
                nome_sala = st.text_input("Nome da sala", placeholder="Ex.: Grupos 1 a 6")
                if st.form_submit_button("Criar sala"):
                    _, erro = criar_sala(id_oferta, nome_sala)
                    if erro:
                        st.error(erro)
                    else:
                        registrar_log(
                            usuario.get("email"),
                            usuario.get("nome"),
                            f"Criou sala {id_oferta}/{nome_sala}",
                        )
                        st.success("Sala criada.")
                        st.rerun()

        with st.expander("Criar grupo"):
            opts_sala = {"(sem sala)": None}
            opts_sala.update({s["nome"]: s["id"] for s in salas})
            with st.form("fg_novo_grupo"):
                nome_g = st.text_input("Nome do grupo", placeholder="Ex.: 7")
                sala_rot = st.selectbox("Sala", options=list(opts_sala.keys()))
                if st.form_submit_button("Criar grupo"):
                    _, erro = criar_grupo(id_oferta, nome_g, opts_sala[sala_rot])
                    if erro:
                        st.error(erro)
                    else:
                        registrar_log(
                            usuario.get("email"),
                            usuario.get("nome"),
                            f"Criou grupo {id_oferta}/{nome_g}",
                        )
                        st.success("Grupo criado.")
                        st.rerun()

        if grupos:
            with st.expander("Vincular grupo a sala"):
                g_map = {f"{g.get('nome')}": g for g in grupos}
                with st.form("fg_vincular"):
                    g_rot = st.selectbox("Grupo", options=list(g_map.keys()))
                    opts = {"(sem sala)": None}
                    opts.update({s["nome"]: s["id"] for s in salas})
                    s_rot = st.selectbox("Nova sala", options=list(opts.keys()))
                    if st.form_submit_button("Atualizar vínculo"):
                        g = g_map[g_rot]
                        _, erro = atualizar_grupo(g["id"], sala_id=opts[s_rot])
                        if erro:
                            st.error(erro)
                        else:
                            st.success("Grupo atualizado.")
                            st.rerun()

    with col_dir:
        st.subheader("Alunos da oferta")
        so_sem = st.checkbox("Somente sem grupo", value=False, key="fg_so_sem")
        visivel = [r for r in roster if (not so_sem or r["sem_grupo"])]

        if not visivel:
            st.info("Nenhuma matrícula para exibir.")
        else:
            nomes_grupos = ordenar_grupos_lista([str(g.get("nome") or "") for g in grupos])
            grupo_nomes = ["(sem grupo)"] + nomes_grupos
            id_por_nome = {"(sem grupo)": None}
            id_por_nome.update({str(g.get("nome") or ""): g["id"] for g in grupos})
            nome_por_id = {g["id"]: str(g.get("nome") or "") for g in grupos}

            df = pd.DataFrame(
                [
                    {
                        "matricula_id": r["matricula_id"],
                        "Nome": r["nome"],
                        "E-mail": r["email"],
                        "Turma": r["turma"] or "",
                        "Sala": r["sala_nome"] or "",
                        "Grupo": nome_por_id.get(r["grupo_id"], "(sem grupo)")
                        if r.get("grupo_id")
                        else "(sem grupo)",
                    }
                    for r in visivel
                ]
            )
            editado = st.data_editor(
                df,
                hide_index=True,
                width="stretch",
                disabled=["matricula_id", "Nome", "E-mail", "Turma", "Sala"],
                column_config={
                    "matricula_id": None,
                    "Grupo": st.column_config.SelectboxColumn(
                        "Grupo",
                        options=grupo_nomes,
                        required=True,
                    ),
                },
                key=f"fg_editor_{id_oferta}",
            )
            if st.button("Salvar atribuições", type="primary", key="fg_salvar"):
                n = 0
                origem = {r["matricula_id"]: r["grupo_id"] for r in visivel}
                for _, row in editado.iterrows():
                    mid = row["matricula_id"]
                    novo_id = id_por_nome.get(str(row["Grupo"]))
                    if novo_id != origem.get(mid):
                        atribuir_grupo(mid, novo_id)
                        n += 1
                if n:
                    registrar_log(
                        usuario.get("email"),
                        usuario.get("nome"),
                        f"Atribuiu grupos {id_oferta}: {n} matrícula(s)",
                    )
                    st.success(f"{n} atribuição(ões) salva(s).")
                    st.rerun()
                else:
                    st.info("Nenhuma alteração.")
