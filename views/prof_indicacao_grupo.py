"""Painel docente da indicação de grupos: uma tela por ciclo, em passos."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.cadastros import carregar_ciclos
from domain.indicacao_grupo import (
    STATUS_ABERTA,
    STATUS_FECHADA,
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

_SIM = {"sim", "s", "1", "true"}

SIT_INDICOU = "✅ Indicou"
SIT_AGUARDANDO = "⏳ Aguardando indicação"
SIT_PRONTO = "Pronto para indicar"
SIT_NAO_INDICOU = "Não indicou"
SIT_EMPATE = "⚠️ Empate: escolha acima"
SIT_SEM_NOTA = "⚠️ Sem nota do ciclo: escolha acima"


def _num(valor) -> float | None:
    v = pd.to_numeric(valor, errors="coerce")
    return None if pd.isna(v) else float(v)


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


def _rodadas(id_disc: str) -> pd.DataFrame:
    """Janelas da disciplina, da mais recente para a mais antiga."""
    jan = carregar_janelas(id_disc)
    if jan.empty:
        return jan
    jan = jan.copy()
    jan["_criado"] = pd.to_datetime(jan["Criado_Em"], dayfirst=True, errors="coerce")
    return jan.sort_values("_criado", ascending=False, kind="mergesort", na_position="last").reset_index(drop=True)


def _escolher_ciclo(id_disc: str, rodadas: pd.DataFrame) -> tuple[str, str] | None:
    ciclos = _ciclos_disciplina(id_disc)
    if ciclos.empty:
        st.warning("Nenhum ciclo cadastrado para esta disciplina.")
        return None
    nomes = [str(r.get("Nome_Ciclo", "")).strip() or str(r.get("ID_Ciclo", "")).strip() for _, r in ciclos.iterrows()]
    ids = [str(r.get("ID_Ciclo", "")).strip() for _, r in ciclos.iterrows()]
    repetidos = {n for n in nomes if nomes.count(n) > 1}
    rotulos = [f"{n} ({i})" if n in repetidos else n for n, i in zip(nomes, ids)]

    idx = 0
    if not rodadas.empty:
        ultimo = str(rodadas.iloc[0].get("ID_Ciclo", "")).strip()
        if ultimo in ids:
            idx = ids.index(ultimo)
    rot = st.selectbox("Ciclo:", rotulos, index=idx, key=f"ind_grp_ciclo_{id_disc}")
    i = rotulos.index(rot)
    return ids[i], nomes[i]


def _montar_quadro(rank: pd.DataFrame, ind: pd.DataFrame, status: str) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """Uma linha por grupo + grupos empatados ainda sem escolha + empates já decididos (editáveis)."""
    feitos: dict[str, str] = {}
    if not ind.empty:
        conf = ind[ind["Status"].astype(str).str.strip().str.lower() == "confirmado"]
        for _, r in conf.iterrows():
            feitos[str(r["Email_Vencedor"]).strip().lower()] = str(r.get("Nome_Escolhido", "")).strip()

    linhas: list[dict] = []
    pendentes: list[dict] = []
    decididos: list[dict] = []
    for (sala, grupo), bloco in rank.groupby(["Sala", "Grupo"], dropna=False):
        sala, grupo = str(sala).strip(), str(grupo).strip()
        ven = bloco[bloco["Vencedor"].astype(str).str.strip().str.lower().isin(_SIM)]
        empatados = candidatos_desempate_grupo(bloco)
        sem_nota = pd.to_numeric(empatados.get("Nota_Ciclo"), errors="coerce").isna().all()
        item = {"sala": sala, "grupo": grupo, "empatados": empatados, "sem_nota": sem_nota}
        indicado = ""
        if not ven.empty:
            nomes = ven["Nome_Aluno"].astype(str).str.strip().tolist()
            emails = ven["Email_Aluno"].astype(str).str.strip().str.lower().tolist()
            melhor = " e ".join(nomes)
            if len(nomes) == 1:
                indicado = feitos.get(emails[0], "")
            else:
                indicado = "; ".join(f"{n} → {feitos[e]}" for n, e in zip(nomes, emails) if e in feitos)
            if all(e in feitos for e in emails):
                situacao = SIT_INDICOU
            elif status == STATUS_ABERTA:
                situacao = SIT_AGUARDANDO
            elif status == STATUS_FECHADA:
                situacao = SIT_NAO_INDICOU
            else:
                situacao = SIT_PRONTO
            if len(empatados) > 1:
                decididos.append({**item, "atuais": emails, "indicaram": [e for e in emails if e in feitos]})
        else:
            situacao = SIT_SEM_NOTA if sem_nota else SIT_EMPATE
            melhor = ", ".join(empatados["Nome_Aluno"].astype(str).str.strip())
            pendentes.append(item)
        linhas.append(
            {
                "Sala": sala,
                "Grupo": grupo,
                "Melhor do grupo": melhor,
                "Situação": situacao,
                "Indicou": indicado,
            }
        )

    quadro = pd.DataFrame(linhas, columns=["Sala", "Grupo", "Melhor do grupo", "Situação", "Indicou"])
    if not quadro.empty:
        quadro["_s"] = quadro["Sala"].map(chave_ordenacao_texto)
        quadro["_g"] = quadro["Grupo"].map(chave_ordenacao_texto)
        quadro = quadro.sort_values(["_s", "_g"], kind="mergesort").drop(columns=["_s", "_g"])
    return quadro.reset_index(drop=True), pendentes, decididos


def _passo(col, feito: bool, titulo: str, detalhe: str):
    with col:
        st.markdown(f"{'✅' if feito else '⬜'} **{titulo}**")
        st.caption(detalhe)


def _render_passos(janela: pd.Series | None, quadro: pd.DataFrame, pendentes: list[dict]):
    status = str(janela.get("Status", "")).strip().lower() if janela is not None else ""
    total = len(quadro)
    indicaram = int((quadro["Situação"] == SIT_INDICOU).sum()) if total else 0
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        _passo(c1, janela is not None, "1. Ranking", "Calculado" if janela is not None else "Ainda não calculado")
        if janela is None:
            det2 = "—"
        elif pendentes:
            det2 = f"{len(pendentes)} grupo(s) para resolver"
        else:
            det2 = "Todos os grupos têm o melhor definido"
        _passo(c2, janela is not None and not pendentes, "2. Melhor de cada grupo", det2)
        if status == STATUS_ABERTA:
            det3 = f"Aberta de {janela.get('Data_Inicio')} a {janela.get('Data_Fim')}"
        elif status == STATUS_FECHADA:
            det3 = "Encerrada"
        else:
            det3 = "Ainda não aberta"
        _passo(c3, status in {STATUS_ABERTA, STATUS_FECHADA}, "3. Indicação aberta", det3)
        _passo(c4, total > 0 and indicaram == total, "4. Indicações", f"{indicaram} de {total} grupo(s)" if total else "—")


def _calcular(usuario: dict, id_disc: str, id_ciclo: str, nome_ciclo: str, rotulo: str, key: str, tipo: str):
    if not st.button(rotulo, type=tipo, key=key):
        return
    with st.spinner("Calculando o ranking… pode levar alguns minutos."):
        ranking = calcular_ranking_ciclo(id_disc, id_ciclo)
        if ranking.empty:
            st.error("Nenhum aluno com grupo encontrado para ranquear.")
            return
        id_j = criar_janela_rascunho(
            id_disc, id_ciclo, nome_ciclo, usuario.get("email", ""), usuario.get("nome", ""), ranking
        )
    registrar_log(
        usuario.get("email", ""),
        usuario.get("nome", ""),
        f"Gerou ranking indicação grupo janela={id_j} ciclo={id_ciclo}",
    )
    st.session_state.pop(f"ind_grp_rodada_{id_disc}_{id_ciclo}", None)
    st.rerun()


def _render_acao(usuario: dict, janela: pd.Series, pendentes: list[dict]):
    id_j = str(janela.get("ID_Janela", "")).strip()
    status = str(janela.get("Status", "")).strip().lower()

    if status == STATUS_ABERTA:
        fim = pd.to_datetime(janela.get("Data_Fim"), dayfirst=True, errors="coerce")
        if pd.notna(fim) and fim.date() < date.today():
            st.warning(f"O prazo terminou em {janela.get('Data_Fim')}. Encerre a indicação quando quiser.")
        else:
            st.info(
                f"Indicação aberta de {janela.get('Data_Inicio')} a {janela.get('Data_Fim')}. "
                "O melhor de cada grupo vê o convite no app."
            )
        if st.button("Encerrar indicação", key=f"ind_grp_fechar_{id_j}"):
            erro = fechar_janela(id_j)
            if erro:
                st.error(erro)
            else:
                registrar_log(usuario.get("email", ""), usuario.get("nome", ""), f"Fechou janela indicação grupo {id_j}")
                st.rerun()
        return

    titulo = "Reabrir a indicação" if status == STATUS_FECHADA else "Abrir a indicação para os alunos"
    st.markdown(f"**{titulo}**")
    if pendentes:
        st.caption(
            f"{len(pendentes)} grupo(s) ainda sem o melhor definido. Dá para abrir assim mesmo: "
            "esses grupos recebem o convite quando a escolha for feita acima."
        )
    c1, c2, c3 = st.columns([1, 1, 1], vertical_alignment="bottom")
    with c1:
        di = st.date_input("De", value=date.today(), format="DD/MM/YYYY", key=f"ind_grp_di_{id_j}")
    with c2:
        dfim = st.date_input("Até", value=date.today() + timedelta(days=2), format="DD/MM/YYYY", key=f"ind_grp_df_{id_j}")
    with c3:
        if st.button(titulo.split(" para")[0], type="primary", key=f"ind_grp_abrir_{id_j}", width="stretch"):
            erro = abrir_janela(id_j, di.strftime("%d/%m/%Y"), dfim.strftime("%d/%m/%Y"))
            if erro:
                st.error(erro)
            else:
                registrar_log(usuario.get("email", ""), usuario.get("nome", ""), f"Abriu janela indicação grupo {id_j}")
                st.rerun()


def _escolha_empate(id_j: str, p: dict, atuais: list[str]):
    opcoes = {}
    for _, r in p["empatados"].iterrows():
        nota = _num(r.get("Nota_Ciclo"))
        nota_txt = "sem nota" if nota is None else f"nota {nota:.1f}"
        opcoes[
            f"{str(r['Nome_Aluno']).strip()} ({nota_txt} · dailies {_num(r.get('Pct_Dailies')) or 0:.0f}% "
            f"· aulas {_num(r.get('Pct_Aulas')) or 0:.0f}%)"
        ] = str(r["Email_Aluno"]).strip().lower()
    chave = f"{id_j}_{p['sala']}_{p['grupo']}"
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    with c1:
        escolha = st.multiselect(
            f"Sala {p['sala']} · Grupo {p['grupo']}",
            list(opcoes.keys()),
            default=[lab for lab, em in opcoes.items() if em in atuais],
            key=f"ind_grp_emp_{chave}",
            placeholder="Marque um ou mais",
        )
    with c2:
        mudou = sorted(opcoes[e] for e in escolha) != sorted(atuais)
        if st.button("Confirmar", key=f"ind_grp_emp_ok_{chave}", width="stretch", disabled=not escolha or not mudou):
            erro = marcar_desempate_coord(id_j, [opcoes[e] for e in escolha])
            if erro:
                st.error(erro)
            else:
                st.rerun()


def _render_pendentes(id_j: str, pendentes: list[dict], decididos: list[dict]):
    if not pendentes and not decididos:
        return
    if pendentes:
        st.markdown("**Definir o melhor do grupo**")
        st.caption(
            "Empate: alunos iguais em nota do ciclo, % de dailies e % de aulas. "
            "Sem nota: o ciclo ainda não tem nota lançada para o grupo. "
            "Marque um ou mais: cada aluno marcado indica um colega."
        )
        for p in pendentes:
            _escolha_empate(id_j, p, [])
    if decididos:
        with st.expander(f"Empates já decididos ({len(decididos)}): marcar outro empatado ou trocar"):
            st.caption(
                "Pode marcar mais de um empatado: cada um indica um colega. "
                "Quem já confirmou a indicação não pode ser desmarcado."
            )
            for p in decididos:
                _escolha_empate(id_j, p, p["atuais"])


def _render_quadro(quadro: pd.DataFrame, id_j: str):
    if quadro.empty:
        return
    filtros = {
        "Todos": None,
        "Aguardando": {SIT_AGUARDANDO, SIT_PRONTO, SIT_NAO_INDICOU},
        "Para resolver": {SIT_EMPATE, SIT_SEM_NOTA},
        "Indicaram": {SIT_INDICOU},
    }
    filtro = st.segmented_control(
        "Mostrar", list(filtros.keys()), default="Todos", key=f"ind_grp_filtro_{id_j}", label_visibility="collapsed"
    )
    alvo = filtros.get(filtro or "Todos")
    mostrar = quadro if alvo is None else quadro[quadro["Situação"].isin(alvo)]
    if mostrar.empty:
        st.caption("Nenhum grupo nesta situação.")
        return
    st.dataframe(mostrar, width="stretch", hide_index=True)


def _opcoes_exclusao(id_disc: str) -> dict[str, str]:
    alunos = ler_aba("Entrancia_Turma")
    if alunos.empty:
        return {}
    alunos = alunos[alunos["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disc)].copy()
    alunos["Email_Limpo"] = alunos["Email_Pessoal"].astype(str).str.strip().str.lower()
    alunos = alunos.drop_duplicates("Email_Limpo")
    alunos = alunos.sort_values("Nome_Completo", key=lambda s: s.map(chave_ordenacao_texto), kind="mergesort")
    return {
        f"{str(r.get('Nome_Completo', '')).strip()} <{r['Email_Limpo']}>": r["Email_Limpo"]
        for _, r in alunos.iterrows()
        if r["Email_Limpo"]
    }


def _render_avancado(
    usuario: dict,
    id_disc: str,
    id_ciclo: str,
    nome_ciclo: str,
    janela: pd.Series,
    rodadas_ciclo: pd.DataFrame,
    rank: pd.DataFrame,
    tem_indicacoes: bool,
):
    id_j = str(janela.get("ID_Janela", "")).strip()
    with st.expander("Opções avançadas"):
        st.markdown("**Excluir alunos da lista de escolha**")
        st.caption("Ex.: desistentes que ainda aparecem na turma. Eles não podem ser indicados.")
        opcoes = _opcoes_exclusao(id_disc)
        atuais = {
            e.strip().lower() for e in str(janela.get("Emails_Excluidos", "")).replace(";", ",").split(",") if e.strip()
        }
        sel = st.multiselect(
            "Alunos excluídos",
            list(opcoes.keys()),
            default=[lab for lab, em in opcoes.items() if em in atuais],
            key=f"ind_grp_exc_{id_j}",
            label_visibility="collapsed",
        )
        if st.button("Salvar exclusões", key=f"ind_grp_exc_save_{id_j}"):
            atualizar_excluidos(id_j, [opcoes[s] for s in sel])
            st.success("Exclusões salvas.")
            st.rerun()

        st.divider()
        st.markdown("**Ranking completo do ciclo**")
        r = recalcular_posicoes_exibicao(rank)
        r = r.assign(
            _s=r["Sala"].map(lambda x: chave_ordenacao_texto(str(x))),
            _g=r["Grupo"].map(lambda x: chave_ordenacao_texto(str(x))),
            _p=pd.to_numeric(r["Posicao_Grupo"], errors="coerce").fillna(999),
        ).sort_values(["_s", "_g", "_p"], kind="mergesort")
        tabela = pd.DataFrame(
            {
                "Sala": r["Sala"],
                "Grupo": r["Grupo"],
                "Posição": pd.to_numeric(r["Posicao_Grupo"], errors="coerce"),
                "Aluno": r["Nome_Aluno"],
                "Nota do ciclo": pd.to_numeric(r["Nota_Ciclo"], errors="coerce"),
                "% dailies": pd.to_numeric(r["Pct_Dailies"], errors="coerce"),
                "% aulas": pd.to_numeric(r["Pct_Aulas"], errors="coerce"),
                "Melhor": r["Vencedor"].astype(str).str.strip().str.lower().isin(_SIM).map({True: "Sim", False: ""}),
            }
        )
        st.dataframe(
            tabela,
            width="stretch",
            hide_index=True,
            column_config={
                "Posição": st.column_config.NumberColumn(format="%d"),
                "Nota do ciclo": st.column_config.NumberColumn(format="%.1f"),
                "% dailies": st.column_config.NumberColumn(format="%.0f%%"),
                "% aulas": st.column_config.NumberColumn(format="%.0f%%"),
            },
        )
        st.caption("Critérios: nota do ciclo, depois % de dailies, depois % de aulas. Empates repetem a posição.")

        st.divider()
        st.markdown("**Recalcular o ranking**")
        st.caption(
            "Use se notas ou presenças mudaram depois do cálculo. Cria uma nova rodada do ciclo, "
            "que passa a ser a exibida; a indicação precisa ser aberta de novo."
        )
        ok = True
        if tem_indicacoes:
            st.warning("Esta rodada já tem indicações confirmadas. Elas ficam na rodada antiga e não passam para a nova.")
            ok = st.checkbox("Entendi, quero recalcular mesmo assim", key=f"ind_grp_recalc_ok_{id_j}")
        if ok:
            _calcular(usuario, id_disc, id_ciclo, nome_ciclo, "Recalcular ranking", f"ind_grp_recalc_{id_j}", "secondary")

        if len(rodadas_ciclo) > 1:
            st.divider()
            st.markdown("**Rodadas anteriores deste ciclo**")
            rotulos = {}
            for _, rr in rodadas_ciclo.iterrows():
                criado = rr["_criado"].strftime("%d/%m/%Y %H:%M") if pd.notna(rr["_criado"]) else "?"
                rotulos[f"Calculada em {criado} · {str(rr.get('Status', '')).strip()}"] = str(rr["ID_Janela"]).strip()
            chave = f"ind_grp_rodada_{id_disc}_{id_ciclo}"
            atual = st.session_state.get(chave, str(rodadas_ciclo.iloc[0]["ID_Janela"]).strip())
            labels = list(rotulos.keys())
            idx = next((i for i, lab in enumerate(labels) if rotulos[lab] == atual), 0)
            escolha = st.selectbox("Rodada exibida", labels, index=idx, key=f"{chave}_sel")
            if rotulos[escolha] != atual:
                st.session_state[chave] = rotulos[escolha]
                st.rerun()


def render(usuario: dict):
    st.header("Indicação de grupos")
    st.caption(
        "Ao fim do ciclo, o melhor aluno de cada grupo indica um colega da turma para o próximo "
        "agrupamento (em empate, a coordenação pode escolher mais de um). O indicado não vê quem o escolheu."
    )

    df_disc = ler_aba("Disciplinas")
    lista = df_disc["Nome_Disciplina"].unique().tolist()
    c1, c2 = st.columns(2)
    with c1:
        disc = st.selectbox("Disciplina:", lista, index=indice_disciplina_ativa(df_disc, lista), key="ind_grp_disc")
    id_disc = id_disciplina_por_nome(df_disc, disc)
    rodadas = _rodadas(id_disc)
    with c2:
        escolhido = _escolher_ciclo(id_disc, rodadas)
    if escolhido is None:
        return
    id_ciclo, nome_ciclo = escolhido

    rodadas_ciclo = (
        rodadas[rodadas["ID_Ciclo"].astype(str).str.strip() == id_ciclo].reset_index(drop=True)
        if not rodadas.empty
        else rodadas
    )
    if rodadas_ciclo.empty:
        _render_passos(None, pd.DataFrame(columns=["Situação"]), [])
        st.info(
            f"Primeiro passo: calcular o ranking de **{nome_ciclo}**. O sistema usa a nota do ciclo e, "
            "no empate, % de dailies e % de aulas para achar o melhor de cada grupo."
        )
        _calcular(usuario, id_disc, id_ciclo, nome_ciclo, "Calcular ranking", f"ind_grp_calc_{id_ciclo}", "primary")
        return

    sel = st.session_state.get(f"ind_grp_rodada_{id_disc}_{id_ciclo}")
    match = rodadas_ciclo[rodadas_ciclo["ID_Janela"].astype(str).str.strip() == sel] if sel else pd.DataFrame()
    janela = match.iloc[0] if not match.empty else rodadas_ciclo.iloc[0]
    id_j = str(janela["ID_Janela"]).strip()

    rank = carregar_ranking(id_j)
    if rank.empty:
        st.warning("O ranking desta rodada está vazio. Recalcule em Opções avançadas.")
        _calcular(usuario, id_disc, id_ciclo, nome_ciclo, "Recalcular ranking", f"ind_grp_recalc_vazio_{id_j}", "primary")
        return
    ind = carregar_indicacoes(id_j)
    status = str(janela.get("Status", "")).strip().lower()
    quadro, pendentes, decididos = _montar_quadro(rank, ind, status)

    _render_passos(janela, quadro, pendentes)
    if id_j != str(rodadas_ciclo.iloc[0]["ID_Janela"]).strip():
        st.caption("Exibindo uma rodada anterior deste ciclo (troque em Opções avançadas).")
    _render_pendentes(id_j, pendentes, decididos)
    _render_acao(usuario, janela, pendentes)

    st.subheader("Grupos")
    _render_quadro(quadro, id_j)

    tem_ind = (not ind.empty) and (ind["Status"].astype(str).str.strip().str.lower() == "confirmado").any()
    _render_avancado(usuario, id_disc, id_ciclo, nome_ciclo, janela, rodadas_ciclo, rank, bool(tem_ind))
