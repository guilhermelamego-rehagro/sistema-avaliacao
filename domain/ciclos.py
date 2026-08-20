"""Regras de disciplinas e ciclos ativos."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from datetime import date, datetime
from zoneinfo import ZoneInfo

from data.sheets import ler_aba
from utils.datas import parse_data_planilha_series
from utils.disciplina import normalizar_id


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
    for col in ("Data início", "Data fim", "Data_Inicio_Ciclo", "Data_Apresentacao"):
        if col in df.columns:
            df[col] = parse_data_planilha_series(df[col])
    return df


def filtrar_ciclos_ativos(df_ciclos: pd.DataFrame, hoje: pd.Timestamp | None = None) -> pd.DataFrame:
    hoje = hoje or hoje_normalizado()
    df = preparar_ciclos(df_ciclos)
    ativo_status = df["Status"].astype(str).str.lower().str.strip() == "ativo"
    tem_janela = df["Data início"].notna() & df["Data fim"].notna()
    ativo_data = (hoje >= df["Data início"]) & (hoje <= df["Data fim"])
    # Com abertura e encerramento das pares preenchidos, só abre dentro da janela.
    # Sem janela completa, mantém o fallback pelo Status ativo.
    aberto = (tem_janela & ativo_status & ativo_data) | (~tem_janela & ativo_status)
    return df[aberto]


def ciclos_da_disciplina(df_ciclos: pd.DataFrame, id_disciplina: str) -> pd.DataFrame:
    df = preparar_ciclos(df_ciclos)
    alvo = str(id_disciplina).strip()
    try:
        from domain.cadastros import carregar_disciplinas
        from utils.disciplina import remapear_coluna_id_disciplina

        discs = carregar_disciplinas()
        atuais = {
            str(row["ID_Disciplina"]).strip(): str(row.get("Nome_Disciplina", "")).strip()
            for _, row in discs.iterrows()
            if str(row.get("ID_Disciplina", "")).strip()
        }
        if atuais:
            df = remapear_coluna_id_disciplina(df, atuais)
    except Exception:
        pass
    return df[df["ID_Disciplina"].astype(str).str.strip() == alvo]


def ordenar_ciclos(df_ciclos: pd.DataFrame) -> pd.DataFrame:
    """Ordem vale dentro de cada disciplina (1, 2, 3… por ID_Disciplina)."""
    df = df_ciclos.copy()
    chaves: list[str] = []
    if "ID_Disciplina" in df.columns:
        chaves.append("ID_Disciplina")
    if "Ordem" in df.columns:
        df["Ordem"] = pd.to_numeric(df["Ordem"], errors="coerce")
        chaves.append("Ordem")
    if "Data início" in df.columns:
        df = preparar_ciclos(df)
        chaves.append("Data início")
    if not chaves:
        return df
    return df.sort_values(chaves, na_position="last")


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
    if pd.notna(inicio) and pd.notna(fim):
        ativo_data = (hoje >= inicio) & (hoje <= fim)
        return not (ativo_status and ativo_data)
    return not ativo_status


def _como_date(valor) -> date | None:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    try:
        return pd.Timestamp(valor).date()
    except Exception:
        return None


def ciclo_na_data(id_disciplina: str, dia: date) -> tuple[str, str]:
    """(ID_Ciclo, Nome_Ciclo) pelo período acadêmico; vazio se não houver recorte."""
    alvo = _como_date(dia)
    if alvo is None or not id_disciplina:
        return "", ""
    try:
        from domain.cadastros import carregar_ciclos

        df = carregar_ciclos()
    except Exception:
        return "", ""
    df = ciclos_da_disciplina(df, id_disciplina)
    if df.empty:
        return "", ""
    df = preparar_ciclos(df)
    if "Data_Inicio_Ciclo" not in df.columns or "Data_Apresentacao" not in df.columns:
        return "", ""
    idxs = []
    for idx, row in df.iterrows():
        ini = _como_date(row.get("Data_Inicio_Ciclo"))
        fim = _como_date(row.get("Data_Apresentacao"))
        if ini is None or fim is None:
            continue
        if ini > fim:
            ini, fim = fim, ini
        if ini <= alvo <= fim:
            idxs.append(idx)
    if not idxs:
        return "", ""
    bloco = ordenar_ciclos(df.loc[idxs])
    row = bloco.iloc[-1]
    return normalizar_id(row.get("ID_Ciclo", "")), str(row.get("Nome_Ciclo", "")).strip()
