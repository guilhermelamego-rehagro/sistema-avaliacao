"""Conversão de datas vindas do Google Sheets (texto ou serial numérico)
e formatação amigável no fuso da instituição (America/Sao_Paulo)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

_ORIGEM_SHEETS = "1899-12-30"
_LIMITE_SERIAL = 20000  # ~1954; abaixo disso não é data de planilha
_TZ_INSTITUICAO = ZoneInfo("America/Sao_Paulo")


def formatar_datetime_br(valor, *, com_segundos: bool = False) -> str:
    """UTC/ISO → dd/mm/aaaa HH:MM (fuso America/Sao_Paulo, GMT-3)."""
    if valor is None or valor == "":
        return ""
    if isinstance(valor, datetime):
        dt = valor
    else:
        texto = str(valor).strip()
        if not texto or texto.lower() in {"nan", "none", "nat"}:
            return ""
        try:
            dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        except ValueError:
            ts = pd.to_datetime(texto, errors="coerce", utc=True)
            if pd.isna(ts):
                return texto
            dt = ts.to_pydatetime()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    local = dt.astimezone(_TZ_INSTITUICAO)
    if com_segundos:
        return local.strftime("%d/%m/%Y %H:%M:%S")
    return local.strftime("%d/%m/%Y %H:%M")


def parse_data_planilha(valor) -> pd.Timestamp:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return pd.NaT
    if isinstance(valor, pd.Timestamp):
        return valor
    if hasattr(valor, "year") and hasattr(valor, "month") and hasattr(valor, "day"):
        try:
            return pd.Timestamp(valor)
        except Exception:
            return pd.NaT
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
