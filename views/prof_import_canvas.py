"""Importação de notas de atividades individuais a partir de export do Canvas."""

import io

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.avaliacoes import importar_atividades_canvas
from utils.logs import registrar_log


def _detectar_colunas(df: pd.DataFrame) -> dict:
    cols = {c.lower().strip(): c for c in df.columns}
    mapeamento = {}

    for alvo, candidatos in {
        "Email_Aluno": ["email", "student email", "sis login id", "login id", "email do aluno"],
        "Nome_Aluno": ["nome", "student", "student name", "nome do aluno", "name"],
        "Atividade": ["assignment", "atividade", "assignment name", "nome da tarefa"],
        "Semana": ["semana", "week", "module"],
        "Nota": ["score", "nota", "grade", "pontos", "final score"],
    }.items():
        for cand in candidatos:
            if cand in cols:
                mapeamento[alvo] = cols[cand]
                break

    return mapeamento


def render(usuario: dict):
    st.header("📥 Importar Atividades do Canvas")
    st.caption(
        "Envie o CSV/Excel exportado do Canvas (notas por atividade). "
        "O sistema tentará mapear as colunas automaticamente."
    )

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox("Disciplina de destino:", lista_disc)
    id_disc = str(df_disc[df_disc["Nome_Disciplina"] == disc_sel].iloc[0]["ID_Disciplina"]).strip()

    arquivo = st.file_uploader("Arquivo Canvas (.csv ou .xlsx)", type=["csv", "xlsx"])

    if not arquivo:
        st.info("Exemplo de colunas úteis no export: Student, SIS Login ID, Assignment, Score")
        return

    try:
        if arquivo.name.endswith(".xlsx"):
            df_raw = pd.read_excel(arquivo)
        else:
            df_raw = pd.read_csv(arquivo)
    except Exception as e:
        st.error(f"Não foi possível ler o arquivo: {e}")
        return

    st.write("Prévia do arquivo:")
    st.dataframe(df_raw.head(10), width="stretch")

    mapa_auto = _detectar_colunas(df_raw)
    st.subheader("Mapeamento de colunas")
    c1, c2 = st.columns(2)
    col_email = c1.selectbox(
        "Coluna de e-mail do aluno:",
        df_raw.columns.tolist(),
        index=df_raw.columns.get_loc(mapa_auto["Email_Aluno"]) if "Email_Aluno" in mapa_auto else 0,
    )
    col_nome = c2.selectbox(
        "Coluna de nome:",
        [""] + df_raw.columns.tolist(),
        index=(df_raw.columns.get_loc(mapa_auto["Nome_Aluno"]) + 1) if "Nome_Aluno" in mapa_auto else 0,
    )
    c3, c4 = st.columns(2)
    col_ativ = c3.selectbox(
        "Coluna da atividade:",
        df_raw.columns.tolist(),
        index=df_raw.columns.get_loc(mapa_auto["Atividade"]) if "Atividade" in mapa_auto else 0,
    )
    col_nota = c4.selectbox(
        "Coluna da nota:",
        df_raw.columns.tolist(),
        index=df_raw.columns.get_loc(mapa_auto["Nota"]) if "Nota" in mapa_auto else 0,
    )
    col_semana = st.selectbox(
        "Coluna da semana (opcional):",
        [""] + df_raw.columns.tolist(),
        index=(df_raw.columns.get_loc(mapa_auto["Semana"]) + 1) if "Semana" in mapa_auto else 0,
    )

    df_prep = pd.DataFrame()
    df_prep["Email_Aluno"] = df_raw[col_email].astype(str).str.strip().str.lower()
    df_prep["Nome_Aluno"] = df_raw[col_nome].astype(str) if col_nome else ""
    df_prep["Atividade"] = df_raw[col_ativ].astype(str)
    df_prep["Semana"] = df_raw[col_semana].astype(str) if col_semana else ""
    df_prep["Nota"] = pd.to_numeric(df_raw[col_nota], errors="coerce")

    df_prep = df_prep[df_prep["Email_Aluno"].str.contains("@", na=False)]
    df_prep = df_prep[df_prep["Nota"].notna()]

    st.write(f"**{len(df_prep)}** linhas prontas para importar.")
    st.dataframe(df_prep.head(15), width="stretch")

    if st.button("Confirmar importação", type="primary", width="stretch"):
        qtd = importar_atividades_canvas(df_prep, id_disc)
        registrar_log(usuario["email"], usuario["nome"], f"Importou {qtd} atividades Canvas - {disc_sel}")
        st.success(f"{qtd} notas importadas para **{disc_sel}**!")
        st.rerun()
