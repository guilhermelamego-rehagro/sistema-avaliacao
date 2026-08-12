"""Conversão de datas vindas do Google Sheets (texto ou serial numérico)."""

from __future__ import annotations

import pandas as pd

_ORIGEM_SHEETS = "1899-12-30"
_LIMITE_SERIAL = 20000  # ~1954; abaixo disso não é data de planilha


def parse_data_planilha(valor) -> pd.Timestamp:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return pd.NaT
    if isinstance(valor, pd.Timestamp):
        return valor
    if isinstance(valor, (int, float)):
        if valor >= _LIMITE_SERIAL:
            return pd.to_datetime(valor, unit="D", origin=_ORIGEM_SHEETS, errors="coerce")
        return pd.NaT
    texto = str(valor).strip()
    if not texto or texto.lower() in ("nan", "none", ""):
        return pd.NaT
    if "/" in texto:
        return pd.to_datetime(texto, format="%d/%m/%Y", errors="coerce")
    try:
        num = float(texto.replace(",", "."))
        if num >= _LIMITE_SERIAL:
            return pd.to_datetime(num, unit="D", origin=_ORIGEM_SHEETS, errors="coerce")
    except ValueError:
        pass
    return pd.to_datetime(texto, errors="coerce")


def parse_data_planilha_series(serie: pd.Series) -> pd.Series:
    return serie.map(parse_data_planilha)
