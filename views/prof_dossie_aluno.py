"""Dossiê do aluno por ciclo — apoio às conversas de feedback da orientação."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.anotacoes_daily import AVISO_USO_INTERNO
from domain.cadastros import sala_padrao_orientador
from domain.ciclos import indice_ciclo_academico_padrao, ordenar_ciclos
from domain.dossie_aluno import (
    CITA_NAO,
    Dossie,
    carregar_contexto,
    dossie_em_texto,
    fmt_num,
    fmt_pct,
    montar_dossie,
    resumo_alunos,
)
from domain.encontro_presencial import ciclos_visiveis_avaliacao
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.ordenacao import ordenar_grupos_lista
from utils.preferencias_sala import selectbox_sala

_VALIDADE_DADOS_S = 600
_TZ = ZoneInfo("America/Sao_Paulo")


def _tabela_resumo(resumo: pd.DataFrame) -> pd.DataFrame:
    def _fracao(a, b):
        return f"{int(a)} de {int(b)}" if b else "—"

    return pd.DataFrame(
        {
            "Aluno": resumo["Nome"],
            "Grupo": resumo["Grupo"],
            "Aulas": resumo["Pct_Aulas"].map(fmt_pct),
            "Dailies": resumo["Pct_Dailies"].map(fmt_pct),
            "Pares recebida (0–5)": resumo["Pares_Media"].map(fmt_num),
            "Pares feita": [_fracao(a, b) for a, b in zip(resumo["Pares_Feitos"], resumo["Pares_Esperados"])],
            "Orientador": resumo["Orientador"].map(fmt_num),
            "Citado nas dailies": [
                _fracao(a, b) for a, b in zip(resumo["Dailies_Citado"], resumo["Dailies_Anotadas"])
            ],
            "Atividades (média)": resumo["Atividades_Media"].map(fmt_num),
            "Sem nota": resumo["Atividades_Sem_Nota"].astype(int),
        }
    )


def _delta(valor, media, sufixo: str = "") -> str | None:
    if valor is None or media is None:
        return None
    diff = float(valor) - float(media)
    return f"{'+' if diff >= 0 else ''}{fmt_num(diff)}{sufixo} vs grupo"


def _render_metricas(d: Dossie):
    ind, grp = d.indicadores, d.medias_grupo
    oficial = (d.banca or {}).get("oficial")
    cols = st.columns(6)
    cols[0].metric("Aulas", fmt_pct(ind["Pct_Aulas"]), _delta(ind["Pct_Aulas"], grp.get("Pct_Aulas"), " p.p."))
    cols[1].metric("Dailies", fmt_pct(ind["Pct_Dailies"]), _delta(ind["Pct_Dailies"], grp.get("Pct_Dailies"), " p.p."))
    cols[2].metric(
        "Pares recebida",
        fmt_num(ind["Pares_Media"]),
        _delta(ind["Pares_Media"], grp.get("Pares_Media")),
        help="Média das notas dos colegas (0 a 5).",
    )
    cols[3].metric("Orientador", fmt_num(ind["Orientador"]), _delta(ind["Orientador"], grp.get("Orientador")))
    cols[4].metric(
        "Banca (grupo)",
        fmt_num(oficial["nota_total"]) if oficial else "—",
        help="Nota do grupo na apresentação — é a mesma para todos os integrantes.",
    )
    cols[5].metric(
        "Atividades",
        fmt_num(ind["Atividades_Media"]),
        help="Média das atividades individuais com prazo no ciclo (0 a 100).",
    )
    st.caption("A comparação “vs grupo” usa a média dos demais integrantes do grupo.")


def _render_sinais(d: Dossie):
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Destaques**")
        if d.destaques:
            st.success("\n".join(f"- {s}" for s in d.destaques))
        else:
            st.caption("Nenhum destaque automático.")
    with c2:
        st.markdown("**Pontos de atenção**")
        if d.atencao:
            st.warning("\n".join(f"- {s}" for s in d.atencao))
        else:
            st.caption("Nenhum ponto de atenção automático.")
    st.caption(
        "Sinais gerados por regras simples (presença, comparação com o grupo, citações). "
        "São pistas para a conversa, não conclusões."
    )


def _render_dailies(d: Dossie):
    st.caption(
        "As anotações são feitas por grupo. O sistema procura o nome e o sobrenome do aluno no texto "
        "(apelidos não são reconhecidos). **Ambígua** = só o primeiro nome aparece e ele se repete "
        "no grupo — confira o trecho."
    )
    if d.linha_dailies.empty:
        st.info("Sem dailies apuradas nem anotações do grupo neste ciclo.")
        return
    st.dataframe(
        d.linha_dailies,
        width="stretch",
        hide_index=True,
        column_config={
            "Data": st.column_config.TextColumn("Data", width="small"),
            "Trecho": st.column_config.TextColumn("Trecho que cita o aluno", width="large"),
            "Anotação completa": st.column_config.TextColumn("Anotação completa", width="large"),
        },
    )


def _render_pares(d: Dossie):
    ind = d.indicadores
    st.markdown(f"**Avaliação feita pelo aluno:** {d.situacao_pares} {d.liberacao_pares}".strip())
    if ind["Pares_N"]:
        st.markdown(
            f"**Recebida:** média {fmt_num(ind['Pares_Media'])}/5 de {ind['Pares_N']} colega(s) "
            f"— média do grupo {fmt_num(d.medias_grupo.get('Pares_Media'))}, "
            f"turma {fmt_num(d.medias_turma.get('Pares_Media'))}."
        )
    st.markdown("**Feedbacks recebidos dos colegas**")
    if d.comentarios_pares:
        for c in d.comentarios_pares:
            st.info(f"“{c}”")
    else:
        st.caption("Nenhum feedback em texto neste ciclo.")
    if d.comentarios_ocultos:
        st.caption(f"{d.comentarios_ocultos} comentário(s) ocultado(s) na moderação não aparecem aqui.")


def _render_banca(d: Dossie):
    if not d.banca:
        st.info("A banca ainda não avaliou o grupo neste ciclo.")
        return
    oficial = d.banca.get("oficial")
    if oficial:
        origem = "conferência da coordenação" if oficial.get("origem") == "conferencia" else (
            f"média de {oficial.get('n_avaliadores', 0)} avaliador(es)"
        )
        st.markdown(
            f"**Nota do grupo:** total {fmt_num(oficial['nota_total'])} — apresentação "
            f"{fmt_num(oficial['nota_apresentacao'])}, conteúdo {fmt_num(oficial['nota_conteudo'])} ({origem})."
        )
    st.markdown("**Comentários ao grupo**")
    if d.banca.get("comentarios"):
        for c in d.banca["comentarios"]:
            marca = f"**Cita {d.primeiro_nome}** · " if c["citacao"] != CITA_NAO else ""
            st.info(f"{marca}“{c['texto']}” — {c['avaliador']}")
    else:
        st.caption("Sem comentários da banca.")


def _render_atividades(d: Dossie):
    if d.atividades.empty:
        st.info("Nenhuma atividade individual com prazo dentro do ciclo.")
        return
    visao = d.atividades.copy()
    visao["Nota"] = visao["Nota"].map(lambda v: "Sem nota" if pd.isna(v) else fmt_num(v))
    visao["Editada"] = visao["Editada"].map({True: "Sim", False: ""})
    st.dataframe(visao, width="stretch", hide_index=True)
    st.caption("“Sem nota” pode ser entrega pendente ou correção ainda não importada do Canvas.")


def _render_presenca(d: Dossie):
    for rotulo, p in (("Aulas", d.aulas), ("Dailies", d.dailies)):
        if not p["total"]:
            st.markdown(f"**{rotulo}:** sem registros no período.")
            continue
        faltas = ", ".join(p["datas_falta"]) or "nenhuma"
        seq = f" Maior sequência de faltas: {p['seq_max']}." if p["seq_max"] >= 2 else ""
        st.markdown(
            f"**{rotulo}:** {p['presencas']} de {p['total']} ({fmt_pct(p['pct'])}). Faltas: {faltas}.{seq}"
        )


def _render_dossie(ctx, d: Dossie):
    st.subheader(d.nome)
    st.caption(f"Grupo {d.grupo}" + (f" · Sala {d.sala}" if d.sala else "") + f" · {ctx.nome_ciclo}")
    _render_metricas(d)
    _render_sinais(d)

    abas = st.tabs(["Dailies", "Pares", "Banca", "Atividades", "Presença", "Texto para copiar"])
    with abas[0]:
        _render_dailies(d)
    with abas[1]:
        _render_pares(d)
    with abas[2]:
        _render_banca(d)
    with abas[3]:
        _render_atividades(d)
    with abas[4]:
        _render_presenca(d)
    with abas[5]:
        texto = dossie_em_texto(ctx, d)
        st.caption(
            "Resumo em texto com só o primeiro nome, sem e-mails e com os feedbacks dos colegas anônimos. "
            "Use o ícone de copiar no canto do quadro."
        )
        st.code(texto, language=None, wrap_lines=True)
        st.download_button(
            "Baixar .txt",
            texto.encode("utf-8"),
            file_name=f"dossie_{d.primeiro_nome}_{ctx.nome_ciclo}.txt".replace(" ", "_"),
            mime="text/plain",
        )

    if d.lacunas:
        with st.expander(f"Dados ausentes ({len(d.lacunas)})"):
            for item in d.lacunas:
                st.markdown(f"- {item}")


def render(usuario: dict):
    st.header("Dossiê do aluno")
    st.caption(
        "Reúne por ciclo presença, avaliações de pares, nota do orientador, banca, anotações das dailies "
        "e atividades, para apoiar a conversa de feedback. " + AVISO_USO_INTERNO
    )

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox(
        "Disciplina:", lista_disc, index=indice_disciplina_ativa(df_disc, lista_disc), key="dossie_disc"
    )
    id_disc = id_disciplina_por_nome(df_disc, disc_sel)

    df_ciclos = ler_aba("Ciclos")
    ciclos = df_ciclos[df_ciclos["ID_Disciplina"].astype(str).str.strip() == id_disc]
    ciclos = ordenar_ciclos(ciclos_visiveis_avaliacao(ciclos, id_disc))
    if ciclos.empty:
        st.warning("Nenhum ciclo cadastrado para esta disciplina.")
        return
    nomes = ciclos["Nome_Ciclo"].astype(str).tolist()

    c1, c2, c3 = st.columns(3)
    ciclo_sel = c1.selectbox(
        "Ciclo:", nomes, index=indice_ciclo_academico_padrao(ciclos, nomes), key=f"dossie_ciclo_{id_disc}"
    )
    ciclo = ciclos[ciclos["Nome_Ciclo"].astype(str) == ciclo_sel].iloc[0]

    chave = f"_dossie_ctx|{id_disc}|{str(ciclo.get('ID_Ciclo', '')).strip()}"
    guardado = st.session_state.get(chave)
    if guardado is None or time.time() - guardado[0] > _VALIDADE_DADOS_S:
        with st.spinner("Reunindo os dados do ciclo…"):
            ctx = carregar_contexto(id_disc, ciclo, usuario=usuario)
            guardado = (time.time(), ctx, resumo_alunos(ctx))
        st.session_state[chave] = guardado
    carregado_em, ctx, resumo = guardado
    a1, a2 = st.columns([4, 1], vertical_alignment="center")
    a1.caption(
        f"Dados carregados às {datetime.fromtimestamp(carregado_em, _TZ):%H:%M}. "
        "Lançamentos feitos depois disso aparecem ao atualizar."
    )
    if a2.button("Atualizar dados", width="stretch", key="dossie_atualizar"):
        st.session_state.pop(chave, None)
        st.rerun()
    if resumo.empty:
        st.info("Nenhum aluno com grupo nesta disciplina.")
        return

    salas = [s for s in resumo["Sala"].unique().tolist() if s]
    sala_pref = sala_padrao_orientador(usuario, id_disc)
    if "dossie_sala" not in st.session_state and sala_pref in salas:
        st.session_state["dossie_sala"] = sala_pref
    with c2:
        sala = selectbox_sala("Sala:", salas, key="dossie_sala", usuario=usuario) if salas else "Todas"
    base = resumo if sala == "Todas" else resumo[resumo["Sala"] == sala]
    grupos = ordenar_grupos_lista(base["Grupo"].unique().tolist())
    grupo = c3.selectbox("Grupo:", ["Todos"] + grupos, key=f"dossie_grupo_{sala}")
    if grupo != "Todos":
        base = base[base["Grupo"] == grupo]

    st.markdown(f"#### Visão geral — {ciclo_sel}")
    st.dataframe(_tabela_resumo(base), width="stretch", hide_index=True)

    st.divider()
    opcoes = base["Email"].tolist()
    nomes_alunos = dict(zip(base["Email"], base["Nome"]))
    email = st.selectbox(
        "Aluno:",
        opcoes,
        format_func=lambda e: nomes_alunos.get(e, e),
        key=f"dossie_aluno_{sala}_{grupo}",
    )
    dossie = montar_dossie(ctx, resumo, email) if email else None
    if dossie is None:
        st.info("Selecione um aluno.")
        return
    _render_dossie(ctx, dossie)
