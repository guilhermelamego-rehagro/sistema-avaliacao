"""Ficha acadêmica do aluno — status, turmas e histórico (ambiente teste)."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from data.supabase_academico import AmbienteProducaoError, academico_habilitado
from domain.alunos_ficha import (
    STATUS_CURSO,
    atualizar_ficha,
    enriquecer_historico_com_notas,
    filtrar_alunos,
    historico_escolar,
    historico_status,
    listar_alunos,
    listar_turmas,
    reingressar,
)
from utils.logs import registrar_log
from utils.datas import formatar_datetime_br


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


def render(usuario: dict):
    st.header("Ficha de alunos")
    st.caption("Modelo acadêmico no Supabase de teste — status do curso, turmas e histórico.")

    if not academico_habilitado():
        st.warning("Disponível apenas com ambiente=teste.")
        return

    try:
        alunos = listar_alunos()
        turmas = listar_turmas()
    except AmbienteProducaoError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"Erro ao carregar fichas: {exc}")
        return

    codigos_turma = [""] + [t["id_turma"] for t in turmas]

    c1, c2, c3, c4 = st.columns([1.1, 1.1, 1.2, 1.5])
    with c1:
        status_f = st.multiselect(
            "Status",
            options=list(STATUS_CURSO),
            default=[],
            key="ficha_filtro_status_multi",
            placeholder="Todos os status",
        )
    with c2:
        turma_f = st.multiselect(
            "Turma vínculo/ingresso",
            options=[t["id_turma"] for t in turmas],
            default=[],
            key="ficha_filtro_turma_multi",
            placeholder="Todas as turmas",
        )
    with c3:
        ofertas_f = st.multiselect(
            "Ofertas ativas",
            options=["Sem oferta ativa", "Com oferta ativa"],
            default=[],
            key="ficha_filtro_ofertas_ativas",
            placeholder="Todas",
        )
    with c4:
        busca = st.text_input("Busca (nome ou e-mail)", key="ficha_busca")

    filtrados = filtrar_alunos(
        alunos,
        status=status_f or None,
        turma=turma_f or None,
        busca=busca,
    )
    if ofertas_f:
        sem_oferta = "Sem oferta ativa" in ofertas_f
        com_oferta = "Com oferta ativa" in ofertas_f
        filtrados = [
            aluno
            for aluno in filtrados
            if (sem_oferta and not aluno.get("n_ofertas_ativas"))
            or (com_oferta and aluno.get("n_ofertas_ativas"))
        ]

    st.write(f"**{len(filtrados)}** aluno(s) (de {len(alunos)})")

    if not filtrados:
        st.info("Nenhum aluno com esses filtros.")
        return

    df = pd.DataFrame(
        [
            {
                "Nome": a.get("nome") or "",
                "E-mail": a.get("email") or "",
                "Status": a.get("status_curso") or "",
                "Ofertas ativas": a.get("n_ofertas_ativas", 0),
                "Turma vínculo": a.get("turma_vinculo") or "",
                "Turma ingresso": a.get("turma_ingresso") or "",
                "Data status": a.get("data_status_efetiva") or "",
                "Login": "sim" if a.get("user_id") else "não",
                "_id": a["id"],
            }
            for a in filtrados
        ]
    )

    evento = st.dataframe(
        df.drop(columns=["_id"]),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="ficha_tabela",
    )

    selected_id = None
    try:
        rows = evento.selection.rows  # type: ignore[attr-defined]
        if rows:
            selected_id = df.iloc[rows[0]]["_id"]
    except Exception:
        selected_id = st.session_state.get("ficha_aluno_id")

    if not selected_id:
        # fallback: selectbox
        opcoes = {f"{a.get('nome')} <{a.get('email')}>": a["id"] for a in filtrados}
        rotulo = st.selectbox(
            "Ou selecione o aluno",
            options=list(opcoes.keys()),
            key="ficha_select_aluno",
        )
        selected_id = opcoes[rotulo]

    anterior_id = st.session_state.get("ficha_aluno_id")
    st.session_state["ficha_aluno_id"] = selected_id
    # Troca de aluno: limpa widgets do formulário anterior (evita status/turma “grudados”).
    if anterior_id and anterior_id != selected_id:
        for chave in list(st.session_state.keys()):
            if chave.startswith(("form_ficha_aluno", "form_reingresso", "reing_")):
                del st.session_state[chave]

    aluno = next((a for a in alunos if a["id"] == selected_id), None)
    if not aluno:
        st.error("Aluno não encontrado.")
        return

    # Alinha oferta Ativa ao status do curso (ex.: trancado → trancado),
    # inclusive quando a ficha já veio divergente de import/ajuste manual.
    status_curso_atual = aluno.get("status_curso") or ""
    if status_curso_atual in {"trancado", "desistente", "cancelado"}:
        chave_sync = f"_espelho_oferta_{selected_id}_{status_curso_atual}"
        if not st.session_state.get(chave_sync):
            try:
                from domain.matriculas_oferta import espelhar_status_curso_nas_matriculas

                n_sync, erros_sync, _avisos_sync = espelhar_status_curso_nas_matriculas(
                    aluno["id"],
                    status_curso=status_curso_atual,
                    data_efetiva=aluno.get("data_status_efetiva"),
                    motivo=(
                        f"Alinhamento automático: status do curso → {status_curso_atual}"
                    ),
                    registrado_por_email=usuario.get("email") or "sistema",
                )
                st.session_state[chave_sync] = True
                if n_sync:
                    st.info(
                        f"Oferta Ativa alinhada ao status **{status_curso_atual}** "
                        f"({n_sync} matrícula(s))."
                    )
                    st.rerun()
                elif erros_sync:
                    st.warning("Não foi possível alinhar a oferta Ativa: " + "; ".join(erros_sync[:3]))
            except Exception as exc:
                st.warning(f"Falha ao alinhar oferta Ativa: {exc}")

    st.subheader(f"{aluno.get('nome')} — {aluno.get('email')}")

    c_h1, c_h2, c_h3, c_h4, c_h5 = st.columns(5)
    c_h1.metric("Status do curso", aluno.get("status_curso") or "—")
    c_h2.metric("Turma vínculo", aluno.get("turma_vinculo") or "—")
    c_h3.metric("Turma ingresso", aluno.get("turma_ingresso") or "—")
    c_h4.metric(
        "Login",
        "sim" if aluno.get("user_id") else "não",
    )
    c_h5.metric("Ofertas ativas", aluno.get("n_ofertas_ativas", 0))
    if aluno.get("data_status_efetiva"):
        st.caption(f"Data efetiva do status: {aluno.get('data_status_efetiva')}")
    if aluno.get("observacao"):
        st.caption(f"Observação: {aluno.get('observacao')}")

    hist = historico_status(aluno["id"])
    with st.expander("Histórico de status do curso", expanded=False):
        if not hist:
            st.caption("Sem alterações registradas.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Quando": formatar_datetime_br(h.get("created_at")),
                            "De": h.get("status_anterior") or "—",
                            "Para": h.get("status_novo") or "",
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

    status_atual = aluno.get("status_curso") or "matriculado"
    pode_reingressar = status_atual in {"trancado", "desistente", "cancelado"}

    tab_hist, tab_edit, tab_reingresso = st.tabs(
        ["Histórico escolar", "Editar ficha", "Reingressar"]
    )

    with tab_hist:
        st.caption(
            "Disciplinas/ofertas em que o aluno constou matriculado, com a "
            "**situação na oferta**. A nota do boletim (planilha) é opcional — "
            "só carrega sob demanda para não deixar a tela lenta."
        )
        incluir_notas = st.checkbox(
            "Incluir nota do boletim (quando houver grupo e lançamentos)",
            value=False,
            key=f"hist_notas_{selected_id}",
        )
        try:
            hist_esc = historico_escolar(aluno["id"])
            if incluir_notas and hist_esc:
                with st.spinner("Calculando notas do boletim..."):
                    hist_esc = enriquecer_historico_com_notas(
                        hist_esc,
                        aluno.get("email") or "",
                        incluir_notas=True,
                    )
            else:
                hist_esc = enriquecer_historico_com_notas(
                    hist_esc, aluno.get("email") or "", incluir_notas=False
                )
        except Exception as exc:
            st.error(f"Erro ao montar histórico escolar: {exc}")
            hist_esc = []

        if not hist_esc:
            st.info("Nenhuma matrícula em oferta para este aluno.")
        else:
            from domain.matriculas_oferta import PENDENCIA_ROTULO

            df_hist = pd.DataFrame(
                [
                    {
                        "Disciplina": h.get("disciplina") or "",
                        "Oferta": h.get("id_oferta") or "",
                        "Trimestre": h.get("trimestre") or "",
                        "Status oferta": h.get("status_oferta") or "",
                        "Situação": h.get("situacao") or "",
                        "Pendência": PENDENCIA_ROTULO.get(
                            h.get("pendencia"), h.get("pendencia") or "—"
                        )
                        if h.get("pendencia")
                        else "—",
                        "Data situação": h.get("data_situacao") or "",
                        "Grupo": h.get("grupo") or "—",
                        "Nota": (
                            f"{h['nota_final']:.1f}"
                            if h.get("nota_final") is not None
                            else "—"
                        ),
                        "Resultado (boletim)": h.get("resultado_boletim") or "—",
                    }
                    for h in hist_esc
                ]
            )
            st.dataframe(df_hist, hide_index=True, width="stretch")
            st.caption(
                f"{len(hist_esc)} disciplina(s)/oferta(s). "
                "Situação = registro acadêmico na matrícula; "
                "nota = motor do boletim (Sheets), quando disponível."
            )

    with tab_edit:
        st.caption(
            "Só a **oferta Ativa** acompanha o status do curso "
            "(trancado / desistente / cancelado, ou volta a cursando no reingresso), "
            "usando a **data efetiva** do status. "
            "Ofertas encerradas/passadas **não mudam** automaticamente — "
            "se ainda estiverem como cursando, ajuste manual em Matrículas na oferta."
        )
        # Chave por aluno: senão o Streamlit reusa o status/turma do aluno anterior.
        with st.form(f"form_ficha_aluno_{selected_id}"):
            novo_status = st.selectbox(
                "Status do curso",
                options=list(STATUS_CURSO),
                index=list(STATUS_CURSO).index(status_atual)
                if status_atual in STATUS_CURSO
                else 0,
            )
            data_efetiva = st.date_input(
                "Data efetiva do status",
                value=date.today(),
                help=(
                    "Data desta alteração (não a última já registrada). "
                    f"Última no cadastro: "
                    f"{_parse_data_widget(aluno.get('data_status_efetiva')) or '—'}"
                ),
            )
            i_ing = (
                codigos_turma.index(aluno.get("turma_ingresso"))
                if aluno.get("turma_ingresso") in codigos_turma
                else 0
            )
            i_vin = (
                codigos_turma.index(aluno.get("turma_vinculo"))
                if aluno.get("turma_vinculo") in codigos_turma
                else 0
            )
            turma_ing = st.selectbox("Turma de ingresso", options=codigos_turma, index=i_ing)
            turma_vin = st.selectbox("Turma vínculo", options=codigos_turma, index=i_vin)
            observacao = st.text_area(
                "Observação", value=aluno.get("observacao") or "", height=80
            )
            motivo = st.text_input("Motivo (se mudar status)", value="")
            conf_sem = False
            if novo_status == "matriculado" and status_atual in {"desistente", "cancelado"}:
                conf_sem = st.checkbox(
                    "Confirmo reingresso sem aproveitamento de histórico acadêmico",
                    value=False,
                )
            if novo_status == "matriculado" and status_atual == "trancado":
                st.info(
                    "Reingresso a partir de trancado: aproveitamento de histórico é possível "
                    "(motor de dispensa ainda não automatizado)."
                )
            salvar = st.form_submit_button("Salvar ficha", type="primary")

        if salvar:
            ficha, erro, aviso = atualizar_ficha(
                aluno["id"],
                status_curso=novo_status,
                data_status_efetiva=data_efetiva,
                turma_ingresso=turma_ing or None,
                turma_vinculo=turma_vin or None,
                observacao=observacao,
                motivo=motivo,
                registrado_por_email=usuario.get("email") or "",
                confirmou_sem_aproveitamento=conf_sem,
                status_anterior=status_atual,
            )
            if erro:
                st.error(erro)
            else:
                registrar_log(
                    usuario.get("email"),
                    usuario.get("nome"),
                    f"Atualizou ficha aluno {aluno.get('email')} → {novo_status}",
                )
                if aviso:
                    st.info(aviso)
                st.success("Ficha salva.")
                st.rerun()

    with tab_reingresso:
        if not pode_reingressar:
            st.caption("Disponível quando o status for trancado, desistente ou cancelado.")
        else:
            with st.form(f"form_reingresso_{selected_id}"):
                st.write(f"Status atual: **{status_atual}** → **matriculado**")
                data_r = st.date_input(
                    "Data efetiva",
                    value=date.today(),
                    key=f"reing_data_{selected_id}",
                )
                i_vin_r = (
                    codigos_turma.index(aluno.get("turma_vinculo"))
                    if aluno.get("turma_vinculo") in codigos_turma
                    else 0
                )
                turma_r = st.selectbox(
                    "Turma vínculo após reingresso",
                    options=codigos_turma,
                    index=i_vin_r,
                    key=f"reing_turma_{selected_id}",
                )
                motivo_r = st.text_input(
                    "Motivo",
                    value="Reingresso",
                    key=f"reing_motivo_{selected_id}",
                )
                conf_r = False
                if status_atual in {"desistente", "cancelado"}:
                    st.warning(
                        "Desistente/cancelado: ao voltar, **não** há aproveitamento de histórico."
                    )
                    conf_r = st.checkbox(
                        "Confirmo reingresso sem aproveitamento de histórico",
                        value=False,
                        key=f"reing_conf_{selected_id}",
                    )
                else:
                    st.info(
                        "Trancado: aproveitamento de histórico é possível "
                        "(dispensa/crédito — ainda manual)."
                    )
                    conf_r = True
                ok_r = st.form_submit_button("Confirmar reingresso", type="primary")

            if ok_r:
                ficha, erro, aviso = reingressar(
                    aluno["id"],
                    data_efetiva=data_r,
                    motivo=motivo_r,
                    registrado_por_email=usuario.get("email") or "",
                    confirmou_sem_aproveitamento=conf_r,
                    turma_vinculo=turma_r or None,
                )
                if erro:
                    st.error(erro)
                else:
                    registrar_log(
                        usuario.get("email"),
                        usuario.get("nome"),
                        f"Reingressou aluno {aluno.get('email')}",
                    )
                    if aviso:
                        st.info(aviso)
                    st.success("Aluno reingressado como matriculado.")
                    st.rerun()
