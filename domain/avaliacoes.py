"""Persistência de avaliações de grupo e orientador."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from config import ABAS_AVALIACAO
from data.sheets import ler_aba, limpar_cache_planilhas, planilha

_COLUNAS_GRUPO = ABAS_AVALIACAO["Avaliacao_Grupo"]


def _agora() -> str:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")


def _normalizar_df_grupo(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out.columns = out.columns.astype(str).str.strip()
    return out


def _sala_vazia(serie: pd.Series) -> pd.Series:
    return serie.astype(str).str.strip().isin(["", "nan", "none", "NaN", "None"])


def _garantir_header_avaliacao_grupo(ws) -> list[str]:
    headers = [str(h).strip() for h in ws.row_values(1) if str(h).strip()]
    if not headers:
        ws.append_row(_COLUNAS_GRUPO)
        return list(_COLUNAS_GRUPO)
    if "Sala" not in headers and "ID_Disciplina" in headers:
        idx = headers.index("ID_Disciplina") + 1
        headers.insert(idx, "Sala")
        ws.update(range_name="A1", values=[headers])
    return headers


def filtrar_avaliacoes_grupo(
    df: pd.DataFrame,
    id_disciplina: str | None = None,
    id_ciclo: str | None = None,
    grupo: str | None = None,
    sala: str | None = None,
) -> pd.DataFrame:
    filtro = _normalizar_df_grupo(df)
    if filtro.empty:
        return filtro

    if id_disciplina is not None:
        filtro = filtro[
            filtro["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip()
        ]
    if id_ciclo is not None:
        filtro = filtro[
            filtro["ID_Ciclo"].astype(str).str.strip() == str(id_ciclo).strip()
        ]
    if grupo is not None:
        filtro = filtro[
            filtro["Grupo"].astype(str).str.strip() == str(grupo).strip()
        ]
    if sala and "Sala" in filtro.columns:
        com_sala = filtro[filtro["Sala"].astype(str).str.strip() == str(sala).strip()]
        legado = filtro[_sala_vazia(filtro["Sala"])]
        if not com_sala.empty:
            filtro = com_sala
        elif not legado.empty:
            filtro = legado
        else:
            filtro = com_sala
    return filtro


def parse_nota_entrega(valor) -> float | None:
    if valor is None or str(valor).strip() == "":
        return None
    try:
        nota = round(float_nota_planilha(valor), 1)
    except (ValueError, TypeError):
        return None
    if 0 <= nota <= 5:
        return nota
    return None


def float_nota_planilha(valor) -> float:
    """Converte nota da planilha (aceita 0,5 ou 0.5)."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto:
        return 0.0
    if "," in texto:
        if "." in texto:
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", ".")
    return float(texto)


def formatar_nota_entrega(nota: float) -> str:
    """Exibe nota com vírgula decimal (padrão BR)."""
    return f"{float(nota):.1f}".replace(".", ",")


def salvar_avaliacao_grupo(
    id_ciclo: str,
    nome_ciclo: str,
    id_disciplina: str,
    sala: str,
    grupo: str,
    nota_apresentacao: float,
    nota_conteudo: float,
    comentario: str,
    email_avaliador: str,
    nome_avaliador: str,
    tipo: str = "Ciclo",
):
    nota_total = round(float(nota_apresentacao) + float(nota_conteudo), 1)
    ws = planilha.worksheet("Avaliacao_Grupo")
    headers = _garantir_header_avaliacao_grupo(ws)
    dados = {
        "Data": _agora(),
        "ID_Ciclo": id_ciclo,
        "Nome_Ciclo": nome_ciclo,
        "ID_Disciplina": id_disciplina,
        "Sala": sala,
        "Grupo": grupo,
        "Nota_Apresentacao": nota_apresentacao,
        "Nota_Conteudo": nota_conteudo,
        "Nota_Total": nota_total,
        "Comentario": comentario,
        "Email_Avaliador": email_avaliador,
        "Nome_Avaliador": nome_avaliador,
        "Tipo": tipo,
    }
    linha = [dados.get(col, "") for col in headers]
    ws.append_row(linha)
    limpar_cache_planilhas()
    return nota_total


def salvar_avaliacao_orientador(
    id_ciclo: str,
    nome_ciclo: str,
    id_disciplina: str,
    email_aluno: str,
    nome_aluno: str,
    grupo: str,
    nota: float,
    email_orientador: str,
    tipo: str = "Ciclo",
):
    ws = planilha.worksheet("Avaliacao_Orientador")
    ws.append_row(
        [
            _agora(),
            id_ciclo,
            nome_ciclo,
            id_disciplina,
            email_aluno,
            nome_aluno,
            grupo,
            email_orientador,
            nota,
            tipo,
        ]
    )
    limpar_cache_planilhas()


def obter_avaliacao_grupo(
    id_ciclo: str,
    grupo: str,
    sala: str = "",
    id_disciplina: str | None = None,
) -> dict | None:
    try:
        df = ler_aba("Avaliacao_Grupo")
    except Exception:
        return None
    if df.empty:
        return None

    filtro = filtrar_avaliacoes_grupo(df, id_disciplina, id_ciclo, grupo, sala or None)
    if filtro.empty:
        return None
    if "Data" in filtro.columns:
        filtro = filtro.copy()
        filtro["_ordem"] = pd.to_datetime(filtro["Data"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
        filtro = filtro.sort_values("_ordem", na_position="last")
    row = filtro.iloc[-1]
    return {
        "nota_apresentacao": float_nota_planilha(row.get("Nota_Apresentacao", 0)),
        "nota_conteudo": float_nota_planilha(row.get("Nota_Conteudo", 0)),
        "nota_total": float_nota_planilha(row.get("Nota_Total", 0)),
        "comentario": str(row.get("Comentario", "")),
    }


def obter_nota_orientador(id_ciclo: str, email_aluno: str) -> float | None:
    try:
        df = ler_aba("Avaliacao_Orientador")
    except Exception:
        return None
    if df.empty:
        return None

    filtro = df[
        (df["ID_Ciclo"].astype(str).str.strip() == str(id_ciclo).strip())
        & (df["Email_Aluno"].astype(str).str.lower().str.strip() == str(email_aluno).lower().strip())
    ]
    if filtro.empty:
        return None
    if "Data" in filtro.columns:
        filtro = filtro.copy()
        filtro["_ordem"] = pd.to_datetime(filtro["Data"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
        filtro = filtro.sort_values("_ordem", na_position="last")
    return float_nota_planilha(filtro.iloc[-1]["Nota"])


def carregar_mapa_notas_orientador(id_disciplina: str) -> dict[tuple[str, str], float]:
    """Retorna {(email, id_ciclo): nota} com a última nota lançada por aluno/ciclo."""
    try:
        df = ler_aba("Avaliacao_Orientador")
    except Exception:
        return {}
    if df.empty:
        return {}

    df = df[df["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip()]
    if "Data" in df.columns:
        df = df.copy()
        df["_ordem"] = pd.to_datetime(df["Data"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
        df = df.sort_values("_ordem", na_position="last")
    mapa: dict[tuple[str, str], float] = {}
    for (email, id_ciclo), grupo in df.groupby(
        [df["Email_Aluno"].astype(str).str.lower().str.strip(), df["ID_Ciclo"].astype(str).str.strip()]
    ):
        mapa[(email, id_ciclo)] = float_nota_planilha(grupo.iloc[-1]["Nota"])
    return mapa


def carregar_mapa_avaliacoes_grupo(id_disciplina: str) -> dict[tuple[str, str, str], dict]:
    """Retorna {(grupo, sala, id_ciclo): última avaliação do grupo}."""
    try:
        df = ler_aba("Avaliacao_Grupo")
    except Exception:
        return {}
    if df.empty:
        return {}

    df = filtrar_avaliacoes_grupo(df, id_disciplina=id_disciplina)
    if df.empty:
        return {}

    if "Sala" not in df.columns:
        df = df.copy()
        df["Sala"] = ""

    if "Data" in df.columns:
        df = df.copy()
        df["_ordem"] = pd.to_datetime(df["Data"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
        df = df.sort_values("_ordem", na_position="last")

    mapa: dict[tuple[str, str, str], dict] = {}
    for (grupo, sala, id_ciclo), grupo_df in df.groupby(
        [
            df["Grupo"].astype(str).str.strip(),
            df["Sala"].astype(str).str.strip(),
            df["ID_Ciclo"].astype(str).str.strip(),
        ]
    ):
        row = grupo_df.iloc[-1]
        mapa[(grupo, sala, id_ciclo)] = {
            "nota_apresentacao": float_nota_planilha(row.get("Nota_Apresentacao", 0)),
            "nota_conteudo": float_nota_planilha(row.get("Nota_Conteudo", 0)),
            "nota_total": float_nota_planilha(row.get("Nota_Total", 0)),
        }
    return mapa


def buscar_avaliacao_grupo_mapa(
    mapa: dict[tuple[str, str, str], dict],
    grupo: str,
    sala: str,
    id_ciclo: str,
) -> dict | None:
    grupo = str(grupo).strip()
    sala = str(sala).strip()
    id_ciclo = str(id_ciclo).strip()
    return mapa.get((grupo, sala, id_ciclo)) or mapa.get((grupo, "", id_ciclo))


def formatar_nota_grid(nota: float) -> str:
    """Exibe nota com uma casa decimal (evita 9.9 virar 99)."""
    return f"{float(nota):.1f}"


def parse_nota_orientador(valor) -> float | None:
    if valor is None:
        return None
    texto = str(valor).strip().replace(",", ".")
    if not texto:
        return None
    try:
        nota = round(float(texto), 1)
    except ValueError:
        return None
    if 0 <= nota <= 10:
        return nota
    return None


def importar_atividades_canvas(df_import: pd.DataFrame, id_disciplina: str) -> int:
    ws = planilha.worksheet("Atividades_Individuais")
    agora = _agora()
    linhas = []
    for _, row in df_import.iterrows():
        linhas.append(
            [
                id_disciplina,
                str(row.get("Semana", "")),
                str(row.get("Atividade", "")),
                str(row.get("Email_Aluno", "")).strip().lower(),
                str(row.get("Nome_Aluno", "")),
                float(row.get("Nota", 0)),
                "Canvas",
                agora,
            ]
        )
    if linhas:
        ws.append_rows(linhas)
        limpar_cache_planilhas()
    return len(linhas)
