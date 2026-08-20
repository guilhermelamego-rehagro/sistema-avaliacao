"""Status das avaliações do aluno para a tela de início."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from data.sheets import ler_aba
from domain.ciclos import ciclos_da_disciplina, hoje_normalizado, preparar_ciclos
from domain.encontro_presencial import ciclos_visiveis_avaliacao, escolher_ciclo_aberto

StatusTarefa = Literal["pendente", "feito", "perdido", "indisponivel"]


@dataclass(frozen=True)
class ResumoTarefa:
    status: StatusTarefa
    titulo: str
    mensagem: str
    nome_ciclo: str = ""


def _disciplina_ativa() -> tuple[str, str] | None:
    df_disc = ler_aba("Disciplinas")
    ativa = df_disc[df_disc["Status"].astype(str).str.strip().str.lower() == "ativo"]
    if ativa.empty:
        return None
    row = ativa.iloc[0]
    return str(row["ID_Disciplina"]).strip(), str(row["Nome_Disciplina"]).strip()


def _ultimo_ciclo_encerrado(ciclos: pd.DataFrame, hoje: pd.Timestamp) -> pd.Series | None:
    if ciclos.empty:
        return None
    encerrados = ciclos[
        ciclos["Data fim"].notna() & (ciclos["Data fim"] < hoje)
    ].sort_values("Data fim")
    if encerrados.empty:
        return None
    return encerrados.iloc[-1]


def _aluno_votou_pares(df_aval: pd.DataFrame, id_ciclo: str, email: str) -> bool:
    if df_aval.empty:
        return False
    mask = (
        (df_aval["ID_Ciclo"].astype(str).str.strip() == id_ciclo)
        & (df_aval["Email_Avaliador"].astype(str).str.lower().str.strip() == email.lower().strip())
    )
    return not df_aval[mask].empty


def _aluno_respondeu_curso(df_respostas: pd.DataFrame, id_ciclo: str, email: str) -> bool:
    if df_respostas.empty:
        return False
    mask = (
        (df_respostas["ID do Ciclo"].astype(str).str.strip() == id_ciclo)
        & (df_respostas["Email do Aluno"].astype(str).str.lower().str.strip() == email.lower().strip())
    )
    return not df_respostas[mask].empty


def status_avaliacao_pares(email_aluno: str) -> ResumoTarefa:
    hoje = hoje_normalizado()
    disc = _disciplina_ativa()
    if not disc:
        return ResumoTarefa(
            "indisponivel",
            "Pares — avaliar",
            "Nenhuma disciplina ativa no momento.",
        )

    id_disc, nome_disc = disc
    df_ciclos = preparar_ciclos(ler_aba("Ciclos"))
    ciclos_disc = ciclos_visiveis_avaliacao(ciclos_da_disciplina(df_ciclos, id_disc), id_disc)
    df_aval = ler_aba("Avaliacoes")

    ciclo = escolher_ciclo_aberto(ciclos_disc, id_disc)
    if ciclo is not None:
        id_ciclo = str(ciclo["ID_Ciclo"]).strip()
        nome_ciclo = str(ciclo["Nome_Ciclo"]).strip()
        if _aluno_votou_pares(df_aval, id_ciclo, email_aluno):
            return ResumoTarefa(
                "feito",
                "Pares — avaliar",
                f"Você já enviou suas avaliações de pares para {nome_ciclo}.",
                nome_ciclo,
            )
        return ResumoTarefa(
            "pendente",
            "Pares — avaliar",
            f"Avaliação aberta: {nome_ciclo} ({nome_disc}).",
            nome_ciclo,
        )

    ultimo = _ultimo_ciclo_encerrado(ciclos_disc, hoje)
    if ultimo is not None:
        id_ciclo = str(ultimo["ID_Ciclo"]).strip()
        nome_ciclo = str(ultimo["Nome_Ciclo"]).strip()
        if not _aluno_votou_pares(df_aval, id_ciclo, email_aluno):
            return ResumoTarefa(
                "perdido",
                "Pares — avaliar",
                f"A janela de {nome_ciclo} encerrou e sua avaliação não foi registrada.",
                nome_ciclo,
            )

    return ResumoTarefa(
        "indisponivel",
        "Pares — avaliar",
        "Nenhuma avaliação de pares aberta no momento.",
    )


def status_avaliacao_curso(email_aluno: str) -> ResumoTarefa:
    disc = _disciplina_ativa()
    if not disc:
        return ResumoTarefa(
            "indisponivel",
            "Avaliação do curso",
            "Nenhuma disciplina ativa no momento.",
        )

    id_disc, _nome_disc = disc
    df_ciclos = preparar_ciclos(ler_aba("Ciclos"))
    ciclos_disc = ciclos_visiveis_avaliacao(ciclos_da_disciplina(df_ciclos, id_disc), id_disc)
    df_respostas = ler_aba("Respostas_Curso")

    ciclo = escolher_ciclo_aberto(ciclos_disc, id_disc)
    if ciclo is not None:
        id_ciclo = str(ciclo["ID_Ciclo"]).strip()
        nome_ciclo = str(ciclo["Nome_Ciclo"]).strip()
        if _aluno_respondeu_curso(df_respostas, id_ciclo, email_aluno):
            return ResumoTarefa(
                "feito",
                "Avaliação do curso",
                f"Você já respondeu a avaliação do curso para {nome_ciclo}.",
                nome_ciclo,
            )
        return ResumoTarefa(
            "pendente",
            "Avaliação do curso",
            f"Avaliação do curso aberta: {nome_ciclo}.",
            nome_ciclo,
        )

    return ResumoTarefa(
        "indisponivel",
        "Avaliação do curso",
        "Nenhuma avaliação do curso aberta no momento.",
    )
