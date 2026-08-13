"""Cálculo de presenças, dailies e grid de frequência em lote."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config import ICONE_STATUS_PRESENCA, MINUTOS_PRESENCA
from data.sheets import ler_aba, ler_aba_frequencia
from domain.ciclos import hoje_normalizado
from utils.datas import parse_data_planilha_series
from utils.disciplina import normalizar_id


@st.cache_data(ttl=900, show_spinner=False)
def carregar_base_presenca() -> dict:
    """Carrega de uma vez as abas usadas em frequência e dailies (cache compartilhado)."""
    return {
        "bd": ler_aba_frequencia("BD_Presenca"),
        "ajustes": ler_aba_frequencia("Ajustes_Presenca"),
        "calendario": ler_aba_frequencia("Calendario_Aulas"),
        "calendario_dailies": ler_aba_frequencia("Calendario_Dailies"),
        "entrancia": ler_aba("Entrancia_Turma"),
    }


def _preparar_entrancia(df_entrancia: pd.DataFrame) -> pd.DataFrame:
    df = df_entrancia.copy()
    df["Email_Limpo"] = df["Email_Pessoal"].astype(str).str.strip().str.lower()
    df["ID_Disc_Limpo"] = df["ID_Disciplina"].map(normalizar_id)
    return df


def _preparar_calendario(df_calendario: pd.DataFrame) -> pd.DataFrame:
    df = df_calendario.copy()
    if "ID_Disciplina" not in df.columns:
        df["ID_Disciplina"] = ""
    if "Data" not in df.columns:
        df["Data"] = ""
    if "Disciplina" not in df.columns:
        df["Disciplina"] = ""
    df["ID_Disc_Limpo"] = df["ID_Disciplina"].map(normalizar_id)
    df["Data_Formatada"] = pd.to_datetime(
        parse_data_planilha_series(df["Data"]), errors="coerce"
    ).dt.normalize()
    df["Chave_Disc"] = df["Disciplina"].astype(str).str.strip().str.lower()
    return df


def _preparar_meet(df_bd_presenca: pd.DataFrame) -> pd.DataFrame:
    if df_bd_presenca.empty or "Email" not in df_bd_presenca.columns:
        return pd.DataFrame(columns=["Email_Limpo", "Data_Formatada", "Chave_Disc", "Minutos"])

    df = df_bd_presenca.copy()
    df["Email_Limpo"] = df["Email"].astype(str).str.strip().str.lower()
    df["Data_Formatada"] = parse_data_planilha_series(df["Data"])
    df["Chave_Disc"] = df["Disciplina"].astype(str).str.strip().str.lower()
    return (
        df.groupby(["Email_Limpo", "Data_Formatada", "Chave_Disc"], as_index=False)["Minutos"]
        .sum()
    )


def _preparar_ajustes(df_ajustes: pd.DataFrame) -> pd.DataFrame:
    if df_ajustes.empty or "Email_Aluno" not in df_ajustes.columns:
        return pd.DataFrame(columns=["Email_Limpo", "Data_Str", "Chave_Disc", "Novo_Status"])

    df = df_ajustes.copy()
    df["Email_Limpo"] = df["Email_Aluno"].astype(str).str.strip().str.lower()
    df["Chave_Disc"] = df["Disciplina"].astype(str).str.strip().str.lower()
    df["Data_Parsed"] = parse_data_planilha_series(df["Data"])
    df["Data_Str"] = df["Data_Parsed"].dt.strftime("%d/%m/%Y")

    col_status = "Novo_Status"
    for candidata in ("Novo_Status", "Novo Status", "Status"):
        if candidata in df.columns:
            col_status = candidata
            break
    else:
        df["Novo_Status"] = ""
        col_status = "Novo_Status"

    if col_status != "Novo_Status":
        df["Novo_Status"] = df[col_status]

    return df[["Email_Limpo", "Data_Str", "Chave_Disc", "Novo_Status"]]


def _aplicar_status_presenca(matriz: pd.DataFrame, df_ajustes: pd.DataFrame) -> pd.DataFrame:
    hoje = hoje_normalizado()
    df = matriz.copy()
    df["Data_Formatada"] = pd.to_datetime(df["Data_Formatada"], errors="coerce").dt.normalize()
    df["Data_Str"] = df["Data_Formatada"].dt.strftime("%d/%m/%Y")

    if not df_ajustes.empty:
        df = df.merge(df_ajustes, on=["Email_Limpo", "Data_Str", "Chave_Disc"], how="left")

    futuro = df["Data_Formatada"] > hoje
    invalido = df["Data_Formatada"].isna()
    tem_ajuste = (
        df["Novo_Status"].notna() & df["Novo_Status"].astype(str).str.strip().ne("")
        if "Novo_Status" in df.columns
        else pd.Series(False, index=df.index)
    )

    df["Status_Tecnico"] = "Falta"
    df["Status_Aluno"] = "Falta"

    df.loc[invalido, "Status_Tecnico"] = "Erro"
    df.loc[invalido, "Status_Aluno"] = "Data Inválida"
    df.loc[futuro & ~invalido, "Status_Tecnico"] = "Futuro"
    df.loc[futuro & ~invalido, "Status_Aluno"] = "Agendada"

    if tem_ajuste.any():
        df.loc[tem_ajuste, "Status_Tecnico"] = "Ajuste"
        df.loc[tem_ajuste, "Status_Aluno"] = df.loc[tem_ajuste, "Novo_Status"]

    base = ~invalido & ~futuro & ~tem_ajuste
    df.loc[base & (df["Minutos"] >= MINUTOS_PRESENCA), "Status_Tecnico"] = "Presente"
    df.loc[base & (df["Minutos"] >= MINUTOS_PRESENCA), "Status_Aluno"] = "Presente"
    df.loc[base & (df["Minutos"] > 0) & (df["Minutos"] < MINUTOS_PRESENCA), "Status_Tecnico"] = "Conectado"
    df.loc[base & (df["Minutos"] > 0) & (df["Minutos"] < MINUTOS_PRESENCA), "Status_Aluno"] = "Falta"

    df["Data"] = df["Data_Formatada"]
    return df


def calcular_matriz_presencas(email_aluno: str, dfs_cache: dict | None = None) -> pd.DataFrame:
    if dfs_cache is None:
        dfs_cache = carregar_base_presenca()
        df_bd_presenca = dfs_cache["bd"].copy()
        df_ajustes = dfs_cache["ajustes"].copy()
        df_calendario = dfs_cache["calendario"].copy()
        df_entrancia = dfs_cache["entrancia"].copy()
    else:
        df_bd_presenca = dfs_cache["bd"].copy()
        df_ajustes = dfs_cache["ajustes"].copy()
        df_calendario = dfs_cache["calendario"].copy()
        df_entrancia = dfs_cache["entrancia"].copy()

    email_aluno = str(email_aluno).strip().lower()
    df_entrancia = _preparar_entrancia(df_entrancia)
    disciplinas_aluno = df_entrancia.loc[
        df_entrancia["Email_Limpo"] == email_aluno, "ID_Disc_Limpo"
    ].unique()
    if len(disciplinas_aluno) == 0:
        return pd.DataFrame()

    df_calendario = _preparar_calendario(df_calendario)
    aulas = df_calendario[df_calendario["ID_Disc_Limpo"].isin(disciplinas_aluno)].copy()
    aulas["Email_Limpo"] = email_aluno

    meet = _preparar_meet(df_bd_presenca)
    meet = meet[meet["Email_Limpo"] == email_aluno]
    matriz = aulas.merge(meet, on=["Email_Limpo", "Data_Formatada", "Chave_Disc"], how="left")
    matriz["Minutos"] = matriz["Minutos"].fillna(0)

    ajustes = _preparar_ajustes(df_ajustes)
    ajustes = ajustes[ajustes["Email_Limpo"] == email_aluno]
    return _aplicar_status_presenca(matriz, ajustes)


def calcular_matriz_dailies(email_aluno: str, dfs_cache: dict | None = None) -> pd.DataFrame:
    if dfs_cache is None:
        dfs_cache = carregar_base_presenca()
    df_bd_presenca = dfs_cache["bd"].copy()
    df_entrancia = _preparar_entrancia(dfs_cache["entrancia"].copy())
    df_calendario_dailies = _preparar_calendario(dfs_cache["calendario_dailies"].copy())

    email_aluno = str(email_aluno).strip().lower()
    disciplinas_aluno = df_entrancia.loc[
        df_entrancia["Email_Limpo"] == email_aluno, "ID_Disc_Limpo"
    ].unique()
    if len(disciplinas_aluno) == 0:
        return pd.DataFrame()

    dailies = df_calendario_dailies[
        df_calendario_dailies["ID_Disc_Limpo"].isin(disciplinas_aluno)
    ].copy()
    dailies["Email_Limpo"] = email_aluno

    meet = _preparar_meet(df_bd_presenca)
    meet = meet[meet["Email_Limpo"] == email_aluno]
    matriz = dailies.merge(meet, on=["Email_Limpo", "Data_Formatada", "Chave_Disc"], how="left")
    matriz["Minutos"] = matriz["Minutos"].fillna(0)

    hoje = hoje_normalizado()
    matriz["Data_Formatada"] = pd.to_datetime(matriz["Data_Formatada"], errors="coerce").dt.normalize()
    matriz["Status_Tecnico"] = "Falta"
    matriz["Status_Aluno"] = "Falta"
    matriz.loc[matriz["Data_Formatada"].isna(), ["Status_Tecnico", "Status_Aluno"]] = [
        "Erro",
        "Data Inválida",
    ]
    matriz.loc[matriz["Data_Formatada"] > hoje, "Status_Tecnico"] = "Futuro"
    matriz.loc[matriz["Data_Formatada"] > hoje, "Status_Aluno"] = "Agendada"
    passado = (matriz["Data_Formatada"] <= hoje) & matriz["Data_Formatada"].notna()
    matriz.loc[passado & (matriz["Minutos"] > 0), "Status_Tecnico"] = "Presente"
    matriz.loc[passado & (matriz["Minutos"] > 0), "Status_Aluno"] = "Presente"
    matriz["Data"] = matriz["Data_Formatada"]
    return matriz


def compilar_grid_frequencia(
    id_disciplina: str,
    alunos_turma: pd.DataFrame,
    dfs_cache: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compila resumo e grid de frequência para todos os alunos de uma disciplina em lote.
    Retorna (df_resumo, df_grid_detalhe).
    """
    if dfs_cache is None:
        dfs_cache = carregar_base_presenca()

    id_disciplina = normalizar_id(id_disciplina)
    emails_alvo = alunos_turma["Email_Pessoal"].astype(str).str.strip().str.lower().tolist()

    df_calendario = _preparar_calendario(dfs_cache["calendario"].copy())
    aulas = df_calendario[df_calendario["ID_Disc_Limpo"] == id_disciplina].copy()
    if aulas.empty:
        return pd.DataFrame(), pd.DataFrame()

    emails_df = pd.DataFrame({"Email_Limpo": emails_alvo})
    base = aulas.assign(_k=1).merge(emails_df.assign(_k=1), on="_k").drop(columns="_k")

    meet = _preparar_meet(dfs_cache["bd"].copy())
    meet = meet[meet["Email_Limpo"].isin(emails_alvo)]
    matriz = base.merge(meet, on=["Email_Limpo", "Data_Formatada", "Chave_Disc"], how="left")
    matriz["Minutos"] = matriz["Minutos"].fillna(0)

    ajustes = _preparar_ajustes(dfs_cache["ajustes"].copy())
    ajustes = ajustes[ajustes["Email_Limpo"].isin(emails_alvo)]
    matriz = _aplicar_status_presenca(matriz, ajustes)

    meta = alunos_turma.copy()
    meta["Email_Limpo"] = meta["Email_Pessoal"].astype(str).str.strip().str.lower()
    meta = meta.set_index("Email_Limpo")

    resumo_rows = []
    grid_rows = []

    for email, grupo in matriz.groupby("Email_Limpo"):
        if email not in meta.index:
            continue
        aluno = meta.loc[email]
        vivido = grupo[grupo["Status_Tecnico"] != "Futuro"]
        futuro = grupo[grupo["Status_Tecnico"] == "Futuro"]
        pres = len(vivido[vivido["Status_Aluno"] == "Presente"])
        total_vivido = len(vivido)
        pct_real = (pres / total_vivido * 100) if total_vivido > 0 else 100.0
        pct_proj = ((pres + len(futuro)) / len(grupo) * 100) if len(grupo) > 0 else 100.0

        resumo_rows.append(
            {
                "Email_Cru": aluno["Email_Pessoal"],
                "Nome": aluno["Nome_Completo"],
                "Turma": str(aluno.get("Turma_Ingresso", "-")),
                "Sala": str(aluno["Sala"]),
                "Grupo": str(aluno["Grupo"]),
                "% Realizado": float(pct_real),
                "% Projetado": float(pct_proj),
            }
        )

        for _, row in grupo.sort_values("Data").iterrows():
            data_ref = row.get("Data")
            if pd.isna(data_ref):
                continue
            icone = ICONE_STATUS_PRESENCA.get(row["Status_Tecnico"], "-")
            grid_rows.append(
                {
                    "Email_Cru": aluno["Email_Pessoal"],
                    "Data_Visual": pd.Timestamp(data_ref).strftime("%d/%m"),
                    "Data_Sort": data_ref,
                    "Status": icone,
                }
            )

    return pd.DataFrame(resumo_rows), pd.DataFrame(grid_rows)
