"""Ordenação natural de rótulos de grupo (1, 2, … 10, depois texto)."""

from __future__ import annotations

import pandas as pd


def chave_ordenacao_grupo(valor) -> tuple:
    texto = str(valor).strip()
    if not texto:
        return (2, "")
    try:
        return (0, float(texto))
    except ValueError:
        return (1, texto.lower())


def ordenar_grupos_lista(grupos: list[str]) -> list[str]:
    return sorted(grupos, key=chave_ordenacao_grupo)


def ordenar_df_grupos(
    df: pd.DataFrame,
    col_grupo: str = "Grupo",
    col_sala: str = "Sala",
) -> pd.DataFrame:
    """Ordena por sala e grupo (1, 2, … 10). Grupos numéricos viram int para sort no grid."""
    if df.empty:
        return df
    out = df.copy()
    chaves = out[col_grupo].map(chave_ordenacao_grupo)
    out["_og_t"] = chaves.map(lambda x: x[0])
    out["_og_v"] = chaves.map(lambda x: x[1])
    out = out.sort_values(by=[col_sala, "_og_t", "_og_v"], kind="stable")
    nums = pd.to_numeric(out[col_grupo], errors="coerce")
    if nums.notna().all():
        out[col_grupo] = nums.astype(int)
    return out.drop(columns=["_og_t", "_og_v"]).reset_index(drop=True)
