"""Regras de janela, ordem de apresentação e status da avaliação de entregas."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from data.sheets import garantir_aba_avaliacao, ler_aba, limpar_cache_planilhas, planilha
from domain.avaliacoes import filtrar_avaliacoes_grupo
from domain.encontro_presencial import ciclos_visiveis_avaliacao
from utils.ordenacao import ordenar_grupos_lista


def _agora() -> str:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")


def _parse_data(valor) -> pd.Timestamp | None:
    if valor is None or str(valor).strip() == "":
        return None
    return pd.to_datetime(str(valor).strip(), format="%d/%m/%Y", errors="coerce")


def _filtrar_disc_ciclo(df: pd.DataFrame, id_disciplina: str, id_ciclo: str) -> pd.DataFrame:
    if df.empty:
        return df
    return df[
        (df["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip())
        & (df["ID_Ciclo"].astype(str).str.strip() == str(id_ciclo).strip())
    ]


def _filtrar_disc_ciclo_sala(
    df: pd.DataFrame, id_disciplina: str, id_ciclo: str, sala: str
) -> pd.DataFrame:
    filtro = _filtrar_disc_ciclo(df, id_disciplina, id_ciclo)
    if filtro.empty or not sala:
        return filtro
    if "Sala" not in filtro.columns:
        return filtro
    return filtro[filtro["Sala"].astype(str).str.strip() == str(sala).strip()]


def grupos_da_sala(entrancia_disc: pd.DataFrame, sala: str) -> list[str]:
    filtro = entrancia_disc[entrancia_disc["Sala"].astype(str).str.strip() == str(sala).strip()]
    grupos = filtro["Grupo"].dropna().unique().astype(str).tolist()
    return ordenar_grupos_lista(grupos)


def obter_config_entregas(id_disciplina: str, id_ciclo: str) -> dict | None:
    try:
        df = ler_aba("Config_Entregas")
    except Exception:
        return None
    filtro = _filtrar_disc_ciclo(df, id_disciplina, id_ciclo)
    if filtro.empty:
        return None
    row = filtro.iloc[-1]
    return {
        "data_inicio": str(row.get("Data_Inicio", "")).strip(),
        "data_fim": str(row.get("Data_Fim", "")).strip(),
    }


def salvar_config_entregas(
    id_disciplina: str,
    id_ciclo: str,
    data_inicio: str,
    data_fim: str,
    email_professor: str,
):
    garantir_aba_avaliacao("Config_Entregas")
    ws = planilha.worksheet("Config_Entregas")
    ws.append_row(
        [
            id_disciplina,
            id_ciclo,
            data_inicio.strip(),
            data_fim.strip(),
            email_professor,
            _agora(),
        ]
    )
    limpar_cache_planilhas()


def avaliacao_entregas_aberta(id_disciplina: str, id_ciclo: str) -> tuple[bool, str]:
    config = obter_config_entregas(id_disciplina, id_ciclo)
    if not config or (not config["data_inicio"] and not config["data_fim"]):
        return True, ""

    hoje = pd.Timestamp(datetime.now(ZoneInfo("America/Sao_Paulo")).date())
    inicio = _parse_data(config["data_inicio"])
    fim = _parse_data(config["data_fim"])

    if inicio is not None and hoje < inicio.normalize():
        return False, f"Avaliação de entregas abre em **{config['data_inicio']}**."
    if fim is not None and hoje > fim.normalize():
        return False, f"Avaliação de entregas encerrou em **{config['data_fim']}**."
    return True, ""


def listar_grupos_avaliados(
    id_disciplina: str,
    id_ciclo: str,
    sala: str = "",
    email_avaliador: str | None = None,
) -> set[str]:
    """Grupos com avaliação no ciclo/sala. Se email_avaliador for informado, só as dele."""
    try:
        df = ler_aba("Avaliacao_Grupo")
    except Exception:
        return set()
    filtro = filtrar_avaliacoes_grupo(df, id_disciplina, id_ciclo, sala=sala or None)
    if filtro.empty:
        return set()
    if email_avaliador is not None:
        email = str(email_avaliador).strip().lower()
        # Sem e-mail válido: não atribuir avaliações de terceiros / legado a este usuário.
        if not email or email in {"nan", "none"}:
            return set()
        if "Email_Avaliador" not in filtro.columns:
            return set()
        filtro = filtro[
            filtro["Email_Avaliador"].astype(str).str.lower().str.strip() == email
        ]
        if filtro.empty:
            return set()
    return set(filtro["Grupo"].astype(str).str.strip().unique())


def carregar_ordem_apresentacao(
    id_disciplina: str, id_ciclo: str, sala: str
) -> dict[str, int]:
    try:
        df = ler_aba("Ordem_Apresentacao")
    except Exception:
        return {}
    filtro = _filtrar_disc_ciclo_sala(df, id_disciplina, id_ciclo, sala)
    if filtro.empty:
        return {}
    filtro = filtro.copy()
    filtro["Ordem"] = pd.to_numeric(filtro["Ordem"], errors="coerce")
    mapa: dict[str, int] = {}
    for _, row in filtro.iterrows():
        mapa[str(row["Grupo"]).strip()] = int(row["Ordem"])
    return mapa


def lista_ordenada_grupos(
    grupos: list[str], ordem_map: dict[str, int]
) -> list[str]:
    return ordenar_grupos(grupos, ordem_map)


def salvar_ordem_apresentacao(
    id_disciplina: str, id_ciclo: str, sala: str, ordens: dict[str, int]
):
    garantir_aba_avaliacao("Ordem_Apresentacao")
    try:
        df = ler_aba("Ordem_Apresentacao")
    except Exception:
        df = pd.DataFrame(columns=["ID_Disciplina", "ID_Ciclo", "Sala", "Grupo", "Ordem"])

    if df.empty:
        restante = df
    else:
        mesmo_escopo = (
            (df["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip())
            & (df["ID_Ciclo"].astype(str).str.strip() == str(id_ciclo).strip())
        )
        if "Sala" in df.columns:
            mesmo_escopo = mesmo_escopo & (df["Sala"].astype(str).str.strip() == str(sala).strip())
        restante = df[~mesmo_escopo]

    novas = []
    for grupo, ordem in sorted(ordens.items(), key=lambda x: x[1]):
        novas.append([id_disciplina, id_ciclo, str(sala), str(grupo), int(ordem)])

    ws = planilha.worksheet("Ordem_Apresentacao")
    ws.clear()
    ws.append_row(["ID_Disciplina", "ID_Ciclo", "Sala", "Grupo", "Ordem"])
    for _, row in restante.iterrows():
        vals = [str(row.get(c, "")) for c in ["ID_Disciplina", "ID_Ciclo", "Sala", "Grupo", "Ordem"]]
        ws.append_row(vals)
    if novas:
        ws.append_rows(novas)
    limpar_cache_planilhas()


def ordenar_grupos(grupos: list[str], ordem_map: dict[str, int]) -> list[str]:
    def chave(g):
        if g in ordem_map:
            return (0, ordem_map[g])
        try:
            return (1, float(g))
        except ValueError:
            return (2, g)

    return sorted(grupos, key=chave)


def proximo_grupo_pendente(
    grupos_ordenados: list[str],
    grupos_avaliados: set[str],
    grupo_atual: str | None = None,
) -> str | None:
    if grupo_atual and grupo_atual in grupos_ordenados:
        idx = grupos_ordenados.index(grupo_atual)
        for g in grupos_ordenados[idx + 1 :]:
            if g not in grupos_avaliados:
                return g
    for g in grupos_ordenados:
        if g not in grupos_avaliados:
            return g
    return grupos_ordenados[0] if grupos_ordenados else None


def disciplina_com_entregas_abertas(id_disciplina: str) -> bool:
    """True se algum ciclo da disciplina tem janela de entregas aberta hoje."""
    try:
        df_ciclos = ler_aba("Ciclos")
    except Exception:
        return False
    ciclos = df_ciclos[
        df_ciclos["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip()
    ]
    ciclos = ciclos_visiveis_avaliacao(ciclos, id_disciplina)
    for _, row in ciclos.iterrows():
        id_ciclo = str(row["ID_Ciclo"]).strip()
        aberta, _ = avaliacao_entregas_aberta(id_disciplina, id_ciclo)
        if aberta:
            return True
    return False
