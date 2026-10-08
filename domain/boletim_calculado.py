"""Boletins calculados guardados no Supabase, para as telas da equipe abrirem sem recalcular.

Calcular a turma inteira leva alguns minutos: o cálculo roda numa thread do servidor no primeiro acesso
do dia de professores e secretaria e quando alguém pede recálculo, sem prender a tela de quem disparou.
Enquanto isso, as telas mostram o último cálculo salvo.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from data.supabase_boletim_calculado import BoletimIndisponivel
from domain.situacao_final import ResultadoFinal
from utils.disciplina import normalizar_id

__all__ = ["BoletimIndisponivel"]

_LOG = logging.getLogger(__name__)
_TZ = ZoneInfo("America/Sao_Paulo")
_COLUNAS_COMPONENTES = ["Componente", "Peso", "Nota", "Pontos", "Perdeu", "Detalhe"]
_NUMERICAS = ("Peso", "Nota", "Pontos", "Perdeu")
_VALIDADE_SESSAO_S = 300
_PRESENCA_VAZIA = {"total": 0, "presencas": 0, "faltas": 0, "pct": None, "seq_max": 0, "datas_falta": []}

# Estado compartilhado por todas as sessões do servidor (um processo no Streamlit Cloud).
_TRAVA = threading.Lock()
_COMPLETOS: dict[str, "Andamento"] = {}
_PARCIAIS: dict[str, set[str]] = {}
_REFEITOS: dict[str, dict[str, float]] = {}
_VERSAO: dict[str, int] = {}


@dataclass
class Andamento:
    inicio: float
    feito: int = 0
    total: int = 0


def _limpo(valor):
    """Valor aceito no jsonb: sem NaN nem tipos do numpy."""
    if isinstance(valor, dict):
        return {str(k): _limpo(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_limpo(v) for v in valor]
    if valor is None or valor is pd.NA or valor is pd.NaT:
        return None
    if hasattr(valor, "item") and not isinstance(valor, (str, bytes)):
        valor = valor.item()
    if isinstance(valor, float):
        return None if math.isnan(valor) else valor
    if isinstance(valor, (str, int, bool)):
        return valor
    return str(valor)


def para_json(r: ResultadoFinal) -> dict:
    comp = r.componentes.reindex(columns=_COLUNAS_COMPONENTES) if r.componentes is not None else pd.DataFrame()
    return _limpo(
        {
            "situacao": r.situacao,
            "nota_final": r.nota_final,
            "presenca": r.presenca,
            "componentes": comp.to_dict("records"),
            "segunda_chamada": list(r.segunda_chamada),
            "motivos": list(r.motivos),
        }
    )


def de_json(email: str, dados: dict) -> ResultadoFinal:
    comp = pd.DataFrame(dados.get("componentes") or [], columns=_COLUNAS_COMPONENTES)
    for col in _NUMERICAS:
        comp[col] = pd.to_numeric(comp[col], errors="coerce")
    comp["Detalhe"] = comp["Detalhe"].fillna("")
    return ResultadoFinal(
        email=email,
        situacao=dados.get("situacao", ""),
        nota_final=dados.get("nota_final"),
        presenca={**_PRESENCA_VAZIA, **(dados.get("presenca") or {})},
        componentes=comp,
        segunda_chamada=list(dados.get("segunda_chamada") or []),
        motivos=list(dados.get("motivos") or []),
    )


def _momento(valor) -> datetime | None:
    ts = pd.to_datetime(valor, utc=True, errors="coerce")
    return None if pd.isna(ts) else ts.to_pydatetime()


def _dia(valor: datetime) -> str:
    return valor.astimezone(_TZ).date().isoformat()


def _hoje() -> str:
    return _dia(datetime.now(_TZ))


def andamento(id_disciplina: str) -> Andamento | None:
    """Cálculo da turma inteira em curso (cópia), ou None."""
    with _TRAVA:
        a = _COMPLETOS.get(normalizar_id(id_disciplina))
        return None if a is None else Andamento(a.inicio, a.feito, a.total)


def em_atualizacao(id_disciplina: str) -> set[str]:
    """E-mails recalculados sozinhos neste momento (ex.: nota do orientador recém-salva)."""
    with _TRAVA:
        return set(_PARCIAIS.get(normalizar_id(id_disciplina), set()))


def versao(id_disciplina: str) -> int:
    """Muda a cada gravação: as sessões releem a tabela quando ela muda."""
    with _TRAVA:
        return _VERSAO.get(normalizar_id(id_disciplina), 0)


def _ciclos(id_d: str) -> pd.DataFrame:
    from data.sheets import ler_aba
    from domain.ciclos import ordenar_ciclos
    from domain.encontro_presencial import ciclos_visiveis_avaliacao

    df = ler_aba("Ciclos")
    df = df[df["ID_Disciplina"].map(normalizar_id) == id_d]
    return ordenar_ciclos(ciclos_visiveis_avaliacao(df, id_d))


def _gravar(id_d: str, resultados: dict[str, ResultadoFinal], *, completo: bool, autor: str) -> None:
    from data import supabase_boletim_calculado as repo

    repo.salvar(id_d, {e: para_json(r) for e, r in resultados.items()}, completo=completo, autor=autor)
    with _TRAVA:
        _VERSAO[id_d] = _VERSAO.get(id_d, 0) + 1


def salvar_resultados(id_disciplina: str, resultados: dict[str, ResultadoFinal], *, autor: str) -> None:
    """Grava boletins calculados fora da thread (ex.: alunos que faltavam no Dossiê)."""
    if not resultados:
        return
    id_d = normalizar_id(id_disciplina)
    _gravar(id_d, resultados, completo=False, autor=autor)
    agora = time.time()
    with _TRAVA:
        _REFEITOS.setdefault(id_d, {}).update({e: agora for e in resultados})


def _rodar(id_d: str, emails: set[str] | None, autor: str) -> None:
    from domain.dossie_aluno import _alunos_disciplina
    from domain.situacao_final import calcular_resultados, periodos_ciclos

    inicio = time.time()
    try:
        alunos = _alunos_disciplina(id_d)
        if emails is not None:
            alunos = alunos[alunos["Email"].isin(emails)]

        def avancar(i, n):
            if emails is None:
                with _TRAVA:
                    _COMPLETOS[id_d].feito, _COMPLETOS[id_d].total = i, n

        resultados = calcular_resultados(id_d, alunos, periodos_ciclos(_ciclos(id_d)), ao_avancar=avancar)
        if emails is None:
            with _TRAVA:
                refeitos = dict(_REFEITOS.get(id_d, {}))
            # Quem foi recalculado sozinho durante esta rodada já está mais atualizado.
            resultados = {e: r for e, r in resultados.items() if refeitos.get(e, 0) <= inicio}
            _gravar(id_d, resultados, completo=True, autor=autor)
        else:
            _gravar(id_d, resultados, completo=False, autor=autor)
            fim = time.time()
            with _TRAVA:
                _REFEITOS.setdefault(id_d, {}).update({e: fim for e in resultados})
    except Exception:
        _LOG.exception("Falha ao calcular os boletins da disciplina %s", id_d)
    finally:
        with _TRAVA:
            if emails is None:
                _COMPLETOS.pop(id_d, None)
            else:
                _PARCIAIS.get(id_d, set()).difference_update(emails)


def recalcular(id_disciplina: str, emails=None, *, autor: str = "") -> bool:
    """Dispara o cálculo em segundo plano (turma inteira ou só ``emails``).

    Devolve False se o cálculo da turma inteira já está em curso.
    """
    id_d = normalizar_id(id_disciplina)
    alvo = {str(e).strip().lower() for e in emails} if emails is not None else None
    if alvo is not None and not alvo:
        return False
    with _TRAVA:
        if alvo is None:
            if id_d in _COMPLETOS:
                return False
            _COMPLETOS[id_d] = Andamento(inicio=time.time())
        else:
            _PARCIAIS.setdefault(id_d, set()).update(alvo)
    threading.Thread(target=_rodar, args=(id_d, alvo, autor), daemon=True, name=f"boletim-{id_d}").start()
    return True


def carregar_salvos(id_disciplina: str) -> tuple[dict[str, ResultadoFinal], datetime | None]:
    """Último cálculo salvo e quando terminou o da turma inteira.

    Fica na sessão até sair um cálculo novo (ou por alguns minutos). Levanta ``BoletimIndisponivel``.
    """
    import streamlit as st

    from data import supabase_boletim_calculado as repo

    id_d = normalizar_id(id_disciplina)
    chave = chave_sessao(id_d)
    atual = versao(id_d)
    guardado = st.session_state.get(chave)
    if guardado and guardado[0] == atual and time.time() - guardado[1] < _VALIDADE_SESSAO_S:
        return guardado[2], guardado[3]
    linhas = repo.listar(id_d)
    calc = repo.ler_calculo(id_d)
    resultados = {str(l["email"]): de_json(str(l["email"]), l.get("dados") or {}) for l in linhas}
    concluido = _momento(calc.get("concluido_em")) if calc else None
    st.session_state[chave] = (atual, time.time(), resultados, concluido)
    return resultados, concluido


def chave_sessao(id_disciplina: str) -> str:
    return f"_boletim_salvo|{normalizar_id(id_disciplina)}"


def garantir_calculo_do_dia(usuario: dict) -> None:
    """Primeiro acesso do dia da equipe: recalcula a disciplina ativa se o último cálculo não é de hoje."""
    import streamlit as st

    from data import supabase_boletim_calculado as repo
    from domain.ciclos import obter_disciplina_ativa

    hoje = _hoje()
    if st.session_state.get("_boletim_dia") == hoje:
        return
    st.session_state["_boletim_dia"] = hoje
    try:
        id_disc, _ = obter_disciplina_ativa()
        if not id_disc:
            return
        id_d = normalizar_id(id_disc)
        if andamento(id_d):
            return
        calc = repo.ler_calculo(id_d)
    except Exception:
        return
    concluido = _momento(calc.get("concluido_em")) if calc else None
    if concluido is not None and _dia(concluido) == hoje:
        return
    recalcular(id_d, autor=f"Primeiro acesso do dia ({str(usuario.get('email', '')).lower()})")
