"""Agregações da avaliação do curso (métricas, didática, NPS e textos)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from data.sheets import ler_aba


ITENS_METRICA = ("Auto Estudo", "Aulas ao Vivo", "Aplicabilidade", "Suporte")
ITEM_NPS = "NPS"
ITEM_DIDATICA = "Didática Professor"
ITENS_TEXTO = ("Que Bom", "Que Pena", "Que Tal")


def _texto(valor) -> str:
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    return str(valor).strip()


def carregar_respostas_curso() -> pd.DataFrame:
    try:
        df = ler_aba("Respostas_Curso")
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    renomear = {}
    if "ID do Ciclo" in out.columns and "ID_Ciclo" not in out.columns:
        renomear["ID do Ciclo"] = "ID_Ciclo"
    if "Email do Aluno" in out.columns and "Email_Aluno" not in out.columns:
        renomear["Email do Aluno"] = "Email_Aluno"
    if "Nome do Aluno" in out.columns and "Nome_Aluno" not in out.columns:
        renomear["Nome do Aluno"] = "Nome_Aluno"
    if renomear:
        out = out.rename(columns=renomear)
    if "ID_Ciclo" in out.columns:
        out["ID_Ciclo"] = out["ID_Ciclo"].astype(str).str.strip()
    if "Email_Aluno" in out.columns:
        out["Email_Aluno"] = out["Email_Aluno"].astype(str).str.strip().str.lower()
    if "Item" in out.columns:
        out["Item"] = out["Item"].astype(str).str.strip()
    if "Professor" in out.columns:
        out["Professor"] = out["Professor"].astype(str).str.strip()
    if "Disciplina" in out.columns:
        out["Disciplina"] = out["Disciplina"].astype(str).str.strip()
    if "Ciclo" in out.columns:
        out["Ciclo"] = out["Ciclo"].astype(str).str.strip()
    if "Resposta" in out.columns:
        out["Resposta"] = out["Resposta"]
    return out


def filtrar_respostas(
    df: pd.DataFrame,
    *,
    id_ciclo: str | None = None,
    disciplina: str | None = None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    out = df
    if id_ciclo and id_ciclo != "Todos":
        out = out[out["ID_Ciclo"] == str(id_ciclo).strip()]
    if disciplina and disciplina != "Todas":
        out = out[out["Disciplina"] == str(disciplina).strip()]
    return out


@dataclass(frozen=True)
class ResumoNps:
    nps: float | None
    respondentes: int
    promotores: int
    passivos: int
    detratores: int
    pct_promotores: float
    pct_passivos: float
    pct_detratores: float


def calcular_nps(notas: list[float] | pd.Series) -> ResumoNps:
    """NPS clássico: % promotores (9–10) − % detratores (0–6). Neutros 7–8 no denominador."""
    serie = pd.to_numeric(pd.Series(notas), errors="coerce").dropna()
    total = int(len(serie))
    if total == 0:
        return ResumoNps(None, 0, 0, 0, 0, 0.0, 0.0, 0.0)
    prom = int(((serie >= 9) & (serie <= 10)).sum())
    det = int((serie <= 6).sum())
    pas = int(((serie >= 7) & (serie <= 8)).sum())
    nps = (prom - det) / total * 100.0
    return ResumoNps(
        nps=round(nps, 1),
        respondentes=total,
        promotores=prom,
        passivos=pas,
        detratores=det,
        pct_promotores=round(100.0 * prom / total, 1),
        pct_passivos=round(100.0 * pas / total, 1),
        pct_detratores=round(100.0 * det / total, 1),
    )


def nps_do_recorte(df: pd.DataFrame) -> ResumoNps:
    if df is None or df.empty or "Item" not in df.columns:
        return calcular_nps([])
    bloco = df[df["Item"] == ITEM_NPS]
    return calcular_nps(bloco["Resposta"] if "Resposta" in bloco.columns else [])


def media_itens_metricas(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Item", "Média", "N"])
    bloco = df[df["Item"].isin(ITENS_METRICA)].copy()
    if bloco.empty:
        return pd.DataFrame(columns=["Item", "Média", "N"])
    bloco["Resposta"] = pd.to_numeric(bloco["Resposta"], errors="coerce")
    agg = (
        bloco.groupby("Item", sort=False)["Resposta"]
        .agg(Média="mean", N="count")
        .reset_index()
    )
    agg["Média"] = agg["Média"].round(2)
    ordem = {nome: i for i, nome in enumerate(ITENS_METRICA)}
    agg["_ord"] = agg["Item"].map(ordem)
    return agg.sort_values("_ord").drop(columns=["_ord"])


def media_didatica_professores(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Professor", "Média", "N"])
    bloco = df[df["Item"] == ITEM_DIDATICA].copy()
    if bloco.empty:
        return pd.DataFrame(columns=["Professor", "Média", "N"])
    bloco["Resposta"] = pd.to_numeric(bloco["Resposta"], errors="coerce")
    bloco = bloco[bloco["Professor"].astype(str).str.strip().ne("")]
    agg = (
        bloco.groupby("Professor")["Resposta"]
        .agg(Média="mean", N="count")
        .reset_index()
        .sort_values("Média", ascending=False)
    )
    agg["Média"] = agg["Média"].round(2)
    return agg


def textos_abertos(df: pd.DataFrame, item: str) -> pd.DataFrame:
    if df is None or df.empty or item not in ITENS_TEXTO:
        return pd.DataFrame(columns=["Aluno", "Texto"])
    bloco = df[df["Item"] == item].copy()
    if bloco.empty:
        return pd.DataFrame(columns=["Aluno", "Texto"])
    bloco["Texto"] = bloco["Resposta"].map(_texto)
    bloco = bloco[bloco["Texto"].ne("")]
    cols = []
    if "Nome_Aluno" in bloco.columns:
        bloco["Aluno"] = bloco["Nome_Aluno"].map(_texto)
        cols = ["Aluno", "Texto"]
    else:
        cols = ["Texto"]
    if "Ciclo" in bloco.columns:
        cols = ["Ciclo"] + cols
    return bloco[cols].reset_index(drop=True)


def contagem_respondentes(df: pd.DataFrame) -> int:
    if df is None or df.empty or "Email_Aluno" not in df.columns:
        return 0
    return int(df["Email_Aluno"].nunique())
