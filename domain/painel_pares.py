"""Situação da avaliação de pares por ciclo, para o painel inicial docente."""

from __future__ import annotations

import pandas as pd

from domain.ciclos import hoje_normalizado, ordenar_ciclos, preparar_ciclos
from utils.disciplina import normalizar_id

ABERTA = "aberta"
BLOQUEADA = "bloqueada"
FUTURA = "futura"
FUTURA_BLOQUEADA = "futura_bloqueada"
ENCERRADA = "encerrada"
SEM_JANELA = "sem_janela"


def _situacao(row: pd.Series, hoje: pd.Timestamp) -> str:
    ini, fim = row.get("Data início"), row.get("Data fim")
    inativo = str(row.get("Status", "")).strip().lower() == "inativo"
    if pd.isna(ini) or pd.isna(fim):
        return ABERTA if not inativo else SEM_JANELA
    if hoje < ini:
        return FUTURA_BLOQUEADA if inativo else FUTURA
    if hoje > fim:
        return ENCERRADA
    return BLOQUEADA if inativo else ABERTA


def _envios_por_ciclo(ids_ciclo: set[str], emails_turma: set[str]) -> dict[str, int]:
    from domain.pares import carregar_avaliacoes_pares

    try:
        df = carregar_avaliacoes_pares()
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    df = df[df["ID_Ciclo"].map(normalizar_id).isin(ids_ciclo)]
    df = df[df["Email_Avaliador"].astype(str).str.strip().str.lower().isin(emails_turma)]
    return df.groupby(df["ID_Ciclo"].map(normalizar_id))["Email_Avaliador"].nunique().to_dict()


def _emails_turma(id_disciplina: str) -> set[str]:
    from data.sheets import ler_aba

    try:
        df = ler_aba("Entrancia_Turma")
    except Exception:
        return set()
    df = df[df["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disciplina)]
    com_grupo = df["Grupo"].astype(str).str.strip().replace({"nan": "", "None": ""}).ne("")
    return set(df.loc[com_grupo, "Email_Pessoal"].astype(str).str.strip().str.lower())


def situacao_pares_disciplina(id_disciplina: str, hoje: pd.Timestamp | None = None) -> pd.DataFrame:
    """Uma linha por ciclo visível da disciplina (mesma leitura da tela do aluno)."""
    from data.sheets import ler_aba
    from domain.ciclos import ciclos_da_disciplina
    from domain.encontro_presencial import ciclos_visiveis_avaliacao

    hoje = hoje or hoje_normalizado()
    ciclos = ciclos_da_disciplina(preparar_ciclos(ler_aba("Ciclos")), id_disciplina)
    ciclos = ciclos_visiveis_avaliacao(ciclos, id_disciplina)
    if ciclos is None or ciclos.empty:
        return pd.DataFrame()
    ciclos = ordenar_ciclos(preparar_ciclos(ciclos))

    turma = _emails_turma(id_disciplina)
    ids = set(ciclos["ID_Ciclo"].map(normalizar_id))
    envios = _envios_por_ciclo(ids, turma)

    linhas = []
    for _, row in ciclos.iterrows():
        id_c = normalizar_id(row.get("ID_Ciclo"))
        linhas.append(
            {
                "ID_Ciclo": id_c,
                "Nome_Ciclo": str(row.get("Nome_Ciclo", "")).strip() or id_c,
                "Abertura": row.get("Data início"),
                "Encerramento": row.get("Data fim"),
                "Status": str(row.get("Status", "")).strip().lower(),
                "Situacao": _situacao(row, hoje),
                "Enviaram": int(envios.get(id_c, 0)),
                "Turma": len(turma),
            }
        )
    return pd.DataFrame(linhas)
