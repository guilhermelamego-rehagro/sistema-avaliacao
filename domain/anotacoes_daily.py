"""Anotações de orientação feitas nas dailies (por grupo e data)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from config import ABAS_AVALIACAO
from data.sheets import garantir_aba_avaliacao, ler_aba, salvar_aba
from domain.ciclos import ciclo_na_data, hoje_normalizado
from utils.datas import parse_data_planilha, parse_data_planilha_series
from utils.disciplina import normalizar_id

ABA = "Anotacoes_Daily"
COLUNAS = ABAS_AVALIACAO[ABA]


def _fmt_data(valor) -> str:
    parsed = parse_data_planilha(valor)
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).strftime("%d/%m/%Y")


def _agora() -> str:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")


def carregar_anotacoes() -> pd.DataFrame:
    garantir_aba_avaliacao(ABA)
    try:
        df = ler_aba(ABA)
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUNAS)
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for col in COLUNAS:
        if col not in out.columns:
            out[col] = ""
    out["ID_Disciplina"] = out["ID_Disciplina"].map(normalizar_id)
    out["ID_Ciclo"] = out["ID_Ciclo"].map(normalizar_id)
    out["Sala"] = out["Sala"].astype(str).str.strip()
    out["Grupo"] = out["Grupo"].astype(str).str.strip()
    out["Texto"] = out["Texto"].astype(str).replace({"nan": "", "None": ""}).str.strip()
    out["Data"] = out["Data"].map(_fmt_data)
    return out[COLUNAS]


def salvar_anotacao(
    *,
    dia: date,
    id_disciplina: str,
    sala: str,
    grupo: str,
    texto: str,
    usuario: dict,
) -> str | None:
    dia_txt = _fmt_data(dia)
    id_limpo = normalizar_id(id_disciplina)
    sala_txt = str(sala or "").strip()
    grupo_txt = str(grupo or "").strip()
    texto_limpo = str(texto or "").strip()
    if not dia_txt or not id_limpo:
        return "Informe a data e a disciplina."
    if not sala_txt:
        return "Selecione a sala."
    if not grupo_txt:
        return "Selecione o grupo."
    if not texto_limpo:
        return "Escreva a anotação da daily."

    id_ciclo, nome_ciclo = ciclo_na_data(id_limpo, dia)
    nova = {
        "Data": dia_txt,
        "ID_Disciplina": id_limpo,
        "ID_Ciclo": id_ciclo,
        "Nome_Ciclo": nome_ciclo,
        "Sala": sala_txt,
        "Grupo": grupo_txt,
        "Texto": texto_limpo,
        "Email_Orientador": str(usuario.get("email", "")).strip().lower(),
        "Nome_Orientador": str(usuario.get("nome", "")).strip(),
        "Data_Atualizacao": _agora(),
    }
    df = carregar_anotacoes()
    if df.empty:
        out = pd.DataFrame([nova], columns=COLUNAS)
    else:
        mask = (
            (df["Data"] == dia_txt)
            & (df["ID_Disciplina"] == id_limpo)
            & (df["Sala"] == sala_txt)
            & (df["Grupo"] == grupo_txt)
        )
        if mask.any():
            for col, valor in nova.items():
                df.loc[mask, col] = valor
            out = df
        else:
            out = pd.concat([df, pd.DataFrame([nova])], ignore_index=True)
    parsed = parse_data_planilha_series(out["Data"])
    out = out.assign(_ord=parsed).sort_values(["ID_Disciplina", "_ord", "Sala", "Grupo"])
    out = out.drop(columns=["_ord"])
    salvar_aba(ABA, out, COLUNAS)
    return None


def anotacoes_do_grupo(
    id_disciplina: str,
    sala: str | None = None,
    grupo: str | None = None,
    id_ciclo: str | None = None,
) -> pd.DataFrame:
    df = carregar_anotacoes()
    if df.empty:
        return df
    out = df[df["ID_Disciplina"] == normalizar_id(id_disciplina)].copy()
    if sala and sala not in {"", "Todas"}:
        out = out[out["Sala"] == str(sala).strip()]
    if grupo and grupo not in {"", "Todos"}:
        out = out[out["Grupo"] == str(grupo).strip()]
    if id_ciclo:
        out = out[out["ID_Ciclo"] == normalizar_id(id_ciclo)]
    if out.empty:
        return out
    parsed = parse_data_planilha_series(out["Data"])
    out = out.assign(_ord=parsed).sort_values(["_ord", "Sala", "Grupo"], ascending=[False, True, True])
    return out.drop(columns=["_ord"]).reset_index(drop=True)


def datas_dailies_disciplina(id_disciplina: str) -> list[date]:
    from domain.calendario import carregar_calendario

    df = carregar_calendario("dailies")
    id_limpo = normalizar_id(id_disciplina)
    bloco = df[df["ID_Disciplina"].map(normalizar_id) == id_limpo]
    saida: list[date] = []
    for valor in bloco["Data"]:
        parsed = parse_data_planilha(valor)
        if pd.isna(parsed):
            continue
        saida.append(pd.Timestamp(parsed).date())
    return sorted(set(saida))


def data_daily_padrao(id_disciplina: str) -> date:
    hoje = hoje_normalizado().date()
    datas = datas_dailies_disciplina(id_disciplina)
    if hoje in datas:
        return hoje
    passadas = [d for d in datas if d <= hoje]
    if passadas:
        return passadas[-1]
    if datas:
        return datas[0]
    return hoje
