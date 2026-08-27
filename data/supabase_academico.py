"""Acesso às tabelas acadêmicas no Supabase (ambiente de TESTE).

Produção (Cloud) usa outro projeto Supabase sem essas tabelas — gravações
e leituras acadêmicas só quando ambiente_app() == \"teste\".
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from auth.supabase_auth import ambiente_app, cliente_admin

PAGE = 1000


class AmbienteProducaoError(RuntimeError):
    """Operação acadêmica bloqueada fora do ambiente de teste."""


def garantir_ambiente_teste() -> None:
    if ambiente_app() != "teste":
        raise AmbienteProducaoError(
            "Operações acadêmicas no Supabase só estão disponíveis em ambiente=teste."
        )


def client():
    garantir_ambiente_teste()
    return cliente_admin()


def academico_habilitado() -> bool:
    return ambiente_app() == "teste"


def _cache_epoch() -> int:
    return int(st.session_state.get("_acad_cache_epoch", 0))


def invalidar_cache_academico() -> None:
    st.session_state["_acad_cache_epoch"] = _cache_epoch() + 1
    try:
        listar_cached.clear()
    except Exception:
        pass


@st.cache_data(ttl=45, show_spinner=False)
def listar_cached(tabela: str, colunas: str, epoch: int) -> tuple[dict, ...]:
    _ = epoch
    sb = cliente_admin()
    saida: list[dict] = []
    inicio = 0
    while True:
        res = (
            sb.table(tabela)
            .select(colunas)
            .range(inicio, inicio + PAGE - 1)
            .execute()
        )
        linhas = res.data or []
        if not linhas:
            break
        saida.extend(linhas)
        if len(linhas) < PAGE:
            break
        inicio += PAGE
    return tuple(saida)


def listar(tabela: str, colunas: str = "*") -> list[dict]:
    garantir_ambiente_teste()
    return list(listar_cached(tabela, colunas, _cache_epoch()))


def listar_filtrado(
    tabela: str,
    colunas: str,
    filtros: dict[str, Any] | None = None,
    order: str | None = None,
) -> list[dict]:
    """Leitura pontual sem cache (filtros dinâmicos)."""
    sb = client()
    q = sb.table(tabela).select(colunas)
    for chave, valor in (filtros or {}).items():
        if valor is None:
            q = q.is_(chave, "null")
        else:
            q = q.eq(chave, valor)
    if order:
        q = q.order(order)
    res = q.execute()
    return list(res.data or [])


def inserir(tabela: str, payload: dict | list[dict]) -> list[dict]:
    sb = client()
    res = sb.table(tabela).insert(payload).execute()
    invalidar_cache_academico()
    return list(res.data or [])


def atualizar(tabela: str, payload: dict, **eq_filtros) -> list[dict]:
    sb = client()
    q = sb.table(tabela).update(payload)
    for chave, valor in eq_filtros.items():
        q = q.eq(chave, valor)
    res = q.execute()
    invalidar_cache_academico()
    return list(res.data or [])


def upsert(tabela: str, payload: dict | list[dict], on_conflict: str) -> list[dict]:
    sb = client()
    res = sb.table(tabela).upsert(payload, on_conflict=on_conflict).execute()
    invalidar_cache_academico()
    return list(res.data or [])
