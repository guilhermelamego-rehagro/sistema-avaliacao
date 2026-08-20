"""Tela de lançamento da avaliação do orientador em grid alunos × ciclos."""

import pandas as pd
import streamlit as st

from data.sheets import ler_aba, texto_planilha
from domain.anotacoes_daily import anotacoes_do_grupo
from domain.avaliacoes import (
    carregar_mapa_notas_orientador,
    formatar_nota_grid,
    parse_nota_orientador,
    salvar_avaliacao_orientador,
)
from domain.cadastros import sala_padrao_orientador
from domain.ciclos import ordenar_ciclos
from domain.encontro_presencial import ciclos_visiveis_avaliacao
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.logs import registrar_log
from utils.preferencias_sala import selectbox_sala
from utils.ordenacao import ordenar_grupos_lista


def _montar_grid(
    alunos: pd.DataFrame,
    ciclos: pd.DataFrame,
    mapa_notas: dict[tuple[str, str], float],
) -> pd.DataFrame:
    colunas_ciclo = ciclos["Nome_Ciclo"].astype(str).tolist()
    id_por_nome = dict(
        zip(ciclos["Nome_Ciclo"].astype(str), ciclos["ID_Ciclo"].astype(str).str.strip())
    )

    linhas = []
    for _, aluno in alunos.iterrows():
        email = str(aluno["Email_Pessoal"]).strip().lower()
        row = {
            "Nome": aluno["Nome_Completo"],
            "Sala": texto_planilha(aluno.get("Sala", "")),
            "Grupo": texto_planilha(aluno.get("Grupo", "")),
            "Email": email,
        }
        for nome_ciclo in colunas_ciclo:
            id_ciclo = id_por_nome[nome_ciclo]
            nota = mapa_notas.get((email, id_ciclo))
            row[nome_ciclo] = "" if nota is None else formatar_nota_grid(nota)
        linhas.append(row)
    return pd.DataFrame(linhas)


def _validar_alteracoes(
    original: pd.DataFrame,
    editado: pd.DataFrame,
    colunas_ciclo: list[str],
) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str, float]]]:
    """Retorna (inválidas, válidas_para_salvar)."""
    invalidas: list[tuple[int, str, str]] = []
    validas: list[tuple[int, str, str, float]] = []

    for idx in range(len(editado)):
        for nome_ciclo in colunas_ciclo:
            val_novo = editado.iloc[idx][nome_ciclo]
            val_antigo = original.iloc[idx][nome_ciclo]
            if str(val_novo).strip() == str(val_antigo).strip():
                continue
            if not str(val_novo).strip():
                continue

            nota = parse_nota_orientador(val_novo)
            if nota is None:
                invalidas.append((idx, nome_ciclo, str(val_novo)))
            else:
                validas.append((idx, nome_ciclo, str(editado.iloc[idx]["Nome"]), nota))

    return invalidas, validas


def _estilo_celulas_invalidas(df: pd.DataFrame, invalidas: list[tuple[int, str, str]]):
    erro_idx = {(i, col) for i, col, _ in invalidas}

    def _linha(row):
        estilos = []
        for col in df.columns:
            if (row.name, col) in erro_idx:
                estilos.append("background-color: #ffcdd2; color: #b71c1c; font-weight: bold")
            else:
                estilos.append("")
        return estilos

    return df.style.apply(_linha, axis=1)


def _salvar_validas(
    original: pd.DataFrame,
    validas: list[tuple[int, str, str, float]],
    ciclos: pd.DataFrame,
    id_disciplina: str,
    usuario: dict,
) -> int:
    id_por_nome = dict(
        zip(ciclos["Nome_Ciclo"].astype(str), ciclos["ID_Ciclo"].astype(str).str.strip())
    )
    salvos = 0

    for idx, nome_ciclo, nome_aluno, nota in validas:
        email = str(original.iloc[idx]["Email"]).strip().lower()
        grupo = str(original.iloc[idx]["Grupo"])
        id_ciclo = id_por_nome[nome_ciclo]
        salvar_avaliacao_orientador(
            id_ciclo=id_ciclo,
            nome_ciclo=nome_ciclo,
            id_disciplina=id_disciplina,
            email_aluno=email,
            nome_aluno=nome_aluno,
            grupo=grupo,
            nota=nota,
            email_orientador=usuario["email"],
        )
        salvos += 1
    return salvos


def render(usuario: dict):
    st.header("Avaliação do orientador")
    st.caption(
        "Lance notas de 0 a 10 (até 1 casa decimal) diretamente no grid. "
        "Em caso de relançamento, **vale sempre a nota mais recente** nos cálculos."
    )

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox(
        "Disciplina:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
    )
    id_disc = id_disciplina_por_nome(df_disc, disc_sel)

    df_ciclos = ler_aba("Ciclos")
    ciclos = df_ciclos[df_ciclos["ID_Disciplina"].astype(str).str.strip() == id_disc]
    ciclos = ordenar_ciclos(ciclos_visiveis_avaliacao(ciclos, id_disc))
    if ciclos.empty:
        st.warning("Nenhum ciclo cadastrado.")
        return

    df_entrancia = ler_aba("Entrancia_Turma")
    alunos = df_entrancia[df_entrancia["ID_Disciplina"].astype(str).str.strip() == id_disc].copy()
    alunos = alunos.sort_values("Nome_Completo")

    c1, c2, c3 = st.columns(3)
    filtro_nome = c1.text_input("Filtrar por aluno:")
    salas = sorted(alunos["Sala"].dropna().astype(str).unique().tolist())
    sala_pref = sala_padrao_orientador(usuario, id_disc)
    if "orientador_sala" not in st.session_state and sala_pref in salas:
        st.session_state["orientador_sala"] = sala_pref
    with c2:
        filtro_sala = selectbox_sala(
            "Sala:",
            salas,
            key="orientador_sala",
            usuario=usuario,
        )
    grupos = ordenar_grupos_lista(alunos["Grupo"].dropna().astype(str).unique().tolist())
    filtro_grupo = c3.selectbox("Grupo:", ["Todos"] + grupos)

    alunos_filtrados = alunos.copy()
    if filtro_nome:
        alunos_filtrados = alunos_filtrados[
            alunos_filtrados["Nome_Completo"].str.contains(filtro_nome, case=False, na=False)
        ]
    if filtro_sala != "Todas":
        alunos_filtrados = alunos_filtrados[alunos_filtrados["Sala"].astype(str) == filtro_sala]
    if filtro_grupo != "Todos":
        alunos_filtrados = alunos_filtrados[alunos_filtrados["Grupo"].astype(str) == filtro_grupo]

    if alunos_filtrados.empty:
        st.info("Nenhum aluno encontrado com os filtros aplicados.")
        return

    mapa_notas = carregar_mapa_notas_orientador(id_disc)
    df_grid = _montar_grid(alunos_filtrados, ciclos, mapa_notas)
    colunas_ciclo = ciclos["Nome_Ciclo"].astype(str).tolist()

    col_config = {
        "Nome": st.column_config.TextColumn("Aluno", disabled=True),
        "Sala": st.column_config.TextColumn("Sala", disabled=True),
        "Grupo": st.column_config.TextColumn("Grupo", disabled=True),
        "Email": None,
    }
    for col in colunas_ciclo:
        col_config[col] = st.column_config.TextColumn(col, help="0 a 10, ex.: 8 ou 8,5")

    st.subheader("Grid de notas")
    df_editado = st.data_editor(
        df_grid,
        width="stretch",
        hide_index=True,
        column_order=["Nome", "Sala", "Grupo"] + colunas_ciclo,
        column_config=col_config,
        disabled=["Nome", "Sala", "Grupo"],
        key="grid_orientador",
    )

    chave_erros = f"orientador_erros_{id_disc}"
    if st.button("💾 Salvar alterações do grid", type="primary", width="stretch"):
        invalidas, validas = _validar_alteracoes(df_grid, df_editado, colunas_ciclo)

        if invalidas:
            st.session_state[chave_erros] = invalidas
            st.error(
                f"**{len(invalidas)}** célula(s) com nota inválida (use valores de 0 a 10). "
                "Corrija as células em vermelho abaixo."
            )
        else:
            st.session_state.pop(chave_erros, None)

        if validas:
            salvos = _salvar_validas(df_grid, validas, ciclos, id_disc, usuario)
            registrar_log(usuario["email"], usuario["nome"], f"Avaliação orientador grid - {disc_sel} ({salvos} notas)")
            st.success(f"{salvos} nota(s) salva(s)!")
            if not invalidas:
                st.rerun()
        elif not invalidas:
            st.info("Nenhuma alteração detectada.")

    invalidas_sessao = st.session_state.get(chave_erros, [])
    if invalidas_sessao:
        st.markdown("**Células com nota inválida:**")
        visao = df_editado[["Nome", "Sala", "Grupo"] + colunas_ciclo].copy()
        st.dataframe(_estilo_celulas_invalidas(visao, invalidas_sessao), width="stretch", hide_index=True)

    _render_anotacoes_dailies(id_disc, filtro_sala, filtro_grupo)

    st.markdown("---")
    st.subheader("Lançamento em lote")
    st.caption("Selecione alunos e ciclos, informe a nota e aplique de uma vez.")

    opcoes_alunos = alunos_filtrados.apply(
        lambda r: f"{r['Nome_Completo']} | Grupo {r['Grupo']}", axis=1
    ).tolist()
    alunos_lote = st.multiselect("Alunos:", opcoes_alunos)
    ciclos_lote = st.multiselect("Ciclos:", colunas_ciclo)
    nota_lote_txt = st.text_input("Nota para aplicar (0 a 10):", placeholder="Ex.: 9 ou 8,5")

    if st.button("Aplicar nota em lote", width="stretch"):
        if not alunos_lote or not ciclos_lote:
            st.error("Selecione ao menos um aluno e um ciclo.")
        else:
            nota_lote = parse_nota_orientador(nota_lote_txt)
            if nota_lote is None:
                st.error("Informe uma nota válida entre 0 e 10.")
            else:
                id_por_nome = dict(
                    zip(ciclos["Nome_Ciclo"].astype(str), ciclos["ID_Ciclo"].astype(str).str.strip())
                )
                total = 0
                for op in alunos_lote:
                    idx = opcoes_alunos.index(op)
                    row = alunos_filtrados.iloc[idx]
                    for nome_ciclo in ciclos_lote:
                        salvar_avaliacao_orientador(
                            id_ciclo=id_por_nome[nome_ciclo],
                            nome_ciclo=nome_ciclo,
                            id_disciplina=id_disc,
                            email_aluno=str(row["Email_Pessoal"]).strip().lower(),
                            nome_aluno=str(row["Nome_Completo"]),
                            grupo=str(row["Grupo"]),
                            nota=nota_lote,
                            email_orientador=usuario["email"],
                        )
                        total += 1
                registrar_log(usuario["email"], usuario["nome"], f"Avaliação orientador lote - {disc_sel}")
                st.success(f"Nota {formatar_nota_grid(nota_lote)} aplicada em {total} combinação(ões) aluno/ciclo.")
                st.session_state.pop(chave_erros, None)
                st.rerun()


def _render_anotacoes_dailies(id_disc: str, filtro_sala: str, filtro_grupo: str):
    st.markdown("---")
    st.subheader("Dailies do grupo — compilado")
    st.caption(
        "Anotações internas da orientação, para embasar a nota. "
        "Não entram no boletim do aluno."
    )
    notas = anotacoes_do_grupo(id_disc, filtro_sala, filtro_grupo)
    if notas.empty:
        st.info("Nenhuma anotação de daily para este recorte. Lance em Avaliações do ciclo → Anotações da daily.")
        return
    if filtro_grupo == "Todos":
        from utils.ordenacao import ordenar_grupos_lista

        for grupo in ordenar_grupos_lista(notas["Grupo"].unique().tolist()):
            bloco = notas[notas["Grupo"] == grupo]
            with st.expander(f"Grupo {grupo} ({len(bloco)} daily(s))", expanded=False):
                _tabela_anotacoes(bloco)
        return
    _tabela_anotacoes(notas)


def _tabela_anotacoes(df: pd.DataFrame):
    visao = df[["Data", "Nome_Ciclo", "Sala", "Grupo", "Texto", "Nome_Orientador"]].rename(
        columns={
            "Nome_Ciclo": "Ciclo",
            "Texto": "Anotação",
            "Nome_Orientador": "Orientadora",
        }
    )
    st.dataframe(visao, width="stretch", hide_index=True)
