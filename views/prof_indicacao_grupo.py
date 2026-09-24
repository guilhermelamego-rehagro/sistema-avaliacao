"""Painel docente: ranking, janela e acompanhamento das indicações de grupo."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.cadastros import carregar_ciclos
from domain.indicacao_grupo import (
    STATUS_ABERTA,
    STATUS_FECHADA,
    STATUS_RASCUNHO,
    abrir_janela,
    atualizar_excluidos,
    calcular_ranking_ciclo,
    candidatos_desempate_grupo,
    carregar_indicacoes,
    carregar_janelas,
    carregar_ranking,
    criar_janela_rascunho,
    fechar_janela,
    marcar_desempate_coord,
    recalcular_posicoes_exibicao,
)
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa, normalizar_id
from utils.logs import registrar_log
from utils.ordenacao import chave_ordenacao_texto


def _ciclos_disciplina(id_disc: str) -> pd.DataFrame:
    df = carregar_ciclos()
    if df.empty:
        return df
    id_d = normalizar_id(id_disc)
    out = df[df["ID_Disciplina"].map(normalizar_id) == id_d].copy()
    if "Ordem" in out.columns:
        out["_ord"] = pd.to_numeric(out["Ordem"], errors="coerce").fillna(999)
        out = out.sort_values(["_ord", "Nome_Ciclo"], kind="mergesort")
        out = out.drop(columns=["_ord"])
    else:
        out = out.sort_values("Nome_Ciclo", kind="mergesort")
    return out.reset_index(drop=True)


def _label_janela(row: pd.Series) -> str:
    nome = str(row.get("Nome_Ciclo", "")).strip() or str(row.get("ID_Ciclo", "")).strip()
    status = str(row.get("Status", "")).strip()
    criacao = str(row.get("Criado_Em", "")).strip()
    return f"{nome} · {status} · {criacao[:16]} · {str(row.get('ID_Janela', ''))[:8]}"


def _render_gerar_ranking(usuario: dict, id_disc: str):
    st.subheader("Gerar ranking do ciclo")
    st.caption(
        "Calcula a nota do ciclo por aluno, desempata por % dailies e % aulas, "
        "e define o melhor de cada grupo. Empates totais ficam para a coordenação."
    )
    ciclos = _ciclos_disciplina(id_disc)
    if ciclos.empty:
        st.warning("Nenhum ciclo cadastrado para esta disciplina.")
        return

    opcoes = {
        f"{str(r.get('Nome_Ciclo', '')).strip()} ({str(r.get('ID_Ciclo', '')).strip()})": str(
            r.get("ID_Ciclo", "")
        ).strip()
        for _, r in ciclos.iterrows()
    }
    labels = list(opcoes.keys())
    # Preferência: Ciclo 4 se existir
    idx = 0
    for i, lab in enumerate(labels):
        if "ciclo 4" in lab.lower() or lab.lower().startswith("c4"):
            idx = i
            break
    lab_sel = st.selectbox("Ciclo:", labels, index=idx, key="ind_grp_ciclo")
    id_ciclo = opcoes[lab_sel]
    nome_ciclo = lab_sel.split(" (")[0]

    if st.button("Calcular e salvar ranking (rascunho)", type="primary", key="ind_grp_calc"):
        with st.spinner("Calculando ranking… pode levar alguns minutos."):
            ranking = calcular_ranking_ciclo(id_disc, id_ciclo)
            if ranking.empty:
                st.error("Nenhum aluno ativo encontrado para ranquear.")
                return
            id_j = criar_janela_rascunho(
                id_disc,
                id_ciclo,
                nome_ciclo,
                usuario.get("email", ""),
                usuario.get("nome", ""),
                ranking,
            )
            registrar_log(
                usuario.get("email", ""),
                usuario.get("nome", ""),
                f"Gerou ranking indicação grupo janela={id_j} ciclo={id_ciclo}",
            )
            st.session_state["ind_grp_janela_sel"] = id_j
            st.success(f"Ranking salvo em rascunho (janela `{id_j[:8]}…`). Abra a aba Ranking.")
            st.rerun()


def _render_ranking(id_disc: str):
    st.subheader("Ranking e desempate")
    janelas = carregar_janelas(id_disc)
    if janelas.empty:
        st.info("Nenhuma janela ainda. Gere o ranking na aba Janela.")
        return

    janelas = janelas.sort_values("Criado_Em", ascending=False, kind="mergesort")
    mapa = {_label_janela(r): str(r.get("ID_Janela", "")).strip() for _, r in janelas.iterrows()}
    labels = list(mapa.keys())
    preferida = str(st.session_state.get("ind_grp_janela_sel", "")).strip()
    idx = 0
    for i, lab in enumerate(labels):
        if mapa[lab] == preferida:
            idx = i
            break
    lab = st.selectbox("Janela:", labels, index=idx, key="ind_grp_rank_janela")
    id_j = mapa[lab]
    st.session_state["ind_grp_janela_sel"] = id_j

    row_j = janelas[janelas["ID_Janela"].astype(str).str.strip() == id_j].iloc[0]
    st.caption(
        f"Status: **{row_j.get('Status')}** · "
        f"Ciclo: **{row_j.get('Nome_Ciclo')}** · "
        f"Excluídos: {row_j.get('Emails_Excluidos') or '—'}"
    )

    rank = carregar_ranking(id_j)
    if rank.empty:
        st.warning("Ranking vazio nesta janela.")
        return

    rank = recalcular_posicoes_exibicao(rank)

    cols = [
        c
        for c in (
            "Sala",
            "Grupo",
            "Posicao_Grupo",
            "Nome_Aluno",
            "Email_Aluno",
            "Nota_Ciclo",
            "Pct_Dailies",
            "Pct_Aulas",
            "Vencedor",
            "Desempate_Coord",
        )
        if c in rank.columns
    ]
    mostrar = rank[cols].copy()
    mostrar["_sala"] = mostrar["Sala"].map(lambda x: chave_ordenacao_texto(str(x)))
    mostrar["_grupo"] = mostrar["Grupo"].map(lambda x: chave_ordenacao_texto(str(x)))
    mostrar["_pos"] = pd.to_numeric(mostrar["Posicao_Grupo"], errors="coerce").fillna(999)
    mostrar["_nome"] = mostrar["Nome_Aluno"].map(lambda x: chave_ordenacao_texto(str(x)))
    mostrar = mostrar.sort_values(
        ["_sala", "_grupo", "_pos", "_nome"], kind="mergesort"
    ).drop(columns=["_sala", "_grupo", "_pos", "_nome"])
    st.dataframe(
        mostrar,
        width="stretch",
        hide_index=True,
        column_config={
            "Posicao_Grupo": st.column_config.NumberColumn("Posição", format="%d"),
            "Nota_Ciclo": st.column_config.NumberColumn(format="%.3f"),
            "Pct_Dailies": st.column_config.NumberColumn(format="%.3f"),
            "Pct_Aulas": st.column_config.NumberColumn(format="%.3f"),
        },
    )
    st.caption(
        "Posição: empates em nota + % dailies + % aulas repetem o mesmo número "
        "(ex.: 1, 1, 3)."
    )

    # Empates no 1º lugar (todos os critérios): só esses entram no desempate da coord.
    sem_v = []
    for (sala, grupo), bloco in rank.groupby(["Sala", "Grupo"], dropna=False):
        ven = bloco[bloco["Vencedor"].astype(str).str.strip().str.lower().isin({"sim", "s", "1", "true"})]
        if ven.empty:
            empatados = candidatos_desempate_grupo(bloco)
            if len(empatados) > 1:
                sem_v.append((str(sala), str(grupo), empatados))

    if sem_v:
        st.warning(
            f"{len(sem_v)} grupo(s) empatado(s) no 1º lugar — "
            "escolha o vencedor apenas entre os empatados."
        )
        for sala, grupo, empatados in sem_v:
            opcoes = {
                (
                    f"{r['Nome_Aluno']} ({r['Email_Aluno']}) — "
                    f"nota {r['Nota_Ciclo']} · dailies {r['Pct_Dailies']}% · "
                    f"aulas {r['Pct_Aulas']}%"
                ): str(r["Email_Aluno"])
                for _, r in empatados.iterrows()
            }
            with st.expander(f"Desempate · Sala {sala} · Grupo {grupo}"):
                st.caption(
                    f"{len(opcoes)} aluno(s) empatados em nota, % dailies e % aulas."
                )
                escolha = st.selectbox(
                    "Vencedor definido pela coordenação:",
                    list(opcoes.keys()),
                    key=f"ind_grp_emp_{id_j}_{sala}_{grupo}",
                )
                if st.button("Confirmar desempate", key=f"ind_grp_emp_ok_{id_j}_{sala}_{grupo}"):
                    erro = marcar_desempate_coord(id_j, opcoes[escolha])
                    if erro:
                        st.error(erro)
                    else:
                        st.success("Desempate registrado.")
                        st.rerun()
    else:
        st.success("Todos os grupos têm vencedor definido.")


def _render_janela(usuario: dict, id_disc: str):
    st.subheader("Abrir / fechar janela")
    janelas = carregar_janelas(id_disc)
    if janelas.empty:
        st.info("Gere um ranking primeiro (aba Ranking → Calcular).")
        _render_gerar_ranking(usuario, id_disc)
        return

    _render_gerar_ranking(usuario, id_disc)
    st.divider()

    janelas = janelas.sort_values("Criado_Em", ascending=False, kind="mergesort")
    mapa = {_label_janela(r): str(r.get("ID_Janela", "")).strip() for _, r in janelas.iterrows()}
    labels = list(mapa.keys())
    preferida = str(st.session_state.get("ind_grp_janela_sel", "")).strip()
    idx = 0
    for i, lab in enumerate(labels):
        if mapa[lab] == preferida:
            idx = i
            break
    lab = st.selectbox("Janela para configurar:", labels, index=idx, key="ind_grp_cfg_janela")
    id_j = mapa[lab]
    st.session_state["ind_grp_janela_sel"] = id_j
    row = janelas[janelas["ID_Janela"].astype(str).str.strip() == id_j].iloc[0]
    status = str(row.get("Status", "")).strip().lower()

    alunos = ler_aba("Entrancia_Turma")
    id_d = normalizar_id(id_disc)
    if not alunos.empty:
        alunos = alunos[alunos["ID_Disciplina"].map(normalizar_id) == id_d].copy()
        alunos["Email_Limpo"] = alunos["Email_Pessoal"].astype(str).str.strip().str.lower()
        alunos = alunos.drop_duplicates("Email_Limpo")
        opcoes_exc = {
            f"{str(r.get('Nome_Completo', '')).strip()} <{str(r.get('Email_Pessoal', '')).strip()}>": str(
                r.get("Email_Pessoal", "")
            )
            .strip()
            .lower()
            for _, r in alunos.iterrows()
            if str(r.get("Email_Pessoal", "")).strip()
        }
    else:
        opcoes_exc = {}

    excluidos_atuais = [
        e.strip().lower()
        for e in str(row.get("Emails_Excluidos", "")).replace(";", ",").split(",")
        if e.strip()
    ]
    defaults = [lab for lab, em in opcoes_exc.items() if em in excluidos_atuais]
    selecionados = st.multiselect(
        "Excluir da pool de escolha (ex.: desistentes manuais):",
        options=list(opcoes_exc.keys()),
        default=defaults,
        key=f"ind_grp_exc_{id_j}",
    )
    if st.button("Salvar exclusões", key=f"ind_grp_exc_save_{id_j}"):
        atualizar_excluidos(id_j, [opcoes_exc[s] for s in selecionados])
        st.success("Exclusões atualizadas.")
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        di = st.date_input(
            "Início da janela",
            value=date.today(),
            key=f"ind_grp_di_{id_j}",
        )
    with col2:
        dfim = st.date_input(
            "Fim da janela",
            value=date.today() + timedelta(days=2),
            key=f"ind_grp_df_{id_j}",
        )

    c1, c2 = st.columns(2)
    with c1:
        if status in {STATUS_RASCUNHO, STATUS_FECHADA}:
            if st.button("Abrir janela", type="primary", key=f"ind_grp_abrir_{id_j}"):
                erro = abrir_janela(
                    id_j,
                    di.strftime("%d/%m/%Y"),
                    dfim.strftime("%d/%m/%Y"),
                )
                if erro:
                    st.error(erro)
                else:
                    registrar_log(
                        usuario.get("email", ""),
                        usuario.get("nome", ""),
                        f"Abriu janela indicação grupo {id_j}",
                    )
                    st.success("Janela aberta. Vencedores já podem indicar.")
                    st.rerun()
        elif status == STATUS_ABERTA:
            st.info(
                f"Janela aberta de {row.get('Data_Inicio')} a {row.get('Data_Fim')}."
            )
    with c2:
        if status == STATUS_ABERTA:
            if st.button("Fechar janela", key=f"ind_grp_fechar_{id_j}"):
                erro = fechar_janela(id_j)
                if erro:
                    st.error(erro)
                else:
                    st.success("Janela fechada.")
                    st.rerun()


def _render_indicacoes(id_disc: str):
    st.subheader("Indicações confirmadas")
    janelas = carregar_janelas(id_disc)
    if janelas.empty:
        st.info("Nenhuma janela.")
        return
    janelas = janelas.sort_values("Criado_Em", ascending=False, kind="mergesort")
    mapa = {_label_janela(r): str(r.get("ID_Janela", "")).strip() for _, r in janelas.iterrows()}
    lab = st.selectbox("Janela:", list(mapa.keys()), key="ind_grp_ind_janela")
    id_j = mapa[lab]
    ind = carregar_indicacoes(id_j)
    if ind.empty:
        st.caption("Ainda não há indicações confirmadas.")
        return
    cols = [c for c in ("Nome_Vencedor", "Email_Vencedor", "Nome_Escolhido", "Email_Escolhido", "Confirmado_Em") if c in ind.columns]
    st.dataframe(ind[cols], width="stretch", hide_index=True)

    rank = carregar_ranking(id_j)
    ven = rank[rank["Vencedor"].astype(str).str.strip().str.lower().isin({"sim", "s", "1", "true"})]
    feitos = set(ind["Email_Vencedor"].astype(str).str.strip().str.lower()) if not ind.empty else set()
    pendentes = ven[~ven["Email_Aluno"].astype(str).str.strip().str.lower().isin(feitos)]
    if not pendentes.empty:
        st.warning(f"{len(pendentes)} vencedor(es) ainda não indicaram.")
        st.dataframe(
            pendentes[["Sala", "Grupo", "Nome_Aluno", "Email_Aluno"]],
            width="stretch",
            hide_index=True,
        )


def render(usuario: dict):
    st.header("Indicação de grupos")
    st.caption(
        "O melhor de cada grupo no ciclo escolhido indica um colega da oferta "
        "para o próximo agrupamento. O indicado não vê quem o escolheu."
    )

    df_disc = ler_aba("Disciplinas")
    lista = df_disc["Nome_Disciplina"].unique().tolist()
    disc = st.selectbox(
        "Disciplina:",
        lista,
        index=indice_disciplina_ativa(df_disc, lista),
        key="ind_grp_disc",
    )
    id_disc = id_disciplina_por_nome(df_disc, disc)

    aba1, aba2, aba3 = st.tabs(["Janela", "Ranking", "Indicações"])
    with aba1:
        _render_janela(usuario, id_disc)
    with aba2:
        _render_ranking(id_disc)
    with aba3:
        _render_indicacoes(id_disc)
