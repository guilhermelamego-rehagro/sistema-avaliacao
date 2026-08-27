"""Ordenação natural de rótulos de grupo (1, 2, … 10, depois texto)
e nomes sem considerar acento (Ânderson junto de Anderson)."""

from __future__ import annotations

import unicodedata

import pandas as pd


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def chave_ordenacao_texto(valor) -> str:
    """Chave alfabética casefold + sem acento."""
    return _sem_acento(str(valor or "")).casefold().strip()


def chave_ordenacao_grupo(valor) -> tuple:
    texto = str(valor).strip()
    if not texto:
        return (2, 0, "")
    try:
        n = float(texto.replace(",", "."))
        if n == int(n):
            return (0, int(n), "")
        return (0, n, "")
    except ValueError:
        return (1, 0, chave_ordenacao_texto(texto))


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
    out["_og_s"] = chaves.map(lambda x: x[2])
    out = out.sort_values(by=[col_sala, "_og_t", "_og_v", "_og_s"], kind="stable")
    nums = pd.to_numeric(out[col_grupo], errors="coerce")
    if nums.notna().all():
        out[col_grupo] = nums.astype(int)
    return out.drop(columns=["_og_t", "_og_v", "_og_s"]).reset_index(drop=True)
