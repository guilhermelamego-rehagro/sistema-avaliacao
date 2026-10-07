"""Relatório de notas finais da secretaria no Supabase (teste e produção).

Tabelas próprias (``relatorio_secretaria`` e ``relatorio_secretaria_log``), sem relação com as planilhas.
"""

from __future__ import annotations

from datetime import datetime, timezone

from auth.supabase_auth import cliente_admin

TABELA = "relatorio_secretaria"
TABELA_LOG = "relatorio_secretaria_log"


class RelatorioIndisponivel(RuntimeError):
    """Tabela ausente ou Supabase fora do ar."""


def ler(id_disciplina: str) -> dict | None:
    try:
        dados = cliente_admin().table(TABELA).select("*").eq("id_disciplina", id_disciplina).limit(1).execute().data
    except Exception as exc:
        raise RelatorioIndisponivel("Leitura do relatório da secretaria indisponível.") from exc
    return dados[0] if dados else None


def listar() -> list[dict]:
    try:
        return (
            cliente_admin()
            .table(TABELA)
            .select("id_disciplina,nome_disciplina,gerado_em,gerado_por_nome")
            .execute()
            .data
            or []
        )
    except Exception as exc:
        raise RelatorioIndisponivel("Leitura do relatório da secretaria indisponível.") from exc


def salvar(registro: dict, alteracoes: list[dict], usuario: dict) -> None:
    """Substitui o retrato da disciplina e registra o que mudou."""
    agora = datetime.now(timezone.utc).isoformat()
    autor_email = str(usuario.get("email", "")).lower()
    autor_nome = str(usuario.get("nome", ""))
    try:
        cliente_admin().table(TABELA).upsert(
            {**registro, "gerado_em": agora, "gerado_por_email": autor_email, "gerado_por_nome": autor_nome},
            on_conflict="id_disciplina",
        ).execute()
        if alteracoes:
            cliente_admin().table(TABELA_LOG).insert(
                [
                    {
                        **alt,
                        "id_disciplina": registro["id_disciplina"],
                        "alterado_em": agora,
                        "alterado_por_email": autor_email,
                        "alterado_por_nome": autor_nome,
                    }
                    for alt in alteracoes
                ]
            ).execute()
    except Exception as exc:
        raise RelatorioIndisponivel("Gravação do relatório da secretaria indisponível.") from exc


def listar_alteracoes(id_disciplina: str) -> list[dict]:
    try:
        return (
            cliente_admin()
            .table(TABELA_LOG)
            .select("email,nome,turma,campo,antes,depois,alterado_em,alterado_por_nome")
            .eq("id_disciplina", id_disciplina)
            .order("alterado_em", desc=True)
            .limit(10000)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        raise RelatorioIndisponivel("Leitura do histórico do relatório indisponível.") from exc
