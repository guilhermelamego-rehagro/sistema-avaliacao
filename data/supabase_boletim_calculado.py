"""Boletins calculados no Supabase (teste e produção).

Tabelas próprias (``boletim_calculado`` e ``boletim_calculo``), sem relação com as planilhas.
"""

from __future__ import annotations

from datetime import datetime, timezone

from auth.supabase_auth import cliente_admin

TABELA = "boletim_calculado"
TABELA_CALCULO = "boletim_calculo"
_LOTE = 200


class BoletimIndisponivel(RuntimeError):
    """Tabela ausente ou Supabase fora do ar."""


def ler_calculo(id_disciplina: str) -> dict | None:
    try:
        dados = (
            cliente_admin().table(TABELA_CALCULO).select("*").eq("id_disciplina", id_disciplina).limit(1).execute().data
        )
    except Exception as exc:
        raise BoletimIndisponivel("Leitura dos boletins calculados indisponível.") from exc
    return dados[0] if dados else None


def listar(id_disciplina: str) -> list[dict]:
    linhas: list[dict] = []
    try:
        while True:
            pagina = (
                cliente_admin()
                .table(TABELA)
                .select("email,dados,calculado_em")
                .eq("id_disciplina", id_disciplina)
                .order("email")
                .range(len(linhas), len(linhas) + 999)
                .execute()
                .data
                or []
            )
            linhas.extend(pagina)
            if len(pagina) < 1000:
                return linhas
    except Exception as exc:
        raise BoletimIndisponivel("Leitura dos boletins calculados indisponível.") from exc


def salvar(id_disciplina: str, dados_por_email: dict[str, dict], *, completo: bool, autor: str) -> None:
    """Grava os boletins; ``completo`` marca o cálculo da turma inteira (o do dia)."""
    agora = datetime.now(timezone.utc).isoformat()
    linhas = [
        {"id_disciplina": id_disciplina, "email": email, "dados": dados, "calculado_em": agora}
        for email, dados in dados_por_email.items()
    ]
    try:
        for i in range(0, len(linhas), _LOTE):
            cliente_admin().table(TABELA).upsert(linhas[i : i + _LOTE], on_conflict="id_disciplina,email").execute()
        if completo:
            cliente_admin().table(TABELA_CALCULO).upsert(
                {"id_disciplina": id_disciplina, "concluido_em": agora, "alunos": len(linhas), "calculado_por": autor},
                on_conflict="id_disciplina",
            ).execute()
    except Exception as exc:
        raise BoletimIndisponivel("Gravação dos boletins calculados indisponível.") from exc
