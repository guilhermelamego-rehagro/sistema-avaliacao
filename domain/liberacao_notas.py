"""Liberação da nota final parcial da disciplina para visualização do aluno."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from data.sheets import garantir_aba_avaliacao, ler_aba, limpar_cache_planilhas, planilha


def _agora() -> str:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")


def notas_finais_liberadas(id_disciplina: str) -> bool:
    try:
        df = ler_aba("Config_Liberacao_Notas")
    except Exception:
        return False
    if df.empty:
        return False
    filtro = df[df["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip()]
    if filtro.empty:
        return False
    ultimo = str(filtro.iloc[-1].get("Liberado", "")).strip().lower()
    return ultimo in {"sim", "s", "true", "1", "liberado", "liberada"}


def salvar_liberacao_notas(
    id_disciplina: str,
    liberado: bool,
    email_responsavel: str,
    nome_responsavel: str,
):
    garantir_aba_avaliacao("Config_Liberacao_Notas")
    ws = planilha.worksheet("Config_Liberacao_Notas")
    ws.append_row(
        [
            str(id_disciplina).strip(),
            "Sim" if liberado else "Não",
            _agora(),
            email_responsavel,
            nome_responsavel,
        ]
    )
    limpar_cache_planilhas()
