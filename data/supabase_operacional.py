"""Leitura e escrita das tabelas operacionais tipadas no Supabase de teste.

Este módulo é deliberadamente independente da planilha. A camada de domínio
decide quando usar o fallback para Sheets e quando espelhar uma gravação.
Produção nunca passa por aqui: ``cliente_operacional`` bloqueia qualquer
ambiente diferente de ``teste``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

from auth.supabase_auth import ambiente_app, cliente_admin


class OperacionalIndisponivel(RuntimeError):
    """Tabela operacional ausente ou Supabase indisponível no teste."""


COLUNAS_ANOTACOES = (
    "Data",
    "ID_Disciplina",
    "ID_Ciclo",
    "Nome_Ciclo",
    "Sala",
    "Grupo",
    "Texto",
    "Email_Orientador",
    "Nome_Orientador",
    "Data_Atualizacao",
)

COLUNAS_AVALIACAO_ORIENTADOR = (
    "Data",
    "ID_Ciclo",
    "Nome_Ciclo",
    "ID_Disciplina",
    "Email_Aluno",
    "Nome_Aluno",
    "Grupo",
    "Email_Orientador",
    "Nota",
    "Tipo",
)

COLUNAS_AVALIACOES_PARES = (
    "Data_Hora",
    "ID_Ciclo",
    "Disciplina",
    "Ciclo",
    "Email_Avaliado",
    "Nome_Avaliado",
    "Grupo",
    "Nota",
    "Email_Avaliador",
    "Nome_Avaliador",
    "Comentário",
    "Duplicação",
    "Moderação",
    "chave_origem",
)


def _cliente():
    if ambiente_app() != "teste":
        raise OperacionalIndisponivel(
            "Tabelas operacionais tipadas só estão habilitadas em ambiente=teste."
        )
    try:
        return cliente_admin()
    except Exception as exc:
        raise OperacionalIndisponivel("Supabase operacional indisponível.") from exc


def _paginar(tabela: str, colunas: str) -> list[dict]:
    try:
        sb = _cliente()
        linhas: list[dict] = []
        inicio = 0
        while True:
            lote = (
                sb.table(tabela)
                .select(colunas)
                .range(inicio, inicio + 999)
                .execute()
                .data
                or []
            )
            linhas.extend(lote)
            if len(lote) < 1000:
                return linhas
            inicio += 1000
    except OperacionalIndisponivel:
        raise
    except Exception as exc:
        raise OperacionalIndisponivel(
            f"Leitura operacional indisponível ({tabela})."
        ) from exc


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    return str(valor).strip()


def _numero(valor: Any) -> float | None:
    texto = _texto(valor)
    if not texto:
        return None
    try:
        return float(texto.replace(",", "."))
    except ValueError:
        return None


def listar_anotacoes() -> pd.DataFrame:
    """Retorna todas as anotações tipadas, inclusive quando o resultado é vazio."""
    linhas = _paginar(
        "anotacoes_daily",
        "chave_origem,data,id_disciplina,id_ciclo,nome_ciclo,sala,grupo,"
        "texto,email_orientador,nome_orientador,data_atualizacao",
    )
    return pd.DataFrame(
        [
            {
                "Data": _texto(linha.get("data")),
                "ID_Disciplina": _texto(linha.get("id_disciplina")),
                "ID_Ciclo": _texto(linha.get("id_ciclo")),
                "Nome_Ciclo": _texto(linha.get("nome_ciclo")),
                "Sala": _texto(linha.get("sala")),
                "Grupo": _texto(linha.get("grupo")),
                "Texto": _texto(linha.get("texto")),
                "Email_Orientador": _texto(linha.get("email_orientador")).lower(),
                "Nome_Orientador": _texto(linha.get("nome_orientador")),
                "Data_Atualizacao": _texto(linha.get("data_atualizacao")),
            }
            for linha in linhas
        ],
        columns=COLUNAS_ANOTACOES,
    )


def listar_avaliacoes_orientador() -> pd.DataFrame:
    """Retorna avaliações tipadas; a ordenação/latest fica no domínio."""
    linhas = _paginar(
        "avaliacoes_orientador",
        "chave_origem,data,id_ciclo,nome_ciclo,id_disciplina,email_aluno,"
        "nome_aluno,grupo,email_orientador,nota,tipo",
    )
    return pd.DataFrame(
        [
            {
                "Data": _texto(linha.get("data")),
                "ID_Ciclo": _texto(linha.get("id_ciclo")),
                "Nome_Ciclo": _texto(linha.get("nome_ciclo")),
                "ID_Disciplina": _texto(linha.get("id_disciplina")),
                "Email_Aluno": _texto(linha.get("email_aluno")).lower(),
                "Nome_Aluno": _texto(linha.get("nome_aluno")),
                "Grupo": _texto(linha.get("grupo")),
                "Email_Orientador": _texto(linha.get("email_orientador")).lower(),
                "Nota": _numero(linha.get("nota")),
                "Tipo": _texto(linha.get("tipo")),
            }
            for linha in linhas
        ],
        columns=COLUNAS_AVALIACAO_ORIENTADOR,
    )


def _hash_linha(aba: str, dados: dict[str, str]) -> str:
    bruto = json.dumps(
        {"aba": aba, "dados": dados},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(bruto).hexdigest()


def _chave_anotacao(dados: dict[str, str]) -> str:
    return "|".join(
        (
            dados.get("Data", ""),
            dados.get("ID_Disciplina", ""),
            dados.get("Sala", ""),
            dados.get("Grupo", ""),
        )
    )


def salvar_anotacao(dados: dict[str, str]) -> None:
    """Upsert por grupo/data, igual à chave lógica usada no Sheets."""
    payload = {
        "chave_origem": _chave_anotacao(dados),
        "data": dados.get("Data", ""),
        "id_disciplina": dados.get("ID_Disciplina", ""),
        "id_ciclo": dados.get("ID_Ciclo", ""),
        "nome_ciclo": dados.get("Nome_Ciclo", ""),
        "sala": dados.get("Sala", ""),
        "grupo": dados.get("Grupo", ""),
        "texto": dados.get("Texto", ""),
        "email_orientador": dados.get("Email_Orientador", ""),
        "nome_orientador": dados.get("Nome_Orientador", ""),
        "data_atualizacao": dados.get("Data_Atualizacao", ""),
        "dados": dados,
    }
    try:
        _cliente().table("anotacoes_daily").upsert(
            payload, on_conflict="chave_origem"
        ).execute()
    except Exception as exc:
        raise OperacionalIndisponivel("Gravação operacional indisponível.") from exc


def salvar_avaliacao_orientador(dados: dict[str, str]) -> None:
    """Insere uma avaliação com chave idempotente do lançamento inteiro."""
    payload = {
        "chave_origem": _hash_linha("Avaliacao_Orientador", dados),
        "data": dados.get("Data", ""),
        "id_ciclo": dados.get("ID_Ciclo", ""),
        "nome_ciclo": dados.get("Nome_Ciclo", ""),
        "id_disciplina": dados.get("ID_Disciplina", ""),
        "email_aluno": dados.get("Email_Aluno", ""),
        "nome_aluno": dados.get("Nome_Aluno", ""),
        "grupo": dados.get("Grupo", ""),
        "email_orientador": dados.get("Email_Orientador", ""),
        "nota": _numero(dados.get("Nota")),
        "tipo": dados.get("Tipo", ""),
        "dados": dados,
    }
    try:
        _cliente().table("avaliacoes_orientador").upsert(
            payload, on_conflict="chave_origem"
        ).execute()
    except Exception as exc:
        raise OperacionalIndisponivel("Gravação operacional indisponível.") from exc


def listar_avaliacoes_pares() -> pd.DataFrame:
    """Retorna avaliações de pares tipadas (histórico importado + envios novos)."""
    linhas = _paginar(
        "avaliacoes_pares",
        "chave_origem,data_hora,id_ciclo,disciplina,ciclo,email_avaliado,"
        "nome_avaliado,grupo,nota,email_avaliador,nome_avaliador,comentario,"
        "duplicacao,moderacao",
    )
    return pd.DataFrame(
        [
            {
                "Data_Hora": _texto(linha.get("data_hora")),
                "ID_Ciclo": _texto(linha.get("id_ciclo")),
                "Disciplina": _texto(linha.get("disciplina")),
                "Ciclo": _texto(linha.get("ciclo")),
                "Email_Avaliado": _texto(linha.get("email_avaliado")).lower(),
                "Nome_Avaliado": _texto(linha.get("nome_avaliado")),
                "Grupo": _texto(linha.get("grupo")),
                "Nota": _numero(linha.get("nota")),
                "Email_Avaliador": _texto(linha.get("email_avaliador")).lower(),
                "Nome_Avaliador": _texto(linha.get("nome_avaliador")),
                "Comentário": _texto(linha.get("comentario")),
                "Duplicação": _texto(linha.get("duplicacao")),
                "Moderação": _texto(linha.get("moderacao")),
                "chave_origem": _texto(linha.get("chave_origem")),
            }
            for linha in linhas
        ],
        columns=COLUNAS_AVALIACOES_PARES,
    )


def chave_avaliacao_pares(dados: dict[str, str]) -> str:
    """Chave de negócio: um voto por avaliador/avaliado/ciclo (idempotente)."""
    return "|".join(
        (
            _texto(dados.get("ID_Ciclo")),
            _texto(dados.get("Email_Avaliador")).lower(),
            _texto(dados.get("Email_Avaliado")).lower(),
        )
    )


def salvar_avaliacao_pares(dados: dict[str, str]) -> str:
    """Upsert de uma linha de pares. Retorna a chave_origem usada."""
    id_ciclo = _texto(dados.get("ID_Ciclo"))
    email_avaliador = _texto(dados.get("Email_Avaliador")).lower()
    email_avaliado = _texto(dados.get("Email_Avaliado")).lower()
    chave_negocio = chave_avaliacao_pares(dados)
    if not id_ciclo or not email_avaliador or not email_avaliado:
        raise OperacionalIndisponivel("Chave de avaliação de pares inválida.")

    try:
        sb = _cliente()
        existentes = (
            sb.table("avaliacoes_pares")
            .select("chave_origem")
            .eq("id_ciclo", id_ciclo)
            .eq("email_avaliador", email_avaliador)
            .eq("email_avaliado", email_avaliado)
            .limit(1)
            .execute()
            .data
            or []
        )
        # Reusa a chave do import (hash) se já existir, evitando duplicata lógica.
        chave = _texto(existentes[0].get("chave_origem")) if existentes else chave_negocio
        payload = {
            "chave_origem": chave,
            "data_hora": _texto(dados.get("Data_Hora")),
            "id_ciclo": id_ciclo,
            "disciplina": _texto(dados.get("Disciplina")),
            "ciclo": _texto(dados.get("Ciclo")),
            "email_avaliado": email_avaliado,
            "nome_avaliado": _texto(dados.get("Nome_Avaliado")),
            "grupo": _texto(dados.get("Grupo")),
            "nota": _numero(dados.get("Nota")),
            "email_avaliador": email_avaliador,
            "nome_avaliador": _texto(dados.get("Nome_Avaliador")),
            "comentario": _texto(dados.get("Comentário") or dados.get("Comentario")),
            "duplicacao": _texto(dados.get("Duplicação") or dados.get("Duplicacao")),
            "moderacao": _texto(dados.get("Moderação") or dados.get("Moderacao")),
            "dados": dados,
        }
        sb.table("avaliacoes_pares").upsert(
            payload, on_conflict="chave_origem"
        ).execute()
    except OperacionalIndisponivel:
        raise
    except Exception as exc:
        raise OperacionalIndisponivel("Gravação operacional indisponível.") from exc
    return chave


def atualizar_moderacao_pares(chave_origem: str, status: str) -> None:
    """Atualiza só o campo de moderação (Aprovado / Ignorar)."""
    chave = _texto(chave_origem)
    status_limpo = _texto(status)
    if not chave:
        raise OperacionalIndisponivel("Chave de moderação inválida.")
    try:
        sb = _cliente()
        atual = (
            sb.table("avaliacoes_pares")
            .select("dados")
            .eq("chave_origem", chave)
            .limit(1)
            .execute()
            .data
            or []
        )
        dados = dict(atual[0].get("dados") or {}) if atual else {}
        dados["Moderação"] = status_limpo
        dados["Moderacao"] = status_limpo
        sb.table("avaliacoes_pares").update(
            {"moderacao": status_limpo, "dados": dados}
        ).eq("chave_origem", chave).execute()
    except OperacionalIndisponivel:
        raise
    except Exception as exc:
        raise OperacionalIndisponivel("Atualização de moderação indisponível.") from exc


def listar_liberacoes_pares() -> list[dict]:
    linhas = _paginar(
        "liberacoes_pares_excepcionais",
        "id,email_aluno,nome_aluno,id_disciplina,id_ciclo,nome_ciclo,modo,"
        "valido_ate,motivo,email_liberador,nome_liberador,criado_em,usado_em,revogado_em",
    )
    return [
        {
            "ID": _texto(linha.get("id")),
            "Email_Aluno": _texto(linha.get("email_aluno")).lower(),
            "Nome_Aluno": _texto(linha.get("nome_aluno")),
            "ID_Disciplina": _texto(linha.get("id_disciplina")),
            "ID_Ciclo": _texto(linha.get("id_ciclo")),
            "Nome_Ciclo": _texto(linha.get("nome_ciclo")),
            "Modo": _texto(linha.get("modo")) or "primeiro_envio",
            "Valido_Ate": _texto(linha.get("valido_ate")),
            "Motivo": _texto(linha.get("motivo")),
            "Email_Liberador": _texto(linha.get("email_liberador")).lower(),
            "Nome_Liberador": _texto(linha.get("nome_liberador")),
            "Criado_Em": _texto(linha.get("criado_em")),
            "Usado_Em": _texto(linha.get("usado_em")),
            "Revogado_Em": _texto(linha.get("revogado_em")),
        }
        for linha in linhas
    ]


def upsert_liberacao_pares(dados: dict[str, str]) -> None:
    payload = {
        "id": dados["ID"],
        "email_aluno": _texto(dados.get("Email_Aluno")).lower(),
        "nome_aluno": _texto(dados.get("Nome_Aluno")),
        "id_disciplina": _texto(dados.get("ID_Disciplina")),
        "id_ciclo": _texto(dados.get("ID_Ciclo")),
        "nome_ciclo": _texto(dados.get("Nome_Ciclo")),
        "modo": _texto(dados.get("Modo")) or "primeiro_envio",
        "valido_ate": dados.get("Valido_Ate"),
        "motivo": _texto(dados.get("Motivo")),
        "email_liberador": _texto(dados.get("Email_Liberador")).lower(),
        "nome_liberador": _texto(dados.get("Nome_Liberador")),
        "criado_em": dados.get("Criado_Em"),
        "usado_em": dados.get("Usado_Em") or None,
        "revogado_em": dados.get("Revogado_Em") or None,
    }
    try:
        _cliente().table("liberacoes_pares_excepcionais").upsert(
            payload, on_conflict="id"
        ).execute()
    except Exception as exc:
        raise OperacionalIndisponivel("Gravação de liberação excepcional indisponível.") from exc


def atualizar_campos_liberacao_pares(id_lib: str, campos: dict) -> None:
    try:
        _cliente().table("liberacoes_pares_excepcionais").update(campos).eq(
            "id", id_lib
        ).execute()
    except Exception as exc:
        raise OperacionalIndisponivel("Atualização de liberação excepcional indisponível.") from exc
