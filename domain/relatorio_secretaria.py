"""Relatório de notas finais para a secretaria.

Retrato estático do boletim geral (``montar_painel_boletins_disciplina``) sem o detalhamento de
orientador, pares e grupo. É publicado quando a nota final é liberada e só muda quando um professor
publica uma atualização; cada diferença entre retratos vai para o histórico.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

_TZ = ZoneInfo("America/Sao_Paulo")
_DETALHE = re.compile(r" (Ori|Par|Grp)\d*$")
_FORA = {"Email", "Nome", "Turma", "Grupo", "Sala", "Pres.%", "Final", "Status"}
TEXTO = ("Nome", "Turma", "Status")
ROTULOS = {"Status": "Situação"}


def colunas_relatorio(painel: pd.DataFrame) -> list[str]:
    notas = [c for c in painel.columns if c not in _FORA and not _DETALHE.search(c)]
    return ["Nome", "Turma", *notas, "Pres.%", "Final", "Status"]


def _casas(coluna: str) -> int:
    return 0 if coluna == "Final" else 1


def _valor(coluna: str, valor):
    vazio = valor is None or (isinstance(valor, float) and math.isnan(valor))
    if coluna in TEXTO:
        return "" if vazio else str(valor).strip()
    return None if vazio else round(float(valor), _casas(coluna))


def montar_relatorio(painel: pd.DataFrame) -> dict:
    """Colunas, linhas (uma por aluno, com ``Email`` como chave) e legendas das siglas mantidas."""
    colunas = colunas_relatorio(painel)
    linhas = [
        {"Email": str(r["Email"]).strip().lower(), **{c: _valor(c, r.get(c)) for c in colunas}}
        for r in painel.to_dict("records")
    ]
    legendas = [l for l in painel.attrs.get("legendas_colunas") or [] if l.split(" = ")[0] in colunas]
    return {"colunas": colunas, "linhas": linhas, "legendas": legendas}


def _texto(coluna: str, valor) -> str:
    if valor is None or valor == "":
        return ""
    if coluna in TEXTO:
        return str(valor)
    return f"{float(valor):.{_casas(coluna)}f}".replace(".", ",")


def diferencas(anterior: dict, atual: dict) -> list[dict]:
    """Uma entrada por aluno e campo que mudou, mais alunos incluídos ou removidos."""
    antes = {l["Email"]: l for l in anterior.get("linhas") or []}
    depois = {l["Email"]: l for l in atual["linhas"]}
    campos = list(dict.fromkeys([*atual["colunas"], *(anterior.get("colunas") or [])]))
    saida: list[dict] = []
    for email, nova in depois.items():
        ident = {"email": email, "nome": nova.get("Nome", ""), "turma": nova.get("Turma", "")}
        velha = antes.get(email)
        if velha is None:
            saida.append({**ident, "campo": "Aluno", "antes": "", "depois": "Incluído no relatório"})
            continue
        for campo in campos:
            a, d = _texto(campo, velha.get(campo)), _texto(campo, nova.get(campo))
            if a != d:
                saida.append({**ident, "campo": ROTULOS.get(campo, campo), "antes": a, "depois": d})
    for email, velha in antes.items():
        if email not in depois:
            saida.append(
                {
                    "email": email,
                    "nome": velha.get("Nome", ""),
                    "turma": velha.get("Turma", ""),
                    "campo": "Aluno",
                    "antes": "No relatório",
                    "depois": "Removido do relatório",
                }
            )
    return sorted(saida, key=lambda d: (str(d["turma"]), str(d["nome"]).lower()))


def publicar_relatorio(id_disciplina: str, nome_disciplina: str, painel: pd.DataFrame, usuario: dict) -> int:
    """Grava o retrato atual. Retorna quantas alterações foram registradas (0 se nada mudou)."""
    from data import supabase_relatorio_secretaria as repo

    atual = montar_relatorio(painel)
    anterior = repo.ler(id_disciplina)
    if anterior is None:
        alteracoes = [
            {
                "email": "",
                "nome": "",
                "turma": "",
                "campo": "Relatório",
                "antes": "",
                "depois": f"Publicado com {len(atual['linhas'])} alunos",
            }
        ]
    else:
        alteracoes = diferencas(anterior, atual)
        if not alteracoes:
            return 0
    repo.salvar({"id_disciplina": id_disciplina, "nome_disciplina": nome_disciplina, **atual}, alteracoes, usuario)
    return len(alteracoes)


def fmt_data_hora(valor) -> str:
    ts = pd.to_datetime(valor, utc=True, errors="coerce")
    return "" if pd.isna(ts) else ts.tz_convert(_TZ).strftime("%d/%m/%Y %H:%M")


def momento(valor) -> datetime | None:
    ts = pd.to_datetime(valor, utc=True, errors="coerce")
    return None if pd.isna(ts) else ts.to_pydatetime()
