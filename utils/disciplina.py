"""Helpers de UI para seleção de disciplina."""

import pandas as pd


def indice_disciplina_ativa(df_disc: pd.DataFrame, lista_nomes: list[str]) -> int:
    if df_disc.empty or not lista_nomes:
        return 0
    ativas = df_disc[
        df_disc["Status"].astype(str).str.strip().str.lower().isin(["ativo", "ativa", "sim", "s"])
    ]
    if not ativas.empty:
        nome = ativas.iloc[0]["Nome_Disciplina"]
        if nome in lista_nomes:
            return lista_nomes.index(nome)
    return 0


def id_disciplina_por_nome(df_disc: pd.DataFrame, nome: str) -> str:
    return str(df_disc[df_disc["Nome_Disciplina"] == nome].iloc[0]["ID_Disciplina"]).strip()
