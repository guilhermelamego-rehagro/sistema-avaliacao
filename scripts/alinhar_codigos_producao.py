"""Alinha códigos antigos de disciplina/ciclo na planilha de produção.

Uso (na pasta sistema-avaliacao):
    python scripts/alinhar_codigos_producao.py
"""

from __future__ import annotations

import re
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from config import ABAS_AVALIACAO
from domain.cadastros import _renomear_colunas_df

PARES = [("20262GEN", "GENT"), ("20263TRI", "TRIB")]
ABAS = [
    "Ciclos",
    "Config_Professores",
    "Config_Professores_Disciplina",
    "Entrancia_Turma",
    "Avaliacoes",
    "Respostas_Curso",
] + list(ABAS_AVALIACAO.keys())


def _conectar():
    secrets = tomllib.loads((ROOT / ".streamlit" / "secrets.toml").read_text(encoding="utf-8"))
    escopo = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    cli = gspread.authorize(
        ServiceAccountCredentials.from_json_keyfile_dict(secrets["gcp_service_account"], escopo)
    )
    return cli.open_by_key(secrets["planilhas"]["id_producao"])


def _ordem_ciclo(nome: str) -> str:
    texto = str(nome or "").strip().lower()
    if "presencial" in texto or "entrega" in texto:
        return "5"
    match = re.search(r"(\d+)", texto)
    return match.group(1) if match else ""


def _gravar(ws, df: pd.DataFrame):
    colunas = [str(c) for c in df.columns]
    if df.empty:
        linhas = []
    else:
        limpo = df.fillna("").astype(str).replace({"nan": "", "None": "", "<NA>": ""})
        linhas = limpo.values.tolist()
    ws.clear()
    ws.update(range_name="A1", values=[colunas] + linhas)


def main():
    livro = _conectar()
    abas_existentes = {ws.title: ws for ws in livro.worksheets()}
    for antigo, novo in PARES:
        print(f"=== {antigo} → {novo}")
        for nome in ABAS:
            ws = abas_existentes.get(nome)
            if ws is None:
                continue
            recs = ws.get_all_records()
            if not recs:
                continue
            df = pd.DataFrame(recs)
            atualizado, n = _renomear_colunas_df(df, antigo, novo)
            extra_ordem = False
            if nome == "Ciclos" and "Ordem" not in atualizado.columns:
                atualizado["Ordem"] = atualizado.get(
                    "Nome_Ciclo", pd.Series("", index=atualizado.index)
                ).map(_ordem_ciclo)
                extra_ordem = True
            if n == 0 and not extra_ordem:
                continue
            print(f"  {nome}: {n} célula(s)")
            _gravar(ws, atualizado)
            time.sleep(8)

    ciclos = abas_existentes["Ciclos"].get_all_records()
    print("Ciclos depois:", Counter((r.get("ID_Disciplina"), r.get("ID_Ciclo")) for r in ciclos))


if __name__ == "__main__":
    main()
