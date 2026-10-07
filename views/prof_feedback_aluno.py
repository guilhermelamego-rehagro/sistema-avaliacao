"""Tela docente: preparar, revisar e publicar o feedback do ciclo para os alunos."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.cadastros import sala_padrao_orientador
from domain.ciclos import hoje_normalizado, indice_ciclo_academico_padrao, ordenar_ciclos
from domain.encontro_presencial import ciclos_visiveis_avaliacao
from domain.dossie_aluno import combinar_resumos, titulo_ciclos
from domain.feedback_aluno import CICLO_MIN_ACUMULADO, feedback_ativo_alunos, montar_feedback
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.ordenacao import chave_ordenacao_texto, ordenar_grupos_lista
from views.aluno_feedback import render_painel
from views.prof_dossie_aluno import _carregar_ciclos

_TZ = ZoneInfo("America/Sao_Paulo")


def _fmt_data(valor) -> str:
    ts = pd.to_datetime(valor, utc=True, errors="coerce")
    return "" if pd.isna(ts) else ts.tz_convert(_TZ).strftime("%d/%m %H:%M")


def _avisar(texto: str) -> None:
    st.session_state["_fb_prof_aviso"] = texto


def _linha_base(email: str, ctx, usuario: dict) -> dict:
    return {
        "email": email,
        "id_disciplina": ctx.id_disciplina,
        "id_ciclo": ctx.id_ciclo,
        "nome_ciclo": ctx.nome_ciclo,
        "autor_email": str(usuario.get("email", "")).lower(),
        "autor_nome": str(usuario.get("nome", "")),
    }


def _multiselect(label: str, opcoes: list, *, key: str, placeholder: str, format_func=str) -> list:
    """Vazio = sem filtro. Descarta da seleção o que deixou de existir (ex.: grupo de sala desmarcada)."""
    if key in st.session_state:
        st.session_state[key] = [o for o in st.session_state[key] if o in opcoes]
    return st.multiselect(label, opcoes, key=key, placeholder=placeholder, format_func=format_func)


def _filtrar_salas_grupos(resumo: pd.DataFrame, usuario: dict, id_disc: str, col_sala, col_grupo) -> tuple[pd.DataFrame, str]:
    salas = ordenar_grupos_lista([s for s in resumo["Sala"].unique().tolist() if s])
    sala_pref = sala_padrao_orientador(usuario, id_disc)
    if "fb_salas" not in st.session_state and sala_pref in salas:
        st.session_state["fb_salas"] = [sala_pref]
    with col_sala:
        salas_sel = _multiselect("Salas:", salas, key="fb_salas", placeholder="Todas")
    base = resumo[resumo["Sala"].isin(salas_sel)] if salas_sel else resumo

    pares = base[["Sala", "Grupo"]].drop_duplicates()
    pares = pares[pares["Grupo"].astype(str).str.strip() != ""]
    ordem_salas = {s: i for i, s in enumerate(salas)}

    def chave_grupo(par):
        g = str(par[1]).strip()
        return (ordem_salas.get(par[0], len(salas)), 0 if g.isdigit() else 1, int(g) if g.isdigit() else 0, chave_ordenacao_texto(g))

    pares = sorted(zip(pares["Sala"], pares["Grupo"]), key=chave_grupo)
    nomes = [str(g) for _, g in pares]
    repetidos = {g for g in nomes if nomes.count(g) > 1}
    opcoes = [f"{s}\t{g}" for s, g in pares]

    def rotulo(valor: str) -> str:
        s, g = valor.split("\t", 1)
        nome = f"Grupo {g}" if g.isdigit() else g
        return f"{nome} ({s})" if g in repetidos else nome

    with col_grupo:
        grupos_sel = _multiselect("Grupos:", opcoes, key="fb_grupos", placeholder="Todos", format_func=rotulo)
    if grupos_sel:
        base = base[(base["Sala"].astype(str) + "\t" + base["Grupo"].astype(str)).isin(grupos_sel)]
    filtro = "|".join(salas_sel) + "#" + "|".join(grupos_sel)
    return base.reset_index(drop=True), filtro


def render(usuario: dict) -> None:
    from data.supabase_feedback import despublicar, listar_do_ciclo, publicar, salvar_rascunhos

    st.header("Feedback aos alunos")
    st.caption(
        "Monta o feedback do ciclo de cada aluno com faixas (Atenção, Bom, Ótimo) e frases automáticas. "
        "Revise, acrescente uma mensagem se quiser e publique: o aluno vê em **Meu feedback**. "
        "A indicação de conversa 1x1 é só da equipe docente."
    )
    if not feedback_ativo_alunos():
        st.warning(
            "**Fase de validação:** os alunos ainda não veem o feedback. O que for publicado agora ficará "
            "visível para eles quando o painel for liberado; antes disso, atualize ou despublique o que precisar."
        )
    if aviso := st.session_state.pop("_fb_prof_aviso", None):
        st.success(aviso)

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    c1, c2, c3, c4 = st.columns(4)
    disc_sel = c1.selectbox("Disciplina:", lista_disc, index=indice_disciplina_ativa(df_disc, lista_disc), key="fb_disc")
    id_disc = id_disciplina_por_nome(df_disc, disc_sel)
    df_ciclos = ler_aba("Ciclos")
    ciclos = ordenar_ciclos(
        ciclos_visiveis_avaliacao(df_ciclos[df_ciclos["ID_Disciplina"].astype(str).str.strip() == id_disc], id_disc)
    )
    if ciclos.empty:
        st.warning("Nenhum ciclo cadastrado para esta disciplina.")
        return
    nomes = ciclos["Nome_Ciclo"].astype(str).tolist()
    nome_ciclo = c2.selectbox("Ciclo:", nomes, index=indice_ciclo_academico_padrao(ciclos, nomes), key=f"fb_ciclo_{id_disc}")
    posicao = nomes.index(nome_ciclo)
    com_acumulado = posicao + 1 >= CICLO_MIN_ACUMULADO
    ciclos_carga = ciclos.iloc[: posicao + 1] if com_acumulado else ciclos.iloc[[posicao]]
    ctxs, resumos, carregado_em, chaves = _carregar_ciclos(id_disc, ciclos_carga, usuario)
    ctx, resumo = ctxs[-1], resumos[-1]
    nomes_acumulado = nomes[: posicao + 1] if com_acumulado else []
    acumulado = combinar_resumos(resumos).set_index("Email") if com_acumulado else None
    if resumo.empty:
        st.info("Nenhum aluno com grupo nesta disciplina.")
        return

    base, filtro = _filtrar_salas_grupos(resumo, usuario, id_disc, c3, c4)
    if base.empty:
        st.info("Nenhum aluno nos filtros escolhidos.")
        return

    a1, a2 = st.columns([4, 1], vertical_alignment="center")
    a1.caption(f"Dados carregados às {datetime.fromtimestamp(carregado_em, _TZ):%H:%M}.")
    if a2.button("Atualizar dados", width="stretch", key="fb_atualizar"):
        for chave in chaves:
            st.session_state.pop(chave, None)
        st.rerun()

    try:
        existentes = {r["email"]: r for r in listar_do_ciclo(ctx.id_ciclo)}
    except Exception:
        st.warning("O feedback está indisponível: confira se a tabela feedback_ciclo foi criada no Supabase.")
        return

    pares_encerrada = ctx.pares_fim is not None and ctx.pares_fim < hoje_normalizado()
    feedbacks = {
        row["Email"]: montar_feedback(
            row,
            ctx.nome_ciclo,
            pares_encerrada,
            acumulado.loc[row["Email"]] if acumulado is not None and row["Email"] in acumulado.index else None,
            nomes_acumulado,
        )
        for _, row in base.iterrows()
    }
    if com_acumulado:
        st.caption(f"Os indicadores mostram o {ctx.nome_ciclo} e o acumulado dos {titulo_ciclos(nomes_acumulado)}.")

    linhas = []
    for _, row in base.iterrows():
        email = row["Email"]
        reg = existentes.get(email, {})
        fb = feedbacks[email]
        publicado = _fmt_data(reg.get("publicado_em"))
        linhas.append(
            {
                "Selecionar": not publicado,
                "Email": email,
                "Nome": row["Nome"],
                "Grupo": row["Grupo"],
                "Pontos de atenção": fb.atencoes,
                "Sugestão de 1x1": fb.sugestao_1x1,
                "1x1": bool(reg.get("um_a_um")),
                "Mensagem": "Sim" if str(reg.get("mensagem") or "").strip() else "",
                "Status": f"Publicado {publicado}" if publicado else ("Rascunho" if reg else "Não publicado"),
            }
        )
    tabela = pd.DataFrame(linhas)

    n = len(tabela)
    n_pub = int(tabela["Status"].str.startswith("Publicado").sum())
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Alunos", n)
    m2.metric("Publicados", f"{n_pub} de {n}")
    m3.metric("Sugestão de 1x1", int((tabela["Sugestão de 1x1"] != "").sum()))
    m4.metric("1x1 marcados", int(tabela["1x1"].sum()))

    chave_sel = f"fb_sel|{ctx.id_ciclo}|{filtro}"
    modo, versao = st.session_state.get(chave_sel, ("pendentes", 0))
    if modo == "todos":
        tabela["Selecionar"] = True
    elif modo == "nenhum":
        tabela["Selecionar"] = False

    s1, s2, s3, _ = st.columns([1, 1, 1, 3])
    for col, (rotulo, novo) in zip(
        (s1, s2, s3), (("Selecionar todos", "todos"), ("Só não publicados", "pendentes"), ("Limpar seleção", "nenhum"))
    ):
        if col.button(rotulo, key=f"fb_modo_{novo}", width="stretch"):
            st.session_state[chave_sel] = (novo, versao + 1)
            st.rerun()

    editada = st.data_editor(
        tabela,
        hide_index=True,
        width="stretch",
        height=min(38 * (n + 1), 460),
        key=f"fb_tabela|{ctx.id_ciclo}|{filtro}|{versao}",
        column_order=[c for c in tabela.columns if c != "Email"],
        disabled=[c for c in tabela.columns if c != "Selecionar"],
        column_config={
            "Selecionar": st.column_config.CheckboxColumn(
                "Selecionar", help="Alunos que entram na publicação em lote. Desmarque quem precisa de mais revisão."
            ),
            "1x1": st.column_config.CheckboxColumn("1x1", help="Marcado pela equipe docente; o aluno não vê."),
            "Sugestão de 1x1": st.column_config.TextColumn(
                help="Presença nas aulas em atenção (no ciclo ou no acumulado) ou 2 ou mais indicadores em atenção."
            ),
        },
    )
    selecionados = editada.loc[editada["Selecionar"], "Email"].tolist()
    sel_publicados = [e for e in selecionados if existentes.get(e, {}).get("publicado_em")]

    st.caption(
        f"**{len(selecionados)} de {n} alunos selecionados.** A publicação usa os dados de agora e mantém as "
        "mensagens e marcações de 1x1 salvas; quem já estava publicado tem o feedback atualizado."
    )
    confirmar = st.checkbox("Revisei o feedback dos alunos selecionados", key=f"fb_conf_{ctx.id_ciclo}_{filtro}")
    b1, b2, _ = st.columns([1, 1, 2])
    if b1.button(
        f"Publicar selecionados ({len(selecionados)})",
        type="primary",
        disabled=not (confirmar and selecionados),
        width="stretch",
    ):
        publicar(
            [
                {
                    **_linha_base(e, ctx, usuario),
                    "mensagem": str(existentes.get(e, {}).get("mensagem") or ""),
                    "um_a_um": bool(existentes.get(e, {}).get("um_a_um")),
                    "conteudo": feedbacks[e].conteudo,
                }
                for e in selecionados
            ]
        )
        st.session_state[chave_sel] = ("pendentes", versao + 1)
        _avisar(f"Feedback do {ctx.nome_ciclo} publicado para {len(selecionados)} alunos.")
        st.rerun()
    if b2.button(
        f"Despublicar selecionados ({len(sel_publicados)})",
        disabled=not (confirmar and sel_publicados),
        width="stretch",
    ):
        despublicar(ctx.id_ciclo, sel_publicados)
        st.session_state[chave_sel] = ("pendentes", versao + 1)
        _avisar(f"Feedback do {ctx.nome_ciclo} despublicado para {len(sel_publicados)} alunos.")
        st.rerun()

    st.subheader("Revisar um aluno")
    ordem = sorted(zip(base["Email"], base["Nome"]), key=lambda par: chave_ordenacao_texto(par[1]))
    nome_por_email = dict(ordem)
    email = st.selectbox(
        "Aluno:", list(nome_por_email), format_func=nome_por_email.get, key=f"fb_aluno_{ctx.id_ciclo}_{filtro}"
    )
    escolhido = nome_por_email[email]
    reg = existentes.get(email, {})
    fb = feedbacks[email]

    e1, e2 = st.columns([3, 1], vertical_alignment="top")
    mensagem = e1.text_area(
        "Mensagem para o aluno (opcional)",
        value=str(reg.get("mensagem") or ""),
        key=f"fb_msg_{ctx.id_ciclo}_{email}",
        height=120,
        placeholder="Ex.: Parabéns pela evolução nas dailies! Para o próximo ciclo, foque em…",
    )
    with e2:
        if fb.sugestao_1x1:
            st.caption(f"Sugestão de 1x1: **{fb.sugestao_1x1}**")
        um_a_um = st.checkbox("Marcar 1x1", value=bool(reg.get("um_a_um")), key=f"fb_1x1_{ctx.id_ciclo}_{email}")
        if st.button("Salvar rascunho", key="fb_salvar_um", width="stretch"):
            salvar_rascunhos([{**_linha_base(email, ctx, usuario), "mensagem": mensagem, "um_a_um": um_a_um}])
            _avisar(f"Rascunho de {escolhido} salvo.")
            st.rerun()
        publicado_aluno = bool(reg.get("publicado_em"))
        if st.button(
            "Atualizar publicação" if publicado_aluno else "Publicar só este aluno",
            key="fb_publicar_um",
            width="stretch",
            type="primary",
        ):
            publicar(
                [{**_linha_base(email, ctx, usuario), "mensagem": mensagem, "um_a_um": um_a_um, "conteudo": fb.conteudo}]
            )
            st.session_state[chave_sel] = ("pendentes", versao + 1)
            _avisar(f"Feedback de {escolhido} publicado.")
            st.rerun()

    with st.container(border=True):
        st.caption("Como o aluno vai ver")
        render_painel(fb.conteudo, mensagem, str(usuario.get("nome", "")), chave="fb_prev", atalhos=False)
