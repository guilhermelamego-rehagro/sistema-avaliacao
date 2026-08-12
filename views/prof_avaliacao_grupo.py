"""Tela de lançamento da avaliação de entregas (grupo) por ciclo e sala."""

import streamlit as st

from data.sheets import ler_aba
from domain.avaliacoes import formatar_nota_entrega, obter_avaliacao_grupo, parse_nota_entrega, salvar_avaliacao_grupo
from domain.ciclos import indice_ciclo_padrao, ordenar_ciclos
from domain.entregas import (
    avaliacao_entregas_aberta,
    carregar_ordem_apresentacao,
    grupos_da_sala,
    listar_grupos_avaliados,
    ordenar_grupos,
    proximo_grupo_pendente,
)
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.logs import registrar_log


def _chave_grupo(id_disc: str, id_ciclo: str, sala: str) -> str:
    return f"entrega_grupo_{id_disc}_{id_ciclo}_{sala}"


def _aplicar_grupo_pendente(chave: str):
    pendente = f"{chave}_proximo"
    if pendente in st.session_state:
        st.session_state[chave] = st.session_state.pop(pendente)


def _render_status_grupos(grupos: list[str], avaliados: set[str]):
    for i, g in enumerate(grupos, start=1):
        status = "✅ Avaliado" if g in avaliados else "⏳ Pendente"
        st.markdown(f"{i}. **Grupo {g}** — {status}")


def render(usuario: dict):
    st.header("Lançar notas da banca")
    st.caption("Lance apresentação e conteúdo técnico (0 a 5 cada). A nota total do grupo vai de 0 a 10.")

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox(
        "Disciplina:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
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
    )
    row_ciclo = ciclos[ciclos["Nome_Ciclo"].astype(str) == ciclo_sel].iloc[0]
    id_ciclo = str(row_ciclo["ID_Ciclo"]).strip()

    aberta, msg_janela = avaliacao_entregas_aberta(id_disc, id_ciclo)
    if not aberta:
        st.warning(msg_janela)
        st.caption("O coordenador define o período em **Configurações do Coordenador**.")
        st.stop()

    df_entrancia = ler_aba("Entrancia_Turma")
    entrancia = df_entrancia[df_entrancia["ID_Disciplina"].astype(str).str.strip() == id_disc]
    salas = sorted(entrancia["Sala"].dropna().astype(str).unique().tolist())
    if not salas:
        st.warning("Nenhuma sala cadastrada.")
        return

    sala_sel = st.selectbox("Sala:", salas, key=f"entrega_sala_{id_disc}_{id_ciclo}")
    grupos_base = grupos_da_sala(entrancia, sala_sel)
    if not grupos_base:
        st.warning("Nenhum grupo nesta sala.")
        return

    ordem_map = carregar_ordem_apresentacao(id_disc, id_ciclo, sala_sel)
    grupos = ordenar_grupos(grupos_base, ordem_map)
    avaliados = listar_grupos_avaliados(id_disc, id_ciclo, sala_sel)

    st.subheader(f"Status dos grupos — Sala {sala_sel}")
    st.caption("A numeração à esquerda é a ordem de apresentação (não confundir com o nome do grupo).")
    _render_status_grupos(grupos, avaliados)

    chave = _chave_grupo(id_disc, id_ciclo, sala_sel)
    _aplicar_grupo_pendente(chave)

    if chave not in st.session_state or st.session_state[chave] not in grupos:
        st.session_state[chave] = proximo_grupo_pendente(grupos, avaliados) or grupos[0]

    idx_atual = grupos.index(st.session_state[chave]) if st.session_state[chave] in grupos else 0
    st.caption(f"Apresentação **{idx_atual + 1}** de **{len(grupos)}** na ordem desta sala.")

    grupo_sel = st.selectbox("Grupo:", grupos, key=chave)

    existente = obter_avaliacao_grupo(id_ciclo, grupo_sel, sala_sel, id_disc)

    if existente:
        st.success(
            f"Grupo **{grupo_sel}** (sala **{sala_sel}**) já avaliado — "
            f"Apresentação **{formatar_nota_entrega(existente['nota_apresentacao'])}** | "
            f"Conteúdo **{formatar_nota_entrega(existente['nota_conteudo'])}** | "
            f"Total **{formatar_nota_entrega(existente['nota_total'])}**"
        )
    else:
        st.info(f"Grupo **{grupo_sel}** ainda não avaliado neste ciclo.")

    valor_ap = float(existente["nota_apresentacao"]) if existente else None
    valor_ct = float(existente["nota_conteudo"]) if existente else None
    valor_coment = existente["comentario"] if existente else ""
    ph_ap = f"Anterior: {formatar_nota_entrega(valor_ap)}" if valor_ap is not None else "Ex: 4"
    ph_ct = f"Anterior: {formatar_nota_entrega(valor_ct)}" if valor_ct is not None else "Ex: 5"

    with st.form(f"form_avaliacao_grupo_{id_disc}_{id_ciclo}_{sala_sel}_{grupo_sel}"):
        col1, col2 = st.columns(2)
        nota_ap_txt = col1.text_input(
            "Apresentação (0 a 5):",
            value="",
            placeholder=ph_ap,
        )
        nota_ct_txt = col2.text_input(
            "Conteúdo técnico (0 a 5):",
            value="",
            placeholder=ph_ct,
        )
        st.caption("Digite a nota diretamente (ex: 4 ou 4,5). Campos em branco para novo lançamento.")
        comentario = st.text_area(
            "Comentário para o grupo (opcional)",
            value="",
            placeholder=valor_coment if valor_coment else "",
        )
        confirmar_sub = False
        if existente:
            confirmar_sub = st.checkbox(
                "Confirmo que desejo registrar uma **nova** avaliação para este grupo "
                "(substitui a anterior nos cálculos — histórico permanece na planilha)."
            )
        salvar = st.form_submit_button("Salvar avaliação do grupo", type="primary", width="stretch")

    if salvar:
        if existente and not confirmar_sub:
            st.warning(
                "Este grupo já foi avaliado. Marque a confirmação acima para registrar uma nova avaliação."
            )
        else:
            nota_ap = parse_nota_entrega(nota_ap_txt)
            nota_ct = parse_nota_entrega(nota_ct_txt)
            if nota_ap is None or nota_ct is None:
                st.error("Informe notas válidas de 0 a 5 em apresentação e conteúdo.")
            else:
                total = salvar_avaliacao_grupo(
                    id_ciclo=id_ciclo,
                    nome_ciclo=ciclo_sel,
                    id_disciplina=id_disc,
                    sala=sala_sel,
                    grupo=grupo_sel,
                    nota_apresentacao=nota_ap,
                    nota_conteudo=nota_ct,
                    comentario=comentario,
                    email_avaliador=usuario["email"],
                    nome_avaliador=usuario["nome"],
                )
                registrar_log(
                    usuario["email"],
                    usuario["nome"],
                    f"Avaliação entregas grupo {grupo_sel} sala {sala_sel} - {ciclo_sel}",
                )

                proximo = proximo_grupo_pendente(grupos, avaliados | {grupo_sel}, grupo_sel)
                if proximo and proximo != grupo_sel:
                    st.session_state[f"{chave}_proximo"] = proximo

                st.success(f"Avaliação salva! Nota total: **{formatar_nota_entrega(total)}** / 10")
                if proximo and proximo != grupo_sel:
                    st.info(f"Próximo grupo sugerido: **{proximo}**")
                st.rerun()
