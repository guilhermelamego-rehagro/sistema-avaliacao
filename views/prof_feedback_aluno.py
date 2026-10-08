"""Tela docente: preparar, revisar e publicar o feedback do ciclo para os alunos."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain import boletim_calculado as boletim
from domain.avaliacoes import formatar_nota_grid, parse_nota_orientador, salvar_avaliacao_orientador
from domain.cadastros import sala_padrao_orientador
from domain.ciclos import hoje_normalizado, indice_ciclo_academico_padrao, ordenar_ciclos
from domain.encontro_presencial import ciclos_visiveis_avaliacao
from domain.dossie_aluno import combinar_resumos, fmt_num, titulo_ciclos
from domain.feedback_aluno import CICLO_MIN_ACUMULADO, feedback_ativo_alunos, montar_feedback
from domain.situacao_final import NOTA_APROVACAO, NOTA_RECUPERACAO
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.logs import registrar_log
from utils.ordenacao import chave_ordenacao_texto, ordenar_grupos_lista
from views.aluno_feedback import render_painel
from views.prof_dossie_aluno import _carregar_ciclos
from views.status_boletim import render_status

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


def _chave_boletins(id_disc: str) -> str:
    """Mesma chave da Situação final do Dossiê (boletins calculados na sessão quando faltam na tabela)."""
    return f"_dossie_final|{id_disc}"


def _nota_ate_agora(resultado) -> tuple[float, float] | None:
    """(pontos obtidos, pontos já apurados) somando só os componentes que já têm nota."""
    comp = resultado.componentes
    if comp.empty:
        return None
    apurados = comp[comp["Nota"].notna()]
    peso = float(apurados["Peso"].sum())
    if peso <= 0:
        return None
    return float(apurados["Pontos"].sum()), peso


def _icone_aproveitamento(pct: float) -> str:
    return "🟢" if pct >= NOTA_APROVACAO else ("🟡" if pct >= NOTA_RECUPERACAO else "🔴")


def _fmt_nota_orientador(valor) -> str:
    return "" if valor is None or pd.isna(valor) else formatar_nota_grid(valor)


def _salvar_notas_orientador(notas: dict[str, float], base: pd.DataFrame, ctx, chave_ctx: str, usuario: dict) -> None:
    """Grava as notas do ciclo e atualiza os dados já carregados na sessão, sem reler tudo."""
    alunos = base.set_index("Email")
    for email, nota in notas.items():
        salvar_avaliacao_orientador(
            id_ciclo=ctx.id_ciclo,
            nome_ciclo=ctx.nome_ciclo,
            id_disciplina=ctx.id_disciplina,
            email_aluno=email,
            nome_aluno=str(alunos.at[email, "Nome"]),
            grupo=str(alunos.at[email, "Grupo"]),
            nota=nota,
            email_orientador=usuario["email"],
        )
    registrar_log(
        usuario["email"], usuario["nome"], f"Avaliação orientador pelo feedback - {ctx.nome_ciclo} ({len(notas)} notas)"
    )
    boletins = st.session_state.get(_chave_boletins(ctx.id_disciplina))
    if boletins is not None:
        for email in notas:
            boletins[1].pop(email, None)
    boletim.recalcular(ctx.id_disciplina, notas, autor=str(usuario.get("email", "")).lower())
    guardado = st.session_state.get(chave_ctx)
    if guardado is not None:
        horario, ctx_salvo, resumo = guardado
        ctx_salvo.notas_orientador.update(notas)
        resumo = resumo.copy()
        resumo["Orientador"] = [notas.get(e, v) for e, v in zip(resumo["Email"], resumo["Orientador"])]
        st.session_state[chave_ctx] = (horario, ctx_salvo, resumo)


def _aviso_notas(n: int, nome_ciclo: str, republicar: int) -> str:
    texto = f"{n} nota(s) do orientador do {nome_ciclo} salva(s)."
    if republicar:
        texto += f" {republicar} aluno(s) já tinham feedback publicado: atualize a publicação para o aluno ver a nota nova."
    return texto


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
    chave_bol = _chave_boletins(ctx.id_disciplina)
    if a2.button("Atualizar dados", width="stretch", key="fb_atualizar"):
        for chave in [*chaves, chave_bol, boletim.chave_sessao(id_disc)]:
            st.session_state.pop(chave, None)
        st.rerun()

    resultados: dict = {}
    parciais: dict[str, tuple[float, float]] = {}
    try:
        salvos, concluido = boletim.carregar_salvos(id_disc)
    except boletim.BoletimIndisponivel:
        st.caption(
            "Nota até agora indisponível: confira se as tabelas de scripts/sql/10_boletim_calculado.sql "
            "foram criadas no Supabase."
        )
    else:
        if not salvos and boletim.andamento(id_disc) is None:
            boletim.recalcular(id_disc, autor=str(usuario.get("email", "")).lower())
        render_status(id_disc, usuario, concluido, chave="fb_boletim")
        resultados = {e: salvos[e] for e in base["Email"] if e in salvos}
        parciais = {e: p for e, r in resultados.items() if (p := _nota_ate_agora(r)) is not None}

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
        st.caption(f"Os indicadores mostram o {ctx.nome_ciclo} e a disciplina até agora ({titulo_ciclos(nomes_acumulado)}).")

    linhas = []
    for _, row in base.iterrows():
        email = row["Email"]
        reg = existentes.get(email, {})
        fb = feedbacks[email]
        publicado = _fmt_data(reg.get("publicado_em"))
        parcial = {}
        if parciais:
            pontos, peso = parciais.get(email, (None, None))
            pct = None if pontos is None else round(pontos / peso * 100)
            parcial = {
                "Nota até agora": "" if pct is None else f"{_icone_aproveitamento(pct)} {fmt_num(pontos)} de {fmt_num(peso, 0)}",
                "Aproveitamento": pct,
            }
        linhas.append(
            {
                "Selecionar": not publicado,
                "Email": email,
                "Nome": row["Nome"],
                "Grupo": row["Grupo"],
                "Nota orientador": _fmt_nota_orientador(row.get("Orientador")),
                **parcial,
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
    metricas = st.columns(5 if parciais else 4)
    metricas[0].metric("Alunos", n)
    metricas[1].metric("Publicados", f"{n_pub} de {n}")
    metricas[2].metric("Sugestão de 1x1", int((tabela["Sugestão de 1x1"] != "").sum()))
    metricas[3].metric("1x1 marcados", int(tabela["1x1"].sum()))
    if parciais:
        metricas[4].metric(
            f"Abaixo de {fmt_num(NOTA_APROVACAO, 0)}% até agora",
            int((tabela["Aproveitamento"] < NOTA_APROVACAO).sum()),
            help="Alunos cujo aproveitamento nos componentes já apurados está abaixo do ritmo de aprovação.",
        )

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
        disabled=[c for c in tabela.columns if c not in ("Selecionar", "Nota orientador")],
        column_config={
            "Selecionar": st.column_config.CheckboxColumn(
                "Selecionar", help="Alunos que entram na publicação em lote. Desmarque quem precisa de mais revisão."
            ),
            "Nota orientador": st.column_config.TextColumn(
                "Nota orientador ✏️",
                help=f"Avaliação do orientador no {ctx.nome_ciclo}, de 0 a 10 (ex.: 8 ou 8,5). "
                "Edite e clique em Salvar notas do orientador; vale sempre a nota mais recente.",
                width="small",
            ),
            "Nota até agora": st.column_config.TextColumn(
                help="Pontos obtidos dos pontos já apurados (só componentes com nota; mesmas regras de Minhas "
                "notas). Ex.: 42 de 60 = aproveitamento de 70%. "
                f"🟢 a partir de {fmt_num(NOTA_APROVACAO, 0)}% (ritmo de aprovação), 🟡 de "
                f"{fmt_num(NOTA_RECUPERACAO, 0)}% a {fmt_num(NOTA_APROVACAO, 0)}%, 🔴 abaixo de "
                f"{fmt_num(NOTA_RECUPERACAO, 0)}%. Só a equipe vê.",
                width="small",
            ),
            "Aproveitamento": st.column_config.NumberColumn(
                format="%d%%",
                help=f"Pontos obtidos ÷ pontos já apurados. A aprovação pede {fmt_num(NOTA_APROVACAO, 0)} no final.",
                width="small",
            ),
            "1x1": st.column_config.CheckboxColumn("1x1", help="Marcado pela equipe docente; o aluno não vê."),
            "Sugestão de 1x1": st.column_config.TextColumn(
                help="Presença nas aulas em atenção (no ciclo ou no acumulado) ou 2 ou mais indicadores em atenção."
            ),
        },
    )
    nota_antes = dict(zip(tabela["Email"], tabela["Nota orientador"]))
    mudou = {
        e: str(v or "").strip()
        for e, v in zip(editada["Email"], editada["Nota orientador"])
        if str(v or "").strip() != nota_antes.get(e, "")
    }
    if mudou:
        nome_de = dict(zip(base["Email"], base["Nome"]))
        validas = {e: parse_nota_orientador(v) for e, v in mudou.items() if parse_nota_orientador(v) is not None}
        invalidas = [nome_de[e] for e, v in mudou.items() if v and parse_nota_orientador(v) is None]
        vazias = [nome_de[e] for e, v in mudou.items() if not v]
        n1, n2 = st.columns([3, 1], vertical_alignment="center")
        if invalidas:
            n1.error(f"Nota inválida (use de 0 a 10, ex.: 8 ou 8,5): {', '.join(invalidas)}.")
        elif vazias:
            n1.warning(f"Nota apagada não é removida ({', '.join(vazias)}): para corrigir, digite a nota certa.")
        else:
            n1.info(f"{len(validas)} nota(s) do orientador alterada(s) na tabela, ainda não salva(s).")
        if n2.button(
            f"Salvar notas do orientador ({len(validas)})",
            type="primary",
            disabled=bool(invalidas) or not validas,
            width="stretch",
            key="fb_salvar_notas_or",
        ):
            _salvar_notas_orientador(validas, base, ctx, chaves[-1], usuario)
            republicar = sum(1 for e in validas if existentes.get(e, {}).get("publicado_em"))
            st.session_state[chave_sel] = (modo, versao + 1)
            _avisar(_aviso_notas(len(validas), ctx.nome_ciclo, republicar))
            st.rerun()

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

    if email in resultados:
        comp = resultados[email].componentes
        sem_nota = ", ".join(comp.loc[comp["Nota"].isna(), "Componente"]) if not comp.empty else ""
        if email in parciais:
            pontos, peso = parciais[email]
            pct = round(pontos / peso * 100)
            texto = (
                f"{_icone_aproveitamento(pct)} **Nota até agora:** {fmt_num(pontos)} dos {fmt_num(peso, 0)} pontos "
                f"já apurados — aproveitamento de **{pct}%** (a aprovação pede {fmt_num(NOTA_APROVACAO, 0)})."
            )
        else:
            texto = "**Nota até agora:** nenhum componente com nota ainda."
        if sem_nota:
            texto += f" Ainda sem nota: {sem_nota}."
        st.markdown(texto + " _Só a equipe vê._")

    nota_atual = _fmt_nota_orientador(base.set_index("Email").at[email, "Orientador"])
    o1, o2, _ = st.columns([1, 1, 2], vertical_alignment="bottom")
    nota_txt = o1.text_input(
        f"Nota do orientador no {ctx.nome_ciclo} (0 a 10)",
        value=nota_atual,
        placeholder="Ex.: 8,5",
        key=f"fb_nota_or_{ctx.id_ciclo}_{email}_{nota_atual}",
    )
    if o2.button(
        "Salvar nota",
        key="fb_salvar_nota_or_um",
        width="stretch",
        disabled=nota_txt.strip().replace(",", ".") == nota_atual,
    ):
        nota = parse_nota_orientador(nota_txt)
        if nota is None:
            st.error("Nota inválida: use de 0 a 10, ex.: 8 ou 8,5.")
        else:
            _salvar_notas_orientador({email: nota}, base, ctx, chaves[-1], usuario)
            st.session_state[chave_sel] = (modo, versao + 1)
            _avisar(_aviso_notas(1, ctx.nome_ciclo, 1 if reg.get("publicado_em") else 0))
            st.rerun()

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
