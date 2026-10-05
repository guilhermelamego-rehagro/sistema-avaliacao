"""Dossiê do aluno por ciclo — apoio às conversas de feedback da orientação."""

from __future__ import annotations

import html
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from data.sheets import ler_aba
from domain.anotacoes_daily import AVISO_USO_INTERNO
from domain.cadastros import sala_padrao_orientador
from domain.ciclos import indice_ciclo_academico_padrao, ordenar_ciclos
from domain.dossie_aluno import (
    CITA_NAO,
    INDICADORES,
    Dossie,
    DossieCiclo,
    carregar_contexto,
    combinar_resumos,
    dossie_em_texto,
    fmt_num,
    fmt_pct,
    montar_dossie,
    prompt_feedback,
    resumo_alunos,
    salas_comparacao_padrao,
    titulo_ciclos,
)
from domain.encontro_presencial import ciclos_visiveis_avaliacao
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.ordenacao import chave_ordenacao_texto, ordenar_grupos_lista
from utils.preferencias_sala import selectbox_sala

_VALIDADE_DADOS_S = 600
_TZ = ZoneInfo("America/Sao_Paulo")
_URL_GEMINI = "https://gemini.google.com/app"
_MODO_UM = "Um ciclo"
_MODO_VARIOS = "Vários ciclos"


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
            "Banca": resumo["Banca"].map(fmt_num),
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
    media_ciclos = " Média dos ciclos selecionados." if d.varios_ciclos else ""
    cols = st.columns(6)
    cols[0].metric("Aulas", fmt_pct(ind["Pct_Aulas"]), _delta(ind["Pct_Aulas"], grp.get("Pct_Aulas"), " p.p."))
    cols[1].metric("Dailies", fmt_pct(ind["Pct_Dailies"]), _delta(ind["Pct_Dailies"], grp.get("Pct_Dailies"), " p.p."))
    cols[2].metric(
        "Pares recebida",
        fmt_num(ind["Pares_Media"]),
        _delta(ind["Pares_Media"], grp.get("Pares_Media")),
        help="Média das notas dos colegas (0 a 5).",
    )
    cols[3].metric(
        "Orientador",
        fmt_num(ind["Orientador"]),
        _delta(ind["Orientador"], grp.get("Orientador")),
        help=("Nota do orientador (0 a 10)." + media_ciclos).strip(),
    )
    cols[4].metric(
        "Banca (grupo)",
        fmt_num(ind["Banca"]),
        help="Nota do grupo na apresentação — é a mesma para todos os integrantes." + media_ciclos,
    )
    cols[5].metric(
        "Atividades",
        fmt_num(ind["Atividades_Media"]),
        help="Média das atividades individuais com prazo no período (0 a 100).",
    )
    st.caption("A comparação “vs grupo” usa a média dos demais integrantes do grupo.")


def _render_comparacao_sala(d: Dossie):
    linhas = []
    for col, rotulo, fmt in INDICADORES:
        est = d.estatisticas.get(col)
        linhas.append(
            {
                "Indicador": rotulo,
                "Aluno": fmt(d.indicadores[col]),
                "Média do grupo": fmt(d.medias_grupo.get(col)),
                "Média": fmt(est["media"]) if est else "—",
                "Q1": fmt(est["q1"]) if est else "—",
                "Mediana": fmt(est["mediana"]) if est else "—",
                "Q3": fmt(est["q3"]) if est else "—",
                "Percentil": fmt_num(est["percentil"], 0) if est and est["percentil"] is not None else "—",
                "Posição": est["posicao"].capitalize() if est and est["posicao"] else "—",
            }
        )
    artigo = "as" if d.referencia_curta == "salas" else "a"
    st.markdown(f"**Comparação com {artigo} {d.referencia}** ({d.n_referencia} alunos)")
    st.dataframe(pd.DataFrame(linhas), width="stretch", hide_index=True)
    st.caption(
        "Q1, mediana e Q3 dividem os alunos de referência em quatro partes iguais (25% abaixo de Q1, 25% acima "
        "de Q3). Percentil = % dos alunos com resultado abaixo do aluno (empates contam pela metade)."
    )


def _render_evolucao(d: Dossie):
    linhas = []
    for c in d.ciclos:
        ind = c.indicadores
        linhas.append(
            {
                "Ciclo": c.nome + (" (entrega final)" if c.final else ""),
                "Período": c.periodo or "—",
                "Aulas": fmt_pct(ind["Pct_Aulas"]),
                "Dailies": fmt_pct(ind["Pct_Dailies"]),
                "Pares recebida": fmt_num(ind["Pares_Media"]),
                "Pares feita": f"{ind['Pares_Feitos']} de {ind['Pares_Esperados']}" if ind["Pares_Esperados"] else "—",
                "Orientador": fmt_num(ind["Orientador"]),
                "Banca": fmt_num(ind["Banca"]),
                "Atividades": fmt_num(ind["Atividades_Media"]),
                "Citado nas dailies": (
                    f"{ind['Dailies_Citado']} de {ind['Dailies_Anotadas']}" if ind["Dailies_Anotadas"] else "—"
                ),
            }
        )
    st.markdown("**Evolução por ciclo**")
    st.dataframe(pd.DataFrame(linhas), width="stretch", hide_index=True)


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


def _render_dailies(c: DossieCiclo, d: Dossie):
    if c.linha_dailies.empty:
        st.info("Sem dailies apuradas nem anotações do grupo neste ciclo.")
        return
    st.dataframe(
        c.linha_dailies,
        width="stretch",
        hide_index=True,
        column_config={
            "Data": st.column_config.TextColumn("Data", width="small"),
            "Trecho": st.column_config.TextColumn("Trecho que cita o aluno", width="large"),
            "Anotação completa": st.column_config.TextColumn("Anotação completa", width="large"),
        },
    )


def _render_pares(c: DossieCiclo, d: Dossie):
    ind = c.indicadores
    st.markdown(f"**Avaliação feita pelo aluno:** {c.situacao_pares} {c.liberacao_pares}".strip())
    if ind["Pares_N"]:
        st.markdown(
            f"**Recebida:** média {fmt_num(ind['Pares_Media'])}/5 de {ind['Pares_N']} colega(s) "
            f"— média do grupo {fmt_num(c.medias_grupo.get('Pares_Media'))}."
        )
    st.markdown("**Feedbacks recebidos dos colegas**")
    if c.comentarios_pares:
        for t in c.comentarios_pares:
            st.info(f"“{t}”")
    else:
        st.caption("Nenhum feedback em texto neste ciclo.")
    if c.comentarios_ocultos:
        st.caption(f"{c.comentarios_ocultos} comentário(s) ocultado(s) na moderação não aparecem aqui.")


def _render_banca(c: DossieCiclo, d: Dossie):
    if not c.banca:
        st.info("A banca ainda não avaliou o grupo neste ciclo.")
        return
    oficial = c.banca.get("oficial")
    if oficial:
        origem = "conferência da coordenação" if oficial.get("origem") == "conferencia" else (
            f"média de {oficial.get('n_avaliadores', 0)} avaliador(es)"
        )
        st.markdown(
            f"**Nota do grupo:** total {fmt_num(oficial['nota_total'])} — apresentação "
            f"{fmt_num(oficial['nota_apresentacao'])}, conteúdo {fmt_num(oficial['nota_conteudo'])} ({origem})."
        )
    st.markdown("**Comentários ao grupo**")
    if c.banca.get("comentarios"):
        for com in c.banca["comentarios"]:
            marca = f"**Cita {d.primeiro_nome}** · " if com["citacao"] != CITA_NAO else ""
            st.info(f"{marca}“{com['texto']}” — {com['avaliador']}")
    else:
        st.caption("Sem comentários da banca.")


def _render_atividades(c: DossieCiclo, d: Dossie):
    if c.atividades.empty:
        st.info("Nenhuma atividade individual com prazo dentro do ciclo.")
        return
    visao = c.atividades.copy()
    visao["Nota"] = visao["Nota"].map(lambda v: "Sem nota" if pd.isna(v) else fmt_num(v))
    visao["Editada"] = visao["Editada"].map({True: "Sim", False: ""})
    st.dataframe(visao, width="stretch", hide_index=True)


def _render_presenca(c: DossieCiclo, d: Dossie):
    for rotulo, p in (("Aulas", c.aulas), ("Dailies", c.dailies)):
        if not p["total"]:
            st.markdown(f"**{rotulo}:** sem registros no período.")
            continue
        faltas = ", ".join(p["datas_falta"]) or "nenhuma"
        seq = f" Maior sequência de faltas: {p['seq_max']}." if p["seq_max"] >= 2 else ""
        st.markdown(
            f"**{rotulo}:** {p['presencas']} de {p['total']} ({fmt_pct(p['pct'])}). Faltas: {faltas}.{seq}"
        )


def _por_ciclo(d: Dossie, render_ciclo):
    for c in d.ciclos:
        if d.varios_ciclos:
            periodo = f" · {c.periodo}" if c.periodo else ""
            st.markdown(f"##### {c.nome}{periodo}")
        render_ciclo(c, d)


def _botao_copiar_e_abrir(texto: str, rotulo: str, url: str):
    dados = json.dumps(texto).replace("</", "<\\/")
    components.html(
        f"""
<style>
  body {{ margin: 0; font-family: "Source Sans Pro", sans-serif; }}
  button {{ background: #004D28; color: #fff; border: 0; border-radius: 8px; padding: 9px 18px;
           font-size: 15px; cursor: pointer; }}
  button:hover {{ background: #003a1e; }}
  span {{ margin-left: 12px; font-size: 14px; color: #004D28; }}
</style>
<button id="b">{html.escape(rotulo)}</button><span id="s"></span>
<script>
  const texto = {dados};
  const aviso = (m) => {{ document.getElementById("s").textContent = m; }};
  const reserva = () => {{
    const t = document.createElement("textarea");
    t.value = texto; document.body.appendChild(t); t.select();
    const ok = document.execCommand("copy"); t.remove(); return ok;
  }};
  document.getElementById("b").addEventListener("click", async () => {{
    let ok = false;
    try {{ await navigator.clipboard.writeText(texto); ok = true; }} catch (e) {{ ok = reserva(); }}
    window.open({json.dumps(url)}, "_blank", "noopener");
    aviso(ok ? "Copiado! No Gemini, cole com Ctrl+V e envie."
             : "Não consegui copiar — abra “Ver o prompt completo” e use o ícone de copiar.");
  }});
</script>
""",
        height=48,
    )


def _render_prompt_gemini(d: Dossie):
    st.markdown("**Rascunho de feedback com o Gemini**")
    st.caption(
        "O botão copia um prompt pronto (instruções + dossiê) e abre o Gemini numa nova aba. "
        "Entre com a sua conta do Rehagro, cole com Ctrl+V e envie. Revise o rascunho antes de usar: "
        "a IA pode errar ou exagerar, e a conversa é sua."
    )
    if d.ciclos_finais:
        st.caption(
            f"Inclui a entrega final ({titulo_ciclos(d.ciclos_finais)}): o prompt pede orientações para os "
            "próximos projetos, em vez de sugestões para o próximo ciclo."
        )
    prompt = prompt_feedback(d)
    _botao_copiar_e_abrir(prompt, "Copiar prompt e abrir o Gemini", _URL_GEMINI)
    with st.expander("Ver o prompt completo"):
        st.code(prompt, language=None, wrap_lines=True)


def _render_dossie(d: Dossie):
    st.subheader(d.nome)
    st.caption(f"Grupo {d.grupo}" + (f" · Sala {d.sala}" if d.sala else "") + f" · {d.titulo}")
    _render_metricas(d)
    _render_comparacao_sala(d)
    if d.varios_ciclos:
        _render_evolucao(d)
    _render_sinais(d)

    abas = st.tabs(["Dailies", "Pares", "Banca", "Atividades", "Presença", "Feedback com IA"])
    with abas[0]:
        st.caption(
            "As anotações são feitas por grupo. O sistema procura o nome e o sobrenome do aluno no texto "
            "(apelidos não são reconhecidos). **Ambígua** = só o primeiro nome aparece e ele se repete "
            "no grupo — confira o trecho."
        )
        _por_ciclo(d, _render_dailies)
    with abas[1]:
        _por_ciclo(d, _render_pares)
    with abas[2]:
        _por_ciclo(d, _render_banca)
    with abas[3]:
        _por_ciclo(d, _render_atividades)
        st.caption("“Sem nota” pode ser entrega pendente ou correção ainda não importada do Canvas.")
    with abas[4]:
        _por_ciclo(d, _render_presenca)
    with abas[5]:
        _render_prompt_gemini(d)
        st.divider()
        texto = dossie_em_texto(d)
        st.markdown("**Só o resumo (sem instruções para a IA)**")
        st.caption(
            "Resumo em texto com só o primeiro nome, sem e-mails e com os feedbacks dos colegas anônimos. "
            "Use o ícone de copiar no canto do quadro."
        )
        st.code(texto, language=None, wrap_lines=True)
        st.download_button(
            "Baixar .txt",
            texto.encode("utf-8"),
            file_name=f"dossie_{d.primeiro_nome}_{d.titulo}.txt".replace(" ", "_").replace(",", ""),
            mime="text/plain",
        )

    if d.lacunas:
        with st.expander(f"Dados ausentes ({len(d.lacunas)})"):
            for item in d.lacunas:
                st.markdown(f"- {item}")


def _carregar_ciclos(id_disc: str, ciclos_sel: pd.DataFrame, usuario: dict) -> tuple[list, list, float, list[str]]:
    """Contexto e resumo de cada ciclo, guardados na sessão por alguns minutos."""
    ctxs, resumos, horarios, chaves = [], [], [], []
    for _, ciclo in ciclos_sel.iterrows():
        chave = f"_dossie_ctx|{id_disc}|{str(ciclo.get('ID_Ciclo', '')).strip()}"
        guardado = st.session_state.get(chave)
        if guardado is None or time.time() - guardado[0] > _VALIDADE_DADOS_S:
            with st.spinner(f"Reunindo os dados do {ciclo.get('Nome_Ciclo', 'ciclo')}…"):
                ctx = carregar_contexto(id_disc, ciclo, usuario=usuario)
                guardado = (time.time(), ctx, resumo_alunos(ctx))
            st.session_state[chave] = guardado
        horarios.append(guardado[0])
        ctxs.append(guardado[1])
        resumos.append(guardado[2])
        chaves.append(chave)
    return ctxs, resumos, min(horarios), chaves


def render(usuario: dict):
    st.header("Dossiê do aluno")
    st.caption(
        "Reúne por ciclo presença, avaliações de pares, nota do orientador, banca, anotações das dailies "
        "e atividades, para apoiar a conversa de feedback. " + AVISO_USO_INTERNO
    )

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    d1, d2 = st.columns([2, 1], vertical_alignment="bottom")
    disc_sel = d1.selectbox(
        "Disciplina:", lista_disc, index=indice_disciplina_ativa(df_disc, lista_disc), key="dossie_disc"
    )
    id_disc = id_disciplina_por_nome(df_disc, disc_sel)
    modo = d2.radio("Feedback de:", [_MODO_UM, _MODO_VARIOS], horizontal=True, key="dossie_modo")

    df_ciclos = ler_aba("Ciclos")
    ciclos = df_ciclos[df_ciclos["ID_Disciplina"].astype(str).str.strip() == id_disc]
    ciclos = ordenar_ciclos(ciclos_visiveis_avaliacao(ciclos, id_disc))
    if ciclos.empty:
        st.warning("Nenhum ciclo cadastrado para esta disciplina.")
        return
    nomes = ciclos["Nome_Ciclo"].astype(str).tolist()
    idx_padrao = indice_ciclo_academico_padrao(ciclos, nomes)

    c1, c2, c3 = st.columns(3)
    if modo == _MODO_VARIOS:
        nomes_sel = c1.multiselect(
            "Ciclos da conversa:", nomes, default=nomes[: idx_padrao + 1], key=f"dossie_ciclos_{id_disc}"
        )
        if not nomes_sel:
            st.info("Marque ao menos um ciclo.")
            return
        nomes_sel = [n for n in nomes if n in nomes_sel]
    else:
        nomes_sel = [c1.selectbox("Ciclo:", nomes, index=idx_padrao, key=f"dossie_ciclo_{id_disc}")]
    ciclos_sel = ciclos[ciclos["Nome_Ciclo"].astype(str).isin(nomes_sel)]
    titulo = titulo_ciclos(nomes_sel)

    ctxs, resumos, carregado_em, chaves = _carregar_ciclos(id_disc, ciclos_sel, usuario)
    resumo = combinar_resumos(resumos)
    a1, a2 = st.columns([4, 1], vertical_alignment="center")
    a1.caption(
        f"Dados carregados às {datetime.fromtimestamp(carregado_em, _TZ):%H:%M}. "
        "Lançamentos feitos depois disso aparecem ao atualizar."
    )
    if a2.button("Atualizar dados", width="stretch", key="dossie_atualizar"):
        for chave in chaves:
            st.session_state.pop(chave, None)
        st.rerun()
    if resumo.empty:
        st.info("Nenhum aluno com grupo nesta disciplina.")
        return

    salas = ordenar_grupos_lista([s for s in resumo["Sala"].unique().tolist() if s])
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

    chave_ref = f"dossie_salas_ref_{id_disc}"
    if chave_ref in st.session_state:
        st.session_state[chave_ref] = [s for s in st.session_state[chave_ref] if s in salas]
    else:
        st.session_state[chave_ref] = [s for s in salas if s in salas_comparacao_padrao(resumo)]
    salas_ref = st.multiselect(
        "Comparar com as salas:",
        salas,
        key=chave_ref,
        help="Média, quartis e percentil do dossiê usam os alunos destas salas. Já vêm marcadas as salas "
        "de alunos ativos; sem nenhuma marcada, a comparação é com a sala do aluno.",
    )

    st.markdown(f"#### Visão geral — {titulo}")
    st.dataframe(_tabela_resumo(base), width="stretch", hide_index=True)

    st.divider()
    nomes_alunos = dict(zip(base["Email"], base["Nome"]))
    opcoes = sorted(nomes_alunos, key=lambda e: chave_ordenacao_texto(nomes_alunos[e]))
    email = st.selectbox(
        "Aluno:",
        opcoes,
        format_func=lambda e: nomes_alunos.get(e, e),
        key=f"dossie_aluno_{sala}_{grupo}",
    )
    dossie = montar_dossie(ctxs, resumos, email, salas_ref) if email else None
    if dossie is None:
        st.info("Selecione um aluno.")
        return
    _render_dossie(dossie)
