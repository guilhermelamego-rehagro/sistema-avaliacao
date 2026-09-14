"""Matrículas na oferta — situação, 2ª chamada, lote e histórico (ambiente teste)."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from data.supabase_academico import AmbienteProducaoError, academico_habilitado
from domain.formacao_grupos import mapa_nomes_disciplinas, rotulo_oferta
from domain.matriculas_oferta import (
    PENDENCIA_ROTULO,
    SITUACOES,
    atualizar_matricula,
    criar_matricula,
    filtrar_roster,
    historico_matricula,
    listar_ofertas,
    oferta_padrao_id,
    roster_matriculas,
)
from utils.logs import registrar_log
from utils.datas import formatar_datetime_br
from utils.ordenacao import chave_ordenacao_texto, ordenar_grupos_lista


def _parse_data_widget(valor) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    if len(texto) >= 10 and texto[4] == "-":
        try:
            return date.fromisoformat(texto[:10])
        except ValueError:
            return None
    return None


def _rotulo_aluno(r: dict) -> str:
    pend = PENDENCIA_ROTULO.get(r.get("pendencia"), r.get("pendencia") or "")
    extra = f" · {pend}" if r.get("pendencia") else ""
    return f"{r['nome']} <{r['email']}> — {r['situacao']}{extra}"


def render(usuario: dict):
    st.header("Matrículas na oferta")
    st.caption(
        "Situação do aluno **nesta disciplina/oferta** (≠ status do curso). "
        "Pendência de 2ª chamada é **só desta oferta** (não herda de outra disciplina). "
        "Em ofertas encerradas, use a alteração em lote. "
        "Filtros reiniciam ao trocar de oferta."
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

    escolha = st.selectbox("Oferta", options=rotulos, index=idx, key="mat_oferta")
    oferta = mapa[escolha]
    id_oferta = oferta["id_oferta"]

    try:
        roster = roster_matriculas(id_oferta)
    except Exception as exc:
        st.error(f"Erro ao carregar matrículas: {exc}")
        return

    c1, c2, c3 = st.columns([1.2, 1.2, 1.6])
    with c1:
        sit_f = st.multiselect(
            "Filtrar situação",
            options=list(SITUACOES),
            default=[],
            key=f"mat_filtro_sit_{id_oferta}",
            placeholder="Todas",
        )
    with c2:
        pend_opts = {
            "Sem pendência": "__none__",
            "Segunda chamada": "segunda_chamada",
        }
        pend_f = st.multiselect(
            "Filtrar pendência",
            options=list(pend_opts.keys()),
            default=[],
            key=f"mat_filtro_pend_{id_oferta}",
            placeholder="Todas",
        )
    with c3:
        busca = st.text_input("Busca (nome ou e-mail)", key=f"mat_busca_{id_oferta}")

    turmas_opts = sorted(
        {
            (r.get("turma") or "").strip() or "(sem turma)"
            for r in roster
        },
        key=chave_ordenacao_texto,
    )
    grupos_brutos = {
        (r.get("grupo_nome") or "").strip() or "(sem grupo)" for r in roster
    }
    com_grupo = ordenar_grupos_lista(
        [g for g in grupos_brutos if g != "(sem grupo)"]
    )
    grupos_opts = (["(sem grupo)"] if "(sem grupo)" in grupos_brutos else []) + com_grupo

    c4, c5 = st.columns(2)
    with c4:
        turma_f = st.multiselect(
            "Filtrar turma",
            options=turmas_opts,
            default=[],
            key=f"mat_filtro_turma_{id_oferta}",
            placeholder="Todas as turmas",
        )
    with c5:
        grupo_f = st.multiselect(
            "Filtrar grupo",
            options=grupos_opts,
            default=[],
            key=f"mat_filtro_grupo_{id_oferta}",
            placeholder="Todos os grupos",
        )

    pend_vals = [pend_opts[p] for p in pend_f] if pend_f else None
    filtrados = filtrar_roster(
        roster,
        situacoes=sit_f or None,
        pendencias=pend_vals,
        turmas=turma_f or None,
        grupos=grupo_f or None,
        busca=busca,
    )

    n_seg = sum(1 for r in roster if r.get("pendencia") == "segunda_chamada")
    m1, m2, m3 = st.columns(3)
    m1.metric("Matrículas", len(roster))
    m2.metric("Exibidas", len(filtrados))
    m3.metric("2ª chamada", n_seg)

    if not filtrados:
        st.info("Nenhuma matrícula com esses filtros.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Nome": r["nome"],
                        "E-mail": r["email"],
                        "Turma": r["turma"],
                        "Status curso": r["status_curso"],
                        "Situação": r["situacao"],
                        "Pendência": PENDENCIA_ROTULO.get(
                            r.get("pendencia"), r.get("pendencia") or "—"
                        ),
                        "Grupo": r["grupo_nome"] or "—",
                        "Data": r.get("data_situacao_efetiva") or "",
                    }
                    for r in filtrados
                ]
            ),
            hide_index=True,
            width="stretch",
        )

    msg_ok = st.session_state.pop("mat_bulk_msg_ok", None)
    if msg_ok:
        st.success(msg_ok)

    if filtrados:
        with st.expander("Editar uma matrícula (detalhe + histórico)"):
            opcoes = {_rotulo_aluno(r): r for r in filtrados}
            rot = st.selectbox("Matrícula", list(opcoes.keys()), key="mat_detalhe_sel")
            item = opcoes[rot]
            st.caption(
                f"Status do curso: **{item['status_curso']}** · "
                f"Turma: **{item['turma'] or '—'}** · "
                f"Grupo: **{item['grupo_nome'] or 'sem grupo'}**"
            )
            hist = historico_matricula(item["matricula_id"])
            if hist:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Quando": formatar_datetime_br(h.get("created_at")),
                                "De": h.get("situacao_anterior") or "—",
                                "Para": h.get("situacao_nova") or "",
                                "Pendência": PENDENCIA_ROTULO.get(
                                    h.get("pendencia"), h.get("pendencia") or "—"
                                ),
                                "Data efetiva": h.get("data_efetiva") or "",
                                "Motivo": h.get("motivo") or "",
                                "Por": h.get("registrado_por_email") or "",
                            }
                            for h in hist
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
            with st.form(f"form_mat_edit_{item['matricula_id']}"):
                st.caption(
                    "Mesma situação com **motivo** ou **observação** novos gera "
                    "outro registro no histórico (não apaga o anterior)."
                )
                sit_u = st.selectbox(
                    "Situação",
                    options=list(SITUACOES),
                    index=list(SITUACOES).index(item["situacao"])
                    if item["situacao"] in SITUACOES
                    else 0,
                )
                pend_labels = ["(nenhuma)", "Segunda chamada"]
                pend_atual = (
                    "Segunda chamada"
                    if item.get("pendencia") == "segunda_chamada"
                    else "(nenhuma)"
                )
                pend_u = st.selectbox(
                    "Pendência",
                    options=pend_labels,
                    index=pend_labels.index(pend_atual),
                )
                data_u = st.date_input(
                    "Data efetiva",
                    value=date.today(),
                    help=(
                        "Para nova situação. Em correção só de motivo, a data acadêmica "
                        "da matrícula é preservada; o histórico usa esta data."
                    ),
                )
                obs_u = st.text_area(
                    "Observação",
                    value=item.get("observacao") or "",
                    height=70,
                    help="Campo aberto na matrícula (pode corrigir a qualquer momento).",
                )
                motivo_u = st.text_input(
                    "Motivo (histórico)",
                    value="",
                    help="Obrigatório para registrar correção mantendo a mesma situação.",
                )
                salvar = st.form_submit_button("Salvar", type="primary")
            if salvar:
                pend = "segunda_chamada" if pend_u == "Segunda chamada" else None
                _, erro, aviso = atualizar_matricula(
                    item["matricula_id"],
                    situacao=sit_u,
                    pendencia=pend,
                    observacao=obs_u,
                    data_situacao_efetiva=data_u,
                    motivo=motivo_u,
                    registrado_por_email=usuario.get("email") or "",
                )
                if erro:
                    st.error(erro)
                else:
                    registrar_log(
                        usuario.get("email"),
                        usuario.get("nome"),
                        f"Matrícula {id_oferta}/{item['email']} → {sit_u}/{pend_u}",
                    )
                    if aviso:
                        st.info(aviso)
                    st.success("Matrícula atualizada.")
                    st.rerun()

    with st.expander("Incluir matrícula nesta oferta"):
        with st.form("form_mat_nova"):
            email_n = st.text_input("E-mail do aluno (ficha existente)")
            sit_n = st.selectbox("Situação inicial", options=list(SITUACOES), index=0)
            pend_n = st.selectbox(
                "Pendência inicial",
                options=["(nenhuma)", "Segunda chamada"],
                index=0,
            )
            obs_n = st.text_input("Observação", value="")
            if st.form_submit_button("Incluir"):
                pend = "segunda_chamada" if pend_n == "Segunda chamada" else None
                _, erro = criar_matricula(
                    email=email_n,
                    id_oferta=id_oferta,
                    situacao=sit_n,
                    pendencia=pend,
                    observacao=obs_n,
                    motivo="Inclusão manual na oferta",
                    registrado_por_email=usuario.get("email") or "",
                )
                if erro:
                    st.error(erro)
                else:
                    registrar_log(
                        usuario.get("email"),
                        usuario.get("nome"),
                        f"Incluiu matrícula {id_oferta}/{email_n}",
                    )
                    st.success("Matrícula criada.")
                    st.rerun()

    if filtrados:
        with st.expander("Alteração em lote", expanded=False):
            st.caption(
                "Selecione os alunos da lista filtrada → **Selecionar todos** "
                "e desmarque quem receberá situação diferente → aplique a mudança."
            )

            label_por_id = {_rotulo_aluno(r): r["matricula_id"] for r in filtrados}
            labels = list(label_por_id.keys())
            chave_sel = f"mat_bulk_sel_{id_oferta}"
            flag_all = "mat_bulk_pedir_todos"
            flag_clear = "mat_bulk_pedir_limpar"

            # Ajustes de seleção ANTES de instanciar o multiselect (regra do Streamlit)
            if st.session_state.pop(flag_all, False):
                st.session_state[chave_sel] = labels
            if st.session_state.pop(flag_clear, False):
                st.session_state[chave_sel] = []
            if chave_sel not in st.session_state:
                st.session_state[chave_sel] = []
            else:
                atual = st.session_state.get(chave_sel) or []
                if isinstance(atual, list):
                    limpo = [x for x in atual if x in labels]
                    if limpo != atual:
                        st.session_state[chave_sel] = limpo

            b1, b2, _b3 = st.columns([1, 1, 2])
            with b1:
                if st.button("Selecionar todos (filtrados)", key="mat_sel_todos"):
                    st.session_state[flag_all] = True
                    st.rerun()
            with b2:
                if st.button("Limpar seleção", key="mat_sel_limpar"):
                    st.session_state[flag_clear] = True
                    st.rerun()

            selecionados_lab = st.multiselect(
                "Alunos selecionados",
                options=labels,
                key=chave_sel,
                placeholder="Nenhum selecionado",
            )
            ids_sel = [
                label_por_id[lab] for lab in selecionados_lab if lab in label_por_id
            ]
            st.write(f"**{len(ids_sel)}** selecionado(s)")

            with st.form("form_mat_lote"):
                sit = st.selectbox("Nova situação", options=list(SITUACOES), index=0)
                pend_lab = st.selectbox(
                    "Nova pendência",
                    options=["(manter)", "(nenhuma)", "Segunda chamada"],
                    index=0,
                    help="«Manter» não altera a pendência de cada aluno.",
                )
                data_ef = st.date_input("Data efetiva", value=date.today())
                motivo = st.text_input(
                    "Motivo",
                    value="Encerramento da oferta — ajuste em lote",
                )
                aplicar = st.form_submit_button(
                    "Aplicar aos selecionados",
                    type="primary",
                    disabled=not ids_sel,
                )

            if aplicar and ids_sel:
                erros_lote: list[str] = []
                ok = 0
                for mid in ids_sel:
                    item = next((r for r in roster if r["matricula_id"] == mid), None)
                    if not item:
                        continue
                    if pend_lab == "(manter)":
                        pend = item.get("pendencia")
                    elif pend_lab == "Segunda chamada":
                        pend = "segunda_chamada"
                    else:
                        pend = None
                    _, erro, _aviso = atualizar_matricula(
                        mid,
                        situacao=sit,
                        pendencia=pend,
                        observacao=item.get("observacao") or "",
                        data_situacao_efetiva=data_ef,
                        motivo=motivo,
                        registrado_por_email=usuario.get("email") or "",
                    )
                    if erro:
                        erros_lote.append(f"{item.get('email')}: {erro}")
                    else:
                        ok += 1
                registrar_log(
                    usuario.get("email"),
                    usuario.get("nome"),
                    f"Lote matrículas {id_oferta}: {ok} → {sit}",
                )
                if erros_lote:
                    st.error("Falhas:\n" + "\n".join(erros_lote[:10]))
                if ok:
                    st.session_state["mat_bulk_msg_ok"] = (
                        f"{ok} matrícula(s) atualizada(s) para **{sit}**."
                    )
                    st.session_state[flag_clear] = True
                    st.rerun()
