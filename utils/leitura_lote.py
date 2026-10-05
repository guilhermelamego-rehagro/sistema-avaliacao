"""Leitura única de bases durante cálculos em lote (ex.: boletins de uma turma inteira).

Fora de ``leitura_em_lote()`` as funções decoradas se comportam normalmente. Dentro dele,
cada base é lida uma vez por contexto (thread/sessão), sem afetar outras sessões.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

import pandas as pd

_MEMO: ContextVar[dict | None] = ContextVar("memo_leitura_lote", default=None)


@contextmanager
def leitura_em_lote():
    token = _MEMO.set({}) if _MEMO.get() is None else None
    try:
        yield
    finally:
        if token is not None:
            _MEMO.reset(token)


def memorizar_em_lote(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        memo = _MEMO.get()
        if memo is None:
            return fn(*args, **kwargs)
        chave = (fn.__module__, fn.__qualname__, args, tuple(sorted(kwargs.items())))
        if chave not in memo:
            memo[chave] = fn(*args, **kwargs)
        valor = memo[chave]
        return valor.copy() if isinstance(valor, pd.DataFrame) else valor

    return wrapper
