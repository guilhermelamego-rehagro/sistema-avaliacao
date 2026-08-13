"""Regras de disciplinas e ciclos ativos."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

from data.sheets import ler_aba


def hoje_normalizado() -> pd.Timestamp:
    """Data civil em America/Sao_Paulo (evita pandas converter para UTC)."""
    return pd.Timestamp(datetime.now(ZoneInfo("America/Sao_Paulo")).date())


def obter_disciplina_ativa():
    return _obter_disciplina_ativa_cached()


@st.cache_data(ttl=900, show_spinner=False)
def _obter_disciplina_ativa_cached():
    df_disc = ler_aba("Disciplinas")
    ativa = df_disc[df_disc["Status"].astype(str).str.strip().str.lower() == "ativo"]
    if not ativa.empty:
        return ativa.iloc[0]["ID_Disciplina"], ativa.iloc[0]["Nome_Disciplina"]
    return None, None


def preparar_ciclos(df_ciclos: pd.DataFrame) -> pd.DataFrame:
    df = df_ciclos.copy()
    df["Data início"] = pd.to_datetime(df["Data início"], format="%d/%m/%Y", errors="coerce")
    df["Data fim"] = pd.to_datetime(df["Data fim"], format="%d/%m/%Y", errors="coerce")
    return df


def filtrar_ciclos_ativos(df_ciclos: pd.DataFrame, hoje: pd.Timestamp | None = None) -> pd.DataFrame:
    hoje = hoje or hoje_normalizado()
    df = preparar_ciclos(df_ciclos)
    ativo_status = df["Status"].astype(str).str.lower().str.strip() == "ativo"
    ativo_data = (hoje >= df["Data início"]) & (hoje <= df["Data fim"])
    return df[ativo_status | ativo_data]


def ciclos_da_disciplina(df_ciclos: pd.DataFrame, id_disciplina: str) -> pd.DataFrame:
    df = preparar_ciclos(df_ciclos)
    return df[df["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip()]


def ordenar_ciclos(df_ciclos: pd.DataFrame) -> pd.DataFrame:
    df = df_ciclos.copy()
    if "Ordem" in df.columns:
        df["Ordem"] = pd.to_numeric(df["Ordem"], errors="coerce")
        return df.sort_values("Ordem", na_position="last")
    if "Data início" in df.columns:
        df = preparar_ciclos(df)
        return df.sort_values("Data início", na_position="last")
    return df


def ciclo_padrao_nome(ciclos: pd.DataFrame, hoje: pd.Timestamp | None = None) -> str | None:
    """Ciclo aberto hoje; senão o último encerrado; senão o próximo futuro."""
    if ciclos is None or ciclos.empty:
        return None
    hoje = hoje or hoje_normalizado()
    df = preparar_ciclos(ciclos)
    if df.empty:
        return None

    aberto = df[(hoje >= df["Data início"]) & (hoje <= df["Data fim"])]
    if not aberto.empty:
        return str(ordenar_ciclos(aberto).iloc[0]["Nome_Ciclo"])

    encerrados = df[df["Data fim"].notna() & (df["Data fim"] < hoje)]
    if not encerrados.empty:
        return str(encerrados.sort_values("Data fim").iloc[-1]["Nome_Ciclo"])

    futuros = df[df["Data início"].notna() & (df["Data início"] > hoje)]
    if not futuros.empty:
        return str(futuros.sort_values("Data início").iloc[0]["Nome_Ciclo"])

    if "Status" in df.columns:
        ativos = df[df["Status"].astype(str).str.lower().str.strip() == "ativo"]
        if not ativos.empty:
            return str(ordenar_ciclos(ativos).iloc[0]["Nome_Ciclo"])

    ordenado = ordenar_ciclos(df)
    return str(ordenado.iloc[0]["Nome_Ciclo"]) if not ordenado.empty else None


def indice_ciclo_padrao(ciclos: pd.DataFrame, nomes: list[str]) -> int:
    if not nomes:
        return 0
    nome = ciclo_padrao_nome(ciclos)
    if nome and nome in nomes:
        return nomes.index(nome)
    return 0


def ciclo_inativo(id_ciclo: str) -> bool:
    """Retorna True quando o ciclo não está mais em andamento."""
    df = ler_aba("Ciclos")
    filtro = df[df["ID_Ciclo"].astype(str).str.strip() == str(id_ciclo).strip()]
    if filtro.empty:
        return False

    hoje = hoje_normalizado()
    row = filtro.iloc[0]
    ativo_status = str(row.get("Status", "")).lower().strip() == "ativo"
    prep = preparar_ciclos(filtro)
    inicio = prep.iloc[0]["Data início"]
    fim = prep.iloc[0]["Data fim"]
    if pd.isna(inicio) or pd.isna(fim):
        return not ativo_status
    ativo_data = (hoje >= inicio) & (hoje <= fim)
    return not (ativo_status or ativo_data)
