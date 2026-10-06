"""Feedback do aluno por ciclo no Supabase (teste e produção).

Tabela própria (``feedback_ciclo``), sem relação com as planilhas.
"""

from __future__ import annotations

from datetime import datetime, timezone

from auth.supabase_auth import cliente_admin

TABELA = "feedback_ciclo"
_COLUNAS = (
    "email,id_disciplina,id_ciclo,nome_ciclo,conteudo,mensagem,um_a_um,"
    "publicado_em,autor_email,autor_nome,atualizado_em"
)


class FeedbackIndisponivel(RuntimeError):
    """Tabela ausente ou Supabase fora do ar."""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def listar_do_ciclo(id_ciclo: str) -> list[dict]:
    try:
        return (
            cliente_admin().table(TABELA).select(_COLUNAS).eq("id_ciclo", id_ciclo).limit(5000).execute().data
            or []
        )
    except Exception as exc:
        raise FeedbackIndisponivel("Leitura de feedback indisponível.") from exc


def listar_publicados_do_aluno(email: str) -> list[dict]:
    """Sem a marcação de 1x1, que é só da equipe docente."""
    try:
        return (
            cliente_admin()
            .table(TABELA)
            .select("id_ciclo,nome_ciclo,conteudo,mensagem,publicado_em,autor_nome")
            .eq("email", email)
            .filter("publicado_em", "not.is", "null")
            .order("publicado_em", desc=True)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        raise FeedbackIndisponivel("Leitura de feedback indisponível.") from exc


def _upsert(linhas: list[dict]) -> None:
    if not linhas:
        return
    agora = _agora()
    try:
        cliente_admin().table(TABELA).upsert(
            [{**linha, "atualizado_em": agora} for linha in linhas],
            on_conflict="email,id_ciclo",
            default_to_null=False,
        ).execute()
    except Exception as exc:
        raise FeedbackIndisponivel("Gravação de feedback indisponível.") from exc


def salvar_rascunhos(linhas: list[dict]) -> None:
    """Mensagem e 1x1, sem mexer no que já foi publicado."""
    _upsert(linhas)


def publicar(linhas: list[dict]) -> None:
    """Grava o retrato do feedback e marca como publicado agora."""
    agora = _agora()
    _upsert([{**linha, "publicado_em": agora} for linha in linhas])


def despublicar(id_ciclo: str, emails: list[str]) -> None:
    if not emails:
        return
    try:
        cliente_admin().table(TABELA).update({"publicado_em": None, "atualizado_em": _agora()}).eq(
            "id_ciclo", id_ciclo
        ).in_("email", emails).execute()
    except Exception as exc:
        raise FeedbackIndisponivel("Gravação de feedback indisponível.") from exc
