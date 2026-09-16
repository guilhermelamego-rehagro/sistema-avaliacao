"""Controle de presença em aulas e dailies (professor/secretaria)."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.presenca import carregar_base_presenca, compilar_grid_dailies, compilar_grid_frequencia
from domain.cadastros import carregar_disciplinas
from domain.filtros_operacionais import preparar_alunos_presenca
from data.supabase_academico import academico_habilitado
from utils.disciplina import normalizar_id, remapear_coluna_id_disciplina
from utils.ordenacao import ordenar_grupos_lista

_PERSIST_TURMA = "presenca_persist_turma"
_PERSIST_SALA = "presenca_persist_sala"
_WIDGET_TURMA = "presenca_turma_ui"
_WIDGET_SALA = "presenca_sala_ui"


def _ordenacao_natural(lista) -> list:
    return ordenar_grupos_lista([str(x) for x in lista])


def _lista_sessao(chave: str) -> list[str]:
    val = st.session_state.get(chave) or []
    if not isinstance(val, list):
        return [str(val)] if val else []
    return [str(x) for x in val if str(x).strip()]


def _preparar_filtro_persistente(
    widget_key: str,
    persist_key: str,
    opcoes: list[str],
    *,
    hidratar: bool,
) -> None:
    """Prepara o widget. Só reidrata da persistência ao trocar de tela."""
    opcoes_set = set(opcoes)
    if hidratar or widget_key not in st.session_state:
        persistidos = _lista_sessao(persist_key)
        st.session_state[widget_key] = [x for x in persistidos if x in opcoes_set]
        return
    st.session_state[widget_key] = [x for x in _lista_sessao(widget_key) if x in opcoes_set]


def _salvar_filtro_persistente(persist_key: str, opcoes: list[str], selecionado: list[str]) -> None:
    """Mantém na sessão valores que não aparecem nesta tela; atualiza o restante."""
    opcoes_set = set(opcoes)
    fora = [x for x in _lista_sessao(persist_key) if x not in opcoes_set]
    escolhidos = [str(x) for x in (selecionado or []) if str(x).strip()]
    st.session_state[persist_key] = fora + [x for x in escolhidos if x not in fora]


def render(usuario: dict, tipo: str = "aulas"):
    eh_dailies = tipo == "dailies"
    st.header("Controle de dailies" if eh_dailies else "Controle de frequência")
    if eh_dailies:
        st.caption("Participação nas reuniões de orientação (dailies) por aluno e data.")

    df_entrancia = ler_aba("Entrancia_Turma")
    df_disciplinas = ler_aba("Disciplinas")
    df_alunos_base = ler_aba("Base_Alunos")
    atuais = {
        normalizar_id(row["ID_Disciplina"]): str(row.get("Nome_Disciplina", "")).strip()
        for _, row in carregar_disciplinas().iterrows()
        if normalizar_id(row.get("ID_Disciplina", ""))
    }
    if atuais:
        df_entrancia = remapear_coluna_id_disciplina(df_entrancia, atuais)

    lista_opcoes = df_disciplinas.apply(
        lambda x: f"{x['ID_Disciplina']} - {x['Nome_Disciplina']}", axis=1
    ).tolist()
    idx_ativo = 0
    ativas = df_disciplinas[df_disciplinas["Status"].astype(str).str.strip().str.lower() == "ativo"]
    if not ativas.empty:
        id_ativo = str(ativas.iloc[0]["ID_Disciplina"]).strip()
        for i, val in enumerate(lista_opcoes):
            if val.startswith(id_ativo):
                idx_ativo = i
                break

    disc_sel = st.selectbox(
        "Selecione a Disciplina para análise:",
        lista_opcoes,
        index=idx_ativo,
        key="presenca_disc",
    )
    id_disciplina_sel = disc_sel.split(" - ")[0]

    alunos_brutos = df_entrancia[
        df_entrancia["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disciplina_sel)
    ].copy()

    modo_label = "Operacional (só quem gera presença)"
    modo_completo_label = "Completa — MEC / auditoria (todos que estiveram matriculados)"
    if academico_habilitado():
        modo_ui = st.radio(
            "Lista de alunos:",
            options=[modo_label, modo_completo_label],
            index=0,
            horizontal=True,
            key=f"presenca_modo_{tipo}",
            help=(
                "Operacional: só matriculado + cursando. "
                "Completa: todos com matrícula/entrância na disciplina, "
                "com situação marcada (útil para MEC e para explicar ausências)."
            ),
        )
        modo = "completo" if modo_ui == modo_completo_label else "operacional"
    else:
        modo = "operacional"

    alunos_turma = preparar_alunos_presenca(
        alunos_brutos, id_disciplina_sel, modo=modo
    )

    if academico_habilitado() and not alunos_turma.empty:
        c_sit, c_st, c_gera = st.columns(3)
        sits = sorted(
            {str(x) for x in alunos_turma.get("Situacao_Oferta", pd.Series(dtype=str)) if str(x).strip()}
        )
        status_opts = sorted(
            {str(x) for x in alunos_turma.get("Status_Curso", pd.Series(dtype=str)) if str(x).strip()}
        )
        with c_sit:
            sit_f = st.multiselect(
                "Situação na oferta",
                options=sits,
                default=[],
                key=f"presenca_sit_{tipo}",
                placeholder="Todas",
            )
        with c_st:
            st_f = st.multiselect(
                "Status do curso",
                options=status_opts,
                default=[],
                key=f"presenca_status_{tipo}",
                placeholder="Todos",
            )
        with c_gera:
            gera_f = st.selectbox(
                "Gera presença?",
                options=["(todos)", "Sim", "Não"],
                index=0,
                key=f"presenca_gera_{tipo}",
            )
        if sit_f:
            alunos_turma = alunos_turma[alunos_turma["Situacao_Oferta"].isin(sit_f)]
        if st_f:
            alunos_turma = alunos_turma[alunos_turma["Status_Curso"].isin(st_f)]
        if gera_f == "Sim":
            alunos_turma = alunos_turma[alunos_turma["Gera_Presenca"] == True]  # noqa: E712
        elif gera_f == "Não":
            alunos_turma = alunos_turma[alunos_turma["Gera_Presenca"] == False]  # noqa: E712

        n_gera = int(alunos_turma["Gera_Presenca"].sum()) if "Gera_Presenca" in alunos_turma.columns else len(alunos_turma)
        n_nao = len(alunos_turma) - n_gera
        st.caption(
            f"**{len(alunos_turma)}** na lista filtrada "
            f"({n_gera} geram presença · {n_nao} sem geração de presença)."
        )

    if alunos_turma.empty:
        st.warning(
            "Nenhum aluno na Entrância/matrículas com este código de disciplina. "
            "Se o cadastro foi recodificado (ex.: 20263TRI → TRIB), os vínculos da aba "
            "Entrancia_Turma na planilha de produção ainda podem estar no código antigo."
        )

    if "Email_Pessoal" in df_alunos_base.columns and "Turma_Ingresso" in df_alunos_base.columns:
        # Evita duplicar Turma_Ingresso se já veio do preparo
        cols_merge = ["Email_Pessoal", "Turma_Ingresso"]
        base_m = df_alunos_base[cols_merge].copy()
        base_m["Email_Pessoal"] = base_m["Email_Pessoal"].astype(str).str.strip().str.lower()
        if "Turma_Ingresso" in alunos_turma.columns:
            alunos_turma = alunos_turma.drop(columns=["Turma_Ingresso"], errors="ignore")
        alunos_turma = pd.merge(
            alunos_turma,
            base_m,
            on="Email_Pessoal",
            how="left",
        )

    with st.spinner("Compilando presença..."):
        memoria_cache = carregar_base_presenca()
        memoria_cache["entrancia"] = df_entrancia
        if eh_dailies:
            df_resumo, df_raw = compilar_grid_dailies(
                id_disciplina_sel, alunos_turma, memoria_cache
            )
        else:
            df_resumo, df_raw = compilar_grid_frequencia(
                id_disciplina_sel, alunos_turma, memoria_cache
            )

    if df_raw.empty:
        st.info(
            "Nenhuma daily registrada ainda para esta disciplina."
            if eh_dailies
            else "Nenhuma aula registrada ainda para esta disciplina."
        )
        return

    datas_unicas = df_raw[["Data_Sort", "Data_Visual"]].drop_duplicates().sort_values("Data_Sort")
    colunas_datas_ordenadas = datas_unicas["Data_Visual"].tolist()

    df_pivot = (
        df_raw.pivot(index="Email_Cru", columns="Data_Visual", values="Status")
        .reset_index()
        .fillna("-")
    )
    df_final = pd.merge(df_resumo, df_pivot, on="Email_Cru", how="left")

    if academico_habilitado() and not alunos_turma.empty:
        meta_cols = [
            c
            for c in (
                "Email_Pessoal",
                "Status_Curso",
                "Situacao_Oferta",
                "Pendencia",
                "Gera_Presenca",
            )
            if c in alunos_turma.columns
        ]
        if meta_cols:
            meta = alunos_turma[meta_cols].copy()
            meta["_em"] = meta["Email_Pessoal"].astype(str).str.strip().str.lower()
            df_final["_em"] = df_final["Email_Cru"].astype(str).str.strip().str.lower()
            df_final = df_final.merge(
                meta.drop(columns=["Email_Pessoal"]),
                on="_em",
                how="left",
            ).drop(columns=["_em"])
            gera_col = df_final["Gera_Presenca"] if "Gera_Presenca" in df_final.columns else True
            if isinstance(gera_col, pd.Series):
                df_final["Gera_Presenca"] = gera_col.fillna(False).map(
                    lambda v: "Sim" if bool(v) and v != "Não" else "Não"
                )
            df_final["Pendencia"] = (
                df_final["Pendencia"].fillna("").replace({"segunda_chamada": "2ª chamada"})
                if "Pendencia" in df_final.columns
                else ""
            )
            if "Status_Curso" in df_final.columns:
                df_final["Status_Curso"] = df_final["Status_Curso"].fillna("")
            if "Situacao_Oferta" in df_final.columns:
                df_final["Situacao_Oferta"] = df_final["Situacao_Oferta"].fillna("")

    turmas_opcoes = _ordenacao_natural(df_final["Turma"].unique())
    salas_opcoes = _ordenacao_natural(df_final["Sala"].unique())

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    trocou_tela = st.session_state.get("presenca_ultima_tela") != tipo
    st.session_state["presenca_ultima_tela"] = tipo
    _preparar_filtro_persistente(_WIDGET_TURMA, _PERSIST_TURMA, turmas_opcoes, hidratar=trocou_tela)
    _preparar_filtro_persistente(_WIDGET_SALA, _PERSIST_SALA, salas_opcoes, hidratar=trocou_tela)
    turma_filtro = c1.multiselect("Filtrar por Turma:", turmas_opcoes, key=_WIDGET_TURMA)
    sala_filtro = c2.multiselect("Filtrar por Sala:", salas_opcoes, key=_WIDGET_SALA)
    _salvar_filtro_persistente(_PERSIST_TURMA, turmas_opcoes, turma_filtro)
    _salvar_filtro_persistente(_PERSIST_SALA, salas_opcoes, sala_filtro)

    base_grupos = df_final
    if turma_filtro:
        base_grupos = base_grupos[base_grupos["Turma"].isin(turma_filtro)]
    if sala_filtro:
        base_grupos = base_grupos[base_grupos["Sala"].isin(sala_filtro)]
    grupos_opcoes = _ordenacao_natural(base_grupos["Grupo"].unique())
    chave_grupo = f"presenca_grupo_{tipo}"
    if chave_grupo in st.session_state:
        atual_grupos = st.session_state.get(chave_grupo) or []
        if not isinstance(atual_grupos, list):
            atual_grupos = [atual_grupos] if atual_grupos else []
        st.session_state[chave_grupo] = [g for g in atual_grupos if g in grupos_opcoes]
    grupo_filtro = c3.multiselect("Filtrar por Grupo:", grupos_opcoes, key=chave_grupo)

    c4, c5 = st.columns(2)
    nome_busca = c4.text_input("Buscar por Nome do Aluno:", key=f"presenca_nome_{tipo}")
    faixa_projetada = c5.slider(
        "Filtrar por % Projetada:",
        min_value=0.0,
        max_value=100.0,
        value=(0.0, 100.0),
        format="%.0f%%",
        key=f"presenca_faixa_{tipo}",
    )

    max_faltas_disponivel = int(df_final["Faltas"].max()) if not df_final.empty else 0
    max_slider_faltas = max(max_faltas_disponivel, 1)
    chave_faixa_faltas = f"presenca_faixa_faltas_{tipo}"
    if chave_faixa_faltas in st.session_state:
        atual_faixa = st.session_state[chave_faixa_faltas]
        if (
            not isinstance(atual_faixa, (list, tuple))
            or len(atual_faixa) != 2
            or atual_faixa[0] < 0
            or atual_faixa[1] > max_slider_faltas
            or atual_faixa[0] > atual_faixa[1]
        ):
            st.session_state[chave_faixa_faltas] = (0, max_slider_faltas)
    c6, c7 = st.columns([2, 1.4])
    faixa_faltas = c6.slider(
        "Filtrar por nº de faltas:",
        min_value=0,
        max_value=max_slider_faltas,
        value=(0, max_slider_faltas),
        key=chave_faixa_faltas,
        help="Contagem total de faltas nas sessões já realizadas desta modalidade.",
    )
    filtro_seguidas = c7.checkbox(
        "2 ou mais faltas seguidas",
        value=False,
        key=f"presenca_seguidas_{tipo}",
        help=(
            "Mostra só quem está com 2 ou mais faltas consecutivas "
            "nas últimas aulas/dailies já realizadas desta modalidade. "
            "Conexão abaixo de 30 min conta como falta."
        ),
    )

    opcao_todas = "(todas as datas)"
    mapa_datas: dict[str, pd.Timestamp] = {}
    for _, row_data in datas_unicas.iterrows():
        data_ref = pd.Timestamp(row_data["Data_Sort"]).normalize()
        rotulo = data_ref.strftime("%d/%m/%Y")
        mapa_datas[rotulo] = data_ref
    data_falta = st.selectbox(
        "Faltantes em uma data:",
        [opcao_todas] + list(mapa_datas.keys()),
        key=f"presenca_data_falta_{tipo}",
        help=(
            "Lista só quem faltou na data escolhida. "
            "Conexão abaixo de 30 min conta como falta."
        ),
    )

    if turma_filtro:
        df_final = df_final[df_final["Turma"].isin(turma_filtro)]
    if sala_filtro:
        df_final = df_final[df_final["Sala"].isin(sala_filtro)]
    if grupo_filtro:
        df_final = df_final[df_final["Grupo"].isin(grupo_filtro)]
    if nome_busca:
        df_final = df_final[df_final["Nome"].str.contains(nome_busca, case=False, na=False)]

    df_final = df_final[
        (df_final["% Projetado"] >= faixa_projetada[0])
        & (df_final["% Projetado"] <= faixa_projetada[1])
    ]
    df_final = df_final[
        (df_final["Faltas"] >= faixa_faltas[0])
        & (df_final["Faltas"] <= faixa_faltas[1])
    ]
    if filtro_seguidas:
        df_final = df_final[df_final["Faltas seguidas"] >= 2]
    if data_falta != opcao_todas:
        data_ref = mapa_datas[data_falta]
        df_dia = df_raw.copy()
        df_dia["Data_Norm"] = pd.to_datetime(df_dia["Data_Sort"], errors="coerce").dt.normalize()
        emails_faltaram = df_dia[
            (df_dia["Data_Norm"] == data_ref)
            & (df_dia["Status"].isin(["❌", "⏳"]))
        ]["Email_Cru"]
        df_final = df_final[df_final["Email_Cru"].isin(emails_faltaram)]

    if df_final.empty:
        if data_falta != opcao_todas:
            aviso = f"Nenhum aluno faltou em {data_falta} com os filtros atuais."
        elif filtro_seguidas:
            aviso = "Nenhum aluno com 2 ou mais faltas seguidas nesta modalidade."
        elif faixa_faltas != (0, max_slider_faltas):
            aviso = (
                f"Nenhum aluno com {faixa_faltas[0]} a {faixa_faltas[1]} "
                "faltas nesta modalidade."
            )
        else:
            aviso = "Nenhum aluno encontrado com esses filtros."
        st.warning(aviso)
        return

    if data_falta != opcao_todas:
        st.warning(
            f"**{len(df_final)}** aluno(s) faltaram em **{data_falta}** "
            f"{'nas dailies' if eh_dailies else 'nas aulas'}."
        )
    if filtro_seguidas:
        st.warning(
            f"**{len(df_final)}** aluno(s) com 2 ou mais faltas seguidas "
            f"{'nas dailies' if eh_dailies else 'nas aulas'} — priorize a abordagem."
        )
        df_final = df_final.sort_values(
            ["Faltas seguidas", "Faltas", "Nome"], ascending=[False, False, True]
        )
    elif faixa_faltas != (0, max_slider_faltas):
        df_final = df_final.sort_values(["Faltas", "Nome"], ascending=[False, True])
    else:
        df_final = df_final.sort_values("Nome")

    df_final = df_final.set_index("Nome")
    cols_formas = ["Turma", "Sala", "Grupo"]
    for c in ("Status_Curso", "Situacao_Oferta", "Pendencia", "Gera_Presenca"):
        if c in df_final.columns:
            cols_formas.append(c)
    cols_formas += ["% Realizado", "% Projetado", "Faltas"]
    cols_finais = cols_formas + [c for c in colunas_datas_ordenadas if c in df_final.columns]
    df_final = df_final[cols_finais]

    df_excel = df_final.copy().replace({"✅": "P", "❌": "F", "⏳": "C", "✏️": "A", "📅": "N"})
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_excel.to_excel(writer, index=True, sheet_name="Dailies" if eh_dailies else "Frequencia")

    col_exp, _ = st.columns([1, 2])
    col_exp.download_button(
        label="📥 Exportar Dados para Excel (.xlsx)",
        data=buffer.getvalue(),
        file_name=f"{'Dailies' if eh_dailies else 'Controle_Frequencia'}_{id_disciplina_sel}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"presenca_xlsx_{tipo}",
    )

    config_colunas = {
        "% Realizado": st.column_config.NumberColumn("% Realizado", format="%.1f %%"),
        "% Projetado": st.column_config.NumberColumn("% Projetado", format="%.1f %%"),
        "Faltas": st.column_config.NumberColumn(
            "Faltas",
            help="Total de faltas nas sessões já realizadas desta modalidade.",
            format="%d",
        ),
    }
    if eh_dailies:
        st.caption(
            "Legenda: ✅ Participou | ❌ Faltou | 📅 Daily futura. "
            "**Faltas** = total nas dailies já realizadas. "
            "O filtro de 2+ faltas seguidas usa só a sequência recente."
        )
    else:
        st.caption(
            "Legenda na tela: ✅ Presente | ❌ Falta | ⏳ Conectado (<30min) | "
            "✏️ Ajuste Manual | 📅 Aula futura. "
            "**Faltas** = total nas aulas já realizadas "
            "(conexão < 30 min entra como falta). "
            "O filtro de 2+ faltas seguidas usa só a sequência recente."
        )
    if academico_habilitado() and "Gera_Presenca" in df_final.columns:
        st.caption(
            "**Gera_Presenca = Não**: situação/status que não entram no controle operacional "
            "(ex.: desistente, aprovado, formado) — permanecem na lista completa para MEC/auditoria."
        )
    st.caption(f"{len(df_final)} aluno(s) no filtro selecionado.")
    st.dataframe(df_final, width="stretch", column_config=config_colunas)
