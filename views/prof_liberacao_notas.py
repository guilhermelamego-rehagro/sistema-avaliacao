"""Liberação da nota final parcial para os alunos + painel de boletins."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from data import supabase_relatorio_secretaria as repo_relatorio
from data.sheets import ler_aba
from domain.liberacao_notas import notas_finais_liberadas, salvar_liberacao_notas
from domain.notas import bytes_excel_boletins, montar_painel_boletins_disciplina
from domain.relatorio_secretaria import diferencas, fmt_data_hora, momento, montar_relatorio, publicar_relatorio
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.logs import registrar_log
from utils.ordenacao import chave_ordenacao_texto, ordenar_grupos_lista

_CACHE_VERSAO = "v5"  # painel com Email (chave do relatório da secretaria)
_TZ = ZoneInfo("America/Sao_Paulo")


def _chave_cache(id_disc: str, sufixo: str) -> str:
    return f"lib_notas_boletim_{_CACHE_VERSAO}_{sufixo}_{id_disc}"


def _opcoes_unicas(serie: pd.Series) -> list[str]:
    vals = sorted(
        {
            str(v).strip()
            for v in serie.dropna().tolist()
            if str(v).strip() and str(v).strip() not in {"—", "–"}
        },
        key=chave_ordenacao_texto,
    )
    return vals


def _carregar_ou_usar_cache(id_disc: str, *, forcar: bool) -> tuple[pd.DataFrame, list[str], str]:
    """Retorna (df, legendas, horario_br). Calcula só na 1ª abertura ou se forçar."""
    chave_df = _chave_cache(id_disc, "df")
    chave_leg = _chave_cache(id_disc, "leg")
    chave_em = _chave_cache(id_disc, "em")

    if forcar or chave_df not in st.session_state:
        df = montar_painel_boletins_disciplina(id_disc)
        legendas = list(df.attrs.get("legendas_colunas") or [])
        agora = datetime.now(_TZ)
        st.session_state[chave_df] = df
        st.session_state[chave_leg] = legendas
        st.session_state[chave_em] = agora.strftime("%d/%m/%Y %H:%M")
        st.session_state[_chave_cache(id_disc, "momento")] = agora

    df = st.session_state[chave_df]
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()
    legendas = list(st.session_state.get(chave_leg) or [])
    horario = str(st.session_state.get(chave_em) or "—")
    return df, legendas, horario


def _aviso_tabela_ausente() -> str:
    from auth.supabase_auth import ambiente_app

    texto = "O relatório da secretaria está indisponível no momento."
    if ambiente_app() != "producao":
        texto += " Confira se `scripts/sql/09_relatorio_secretaria.sql` já foi executado no Supabase."
    return texto


def _publicar_para_secretaria(id_disc: str, disc_sel: str, df_painel: pd.DataFrame, usuario: dict) -> str:
    """Publica o retrato e devolve a mensagem para o aviso da próxima execução."""
    try:
        n = publicar_relatorio(id_disc, disc_sel, df_painel, usuario)
    except repo_relatorio.RelatorioIndisponivel:
        return f"⚠️ {_aviso_tabela_ausente()}"
    if n:
        registrar_log(usuario["email"], usuario["nome"], f"Publicou relatório da secretaria — {disc_sel} ({n} alterações)")
        return f"Relatório da secretaria publicado ({n} registro(s) no histórico)."
    return "Relatório da secretaria já estava igual ao cálculo atual."


def _render_relatorio_secretaria(
    id_disc: str, disc_sel: str, df_painel: pd.DataFrame, horario: str, liberado: bool, usuario: dict
) -> None:
    st.markdown("##### Relatório da secretaria")
    if not liberado:
        st.caption(
            "A secretaria vê o relatório de notas finais (totais dos ciclos, atividades, dailies, presença, "
            "nota final e situação, sem orientador, pares e grupo) só depois que a nota final é liberada. "
            "Ao liberar, o relatório é publicado com o cálculo desta tela."
        )
        return
    try:
        anterior = repo_relatorio.ler(id_disc)
    except repo_relatorio.RelatorioIndisponivel:
        st.warning(_aviso_tabela_ausente())
        return
    if anterior is None:
        r1, r2 = st.columns([3, 1], vertical_alignment="center")
        r1.warning("A nota final está liberada, mas o relatório da secretaria ainda não foi publicado.")
        if r2.button("Publicar para a secretaria", type="primary", width="stretch", key=f"lib_rel_pub_{id_disc}"):
            with st.spinner("Publicando…"):
                st.session_state["_lib_notas_aviso"] = _publicar_para_secretaria(id_disc, disc_sel, df_painel, usuario)
            st.rerun()
        return

    publicado = f"publicado em {fmt_data_hora(anterior['gerado_em'])} por {anterior.get('gerado_por_nome') or '—'}"
    mudancas = diferencas(anterior, montar_relatorio(df_painel))
    if not mudancas:
        st.success(f"Relatório da secretaria igual ao cálculo das {horario} ({publicado}).")
        return

    calculado = st.session_state.get(_chave_cache(id_disc, "momento"))
    gerado = momento(anterior["gerado_em"])
    if calculado is not None and gerado is not None and calculado < gerado:
        st.info(
            f"O relatório da secretaria ({publicado}) é mais recente que o cálculo desta tela ({horario}). "
            "Clique em **Recalcular notas** para comparar com os dados de agora."
        )
        return

    st.warning(
        f"O cálculo das {horario} tem **{len(mudancas)} alteração(ões)** em relação ao relatório da secretaria "
        f"({publicado}). Confira e publique a atualização: a secretaria vê cada mudança no histórico."
    )
    tabela = pd.DataFrame(mudancas).rename(
        columns={"nome": "Aluno", "turma": "Turma", "campo": "Campo", "antes": "Antes", "depois": "Depois"}
    )
    st.dataframe(
        tabela[["Aluno", "Turma", "Campo", "Antes", "Depois"]],
        hide_index=True,
        width="stretch",
        height=min(38 + 35 * len(tabela), 320),
    )
    if st.button(
        f"Atualizar relatório da secretaria ({len(mudancas)})", type="primary", key=f"lib_rel_atualizar_{id_disc}"
    ):
        with st.spinner("Publicando…"):
            st.session_state["_lib_notas_aviso"] = _publicar_para_secretaria(id_disc, disc_sel, df_painel, usuario)
        st.rerun()


def render(usuario: dict):
    st.header("Liberação de notas finais")
    st.caption(
        "Enquanto a nota final **não estiver liberada**, o aluno vê apenas o detalhamento "
        "por componente em **Minhas notas (boletim)**."
    )

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox(
        "Disciplina:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
        key="lib_notas_disc",
    )
    id_disc = id_disciplina_por_nome(df_disc, disc_sel)

    if aviso := st.session_state.pop("_lib_notas_aviso", None):
        (st.warning if aviso.startswith("⚠️") else st.success)(aviso)

    liberado = notas_finais_liberadas(id_disc)
    if liberado:
        st.success("Nota final **liberada** para os alunos desta disciplina.")
    else:
        st.info("Nota final **oculta** — alunos veem só o grid por componente.")

    c1, c2 = st.columns(2)
    if c1.button("Liberar nota final", type="primary", width="stretch"):
        salvar_liberacao_notas(id_disc, True, usuario["email"], usuario["nome"])
        registrar_log(usuario["email"], usuario["nome"], f"Liberou nota final — {disc_sel}")
        with st.spinner("Publicando o relatório da secretaria…"):
            df_lib, _, _ = _carregar_ou_usar_cache(id_disc, forcar=False)
            msg = _publicar_para_secretaria(id_disc, disc_sel, df_lib, usuario) if not df_lib.empty else ""
        st.session_state["_lib_notas_aviso"] = f"Nota final liberada! {msg}".strip()
        st.rerun()

    if c2.button("Ocultar nota final", width="stretch"):
        salvar_liberacao_notas(id_disc, False, usuario["email"], usuario["nome"])
        registrar_log(usuario["email"], usuario["nome"], f"Ocultou nota final — {disc_sel}")
        st.success("Nota final ocultada para os alunos.")
        st.rerun()

    st.divider()
    st.subheader("Boletins da disciplina")
    st.caption(
        "Presença **realizada** (aulas + encontro presencial, quando houver). "
        "Status: presença < 75% → reprovado por presença; "
        "com presença ≥ 75%: nota < 40 reprovado · 40–69,9 recuperação · ≥ 70 aprovado. "
        "Cabeçalhos curtos: **C1 Ori/Par/Grp/Tot** = ciclo 1 (orientador, pares, grupo, total); "
        "**EF** = entrega final; **Pres.%** = presença; **Final** = nota final."
    )

    col_calc, col_info = st.columns([1, 2])
    forcar = col_calc.button(
        "Recalcular notas",
        width="stretch",
        key=f"lib_notas_recalc_{id_disc}",
        help="Recalcula boletins e frequências desta disciplina (pode demorar).",
    )

    precisa_calcular = forcar or _chave_cache(id_disc, "df") not in st.session_state
    try:
        if precisa_calcular:
            with st.spinner("Calculando boletins e frequências…"):
                df_painel, legendas, horario = _carregar_ou_usar_cache(id_disc, forcar=True)
        else:
            df_painel, legendas, horario = _carregar_ou_usar_cache(id_disc, forcar=False)
    except Exception as exc:
        st.error(f"Não foi possível montar o painel de boletins: {exc}")
        return

    col_info.caption(f"Calculado em **{horario}**. Filtros não recalculam — use o botão acima.")

    if df_painel.empty:
        st.warning("Nenhum aluno encontrado nesta disciplina.")
        return

    _render_relatorio_secretaria(id_disc, disc_sel, df_painel, horario, liberado, usuario)
    st.divider()

    base = df_painel.drop(columns=["Email"], errors="ignore")
    # Exibição: sala/turma vazias aparecem como — sem poluir a exportação.
    for col_txt in ("Turma", "Sala"):
        if col_txt in base.columns:
            base[col_txt] = base[col_txt].replace({"": "—", None: "—"})
    turmas = _opcoes_unicas(base["Turma"]) if "Turma" in base.columns else []
    salas = _opcoes_unicas(base["Sala"]) if "Sala" in base.columns else []
    grupos = (
        ordenar_grupos_lista(_opcoes_unicas(base["Grupo"]))
        if "Grupo" in base.columns
        else []
    )

    f1, f2, f3, f4 = st.columns([2, 1.2, 1.2, 1.2])
    busca_aluno = f1.text_input(
        "Filtrar por aluno:",
        key=f"lib_notas_busca_{id_disc}",
        placeholder="Nome (parcial)",
    ).strip()
    turmas_sel = f2.multiselect("Turma:", turmas, key=f"lib_notas_turma_{id_disc}")
    salas_sel = f3.multiselect("Sala:", salas, key=f"lib_notas_sala_{id_disc}")
    grupos_sel = f4.multiselect("Grupo:", grupos, key=f"lib_notas_grupo_{id_disc}")

    vista = base
    if busca_aluno and "Nome" in vista.columns:
        vista = vista[
            vista["Nome"].astype(str).str.contains(busca_aluno, case=False, na=False)
        ]
    if turmas_sel and "Turma" in vista.columns:
        vista = vista[vista["Turma"].isin(turmas_sel)]
    if salas_sel and "Sala" in vista.columns:
        vista = vista[vista["Sala"].isin(salas_sel)]
    if grupos_sel and "Grupo" in vista.columns:
        vista = vista[vista["Grupo"].isin(grupos_sel)]

    if vista.empty:
        st.warning("Nenhum aluno com os filtros atuais.")
        return

    st.caption(f"{len(vista)} aluno(s) no filtro (de {len(base)} na disciplina).")

    if "Status" in vista.columns:
        contagem = vista["Status"].value_counts()
        cols_m = st.columns(min(len(contagem), 4) or 1)
        for i, (status, qtd) in enumerate(contagem.items()):
            cols_m[i % len(cols_m)].metric(str(status), int(qtd))

    if legendas:
        with st.expander("Legenda dos cabeçalhos", expanded=False):
            st.caption(" · ".join(legendas))

    # Nome como índice: permanece à esquerda ao rolar horizontalmente.
    mostrar = vista.set_index("Nome") if "Nome" in vista.columns else vista
    config: dict = {
        "Pres.%": st.column_config.NumberColumn("Pres.%", format="%.1f", width="small"),
        "Turma": st.column_config.TextColumn("Turma", width="small"),
        "Sala": st.column_config.TextColumn("Sala", width="small"),
        "Grupo": st.column_config.TextColumn("Grupo", width="small"),
        "Final": st.column_config.NumberColumn("Final", format="%.0f", width="small"),
        "Status": st.column_config.TextColumn("Status", width="medium"),
    }
    for col in mostrar.columns:
        if col in config:
            continue
        # Notas abreviadas (C1 Ori, EF Tot, …) — na tela 1 casa; no Excel até 3.
        config[col] = st.column_config.NumberColumn(col, format="%.1f", width="small")

    st.dataframe(
        mostrar,
        width="stretch",
        hide_index=False,
        height=min(52 + 35 * len(mostrar), 720),
        column_config=config,
    )

    st.download_button(
        "Baixar boletins filtrados (Excel)",
        data=bytes_excel_boletins(vista),
        file_name=f"boletins_{id_disc}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"lib_notas_xlsx_{id_disc}",
        help=(
            "Arquivo .xlsx limpo: colunas já separadas, notas como número "
            "(até 3 casas), células vazias onde não há nota."
        ),
    )
