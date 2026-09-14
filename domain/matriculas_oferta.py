"""Matrículas na oferta: situação, pendência (2ª chamada) e histórico."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from data import supabase_academico as acad
from domain.formacao_grupos import (
    grupos_da_oferta,
    listar_ofertas,
    oferta_padrao_id,
    rotulo_oferta,
)
from utils.ordenacao import chave_ordenacao_texto

SITUACOES = (
    "cursando",
    "trancado",
    "desistente",
    "cancelado",
    "aprovado",
    "reprovado",
    "dispensa",
)

# Situações “abertas” (ainda operacionais / espelháveis a partir do status do curso)
SITUACOES_ABERTAS = frozenset({"cursando", "trancado", "desistente", "cancelado"})
# Conclusões acadêmicas da oferta — nunca sobrescrever por mudança de status do curso
SITUACOES_FINAIS = frozenset({"aprovado", "reprovado", "dispensa"})

# status_curso → situacao na oferta (saídas que refletem imediatamente)
ESPELHO_STATUS_PARA_SITUACAO = {
    "trancado": "trancado",
    "desistente": "desistente",
    "cancelado": "cancelado",
}

PENDENCIAS = (None, "segunda_chamada")
PENDENCIA_ROTULO = {
    None: "(nenhuma)",
    "segunda_chamada": "Segunda chamada",
}

COLS_MAT = (
    "id,aluno_id,id_oferta,situacao,pendencia,observacao,"
    "grupo_id,data_situacao_efetiva,updated_at"
)
COLS_ALUNO = "id,email,nome,status_curso,turma_vinculo,turma_ingresso"


def _parse_data(valor) -> str | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor.isoformat()
    texto = str(valor).strip()
    if len(texto) >= 10 and texto[4] == "-":
        return texto[:10]
    return texto[:10] if texto else None


def roster_matriculas(id_oferta: str) -> list[dict]:
    mats = [
        m
        for m in acad.listar("matriculas", COLS_MAT)
        if m.get("id_oferta") == id_oferta
    ]
    alunos = {a["id"]: a for a in acad.listar("alunos", COLS_ALUNO)}
    grupos = {g["id"]: g for g in grupos_da_oferta(id_oferta)}

    roster = []
    for m in mats:
        a = alunos.get(m["aluno_id"], {})
        g = grupos.get(m["grupo_id"]) if m.get("grupo_id") else None
        roster.append(
            {
                "matricula_id": m["id"],
                "aluno_id": m["aluno_id"],
                "email": a.get("email") or "",
                "nome": a.get("nome") or "",
                "status_curso": a.get("status_curso") or "",
                "turma": a.get("turma_vinculo") or a.get("turma_ingresso") or "",
                "situacao": m.get("situacao") or "cursando",
                "pendencia": m.get("pendencia"),
                "observacao": m.get("observacao") or "",
                "grupo_id": m.get("grupo_id"),
                "grupo_nome": (g or {}).get("nome") or "",
                "data_situacao_efetiva": m.get("data_situacao_efetiva"),
            }
        )
    return sorted(
        roster,
        key=lambda r: (
            chave_ordenacao_texto(r["nome"]),
            chave_ordenacao_texto(r["email"]),
        ),
    )


def filtrar_roster(
    roster: list[dict],
    *,
    situacoes: list[str] | None = None,
    pendencias: list[str] | None = None,
    turmas: list[str] | None = None,
    grupos: list[str] | None = None,
    busca: str = "",
) -> list[dict]:
    q = (busca or "").strip().lower()
    sit_ok = set(situacoes) if situacoes else None
    # pendencias: use literal "segunda_chamada" or "__none__" for null
    pend_ok = set(pendencias) if pendencias else None
    turma_ok = set(turmas) if turmas else None
    # grupos: nome do grupo ou "(sem grupo)"
    grupo_ok = set(grupos) if grupos else None
    saida = []
    for r in roster:
        if sit_ok and r.get("situacao") not in sit_ok:
            continue
        if pend_ok is not None:
            chave = r.get("pendencia") or "__none__"
            if chave not in pend_ok:
                continue
        if turma_ok is not None:
            turma_ref = (r.get("turma") or "").strip() or "(sem turma)"
            if turma_ref not in turma_ok:
                continue
        if grupo_ok is not None:
            g_ref = (r.get("grupo_nome") or "").strip() or "(sem grupo)"
            if g_ref not in grupo_ok:
                continue
        if q:
            blob = f"{r.get('nome', '')} {r.get('email', '')}".lower()
            if q not in blob:
                continue
        saida.append(r)
    return saida


def historico_matricula(matricula_id: str, limite: int = 20) -> list[dict]:
    linhas = acad.listar_filtrado(
        "matricula_situacao_historico",
        "id,situacao_anterior,situacao_nova,pendencia,data_efetiva,"
        "motivo,registrado_por_email,created_at",
        filtros={"matricula_id": matricula_id},
        order="created_at",
    )
    return list(reversed(linhas[-limite:]))


def atualizar_matricula(
    matricula_id: str,
    *,
    situacao: str,
    pendencia: str | None,
    observacao: str,
    data_situacao_efetiva: Any,
    motivo: str,
    registrado_por_email: str,
) -> tuple[dict | None, str | None, str | None]:
    """
    Atualiza matrícula e histórico.

    Retorna (registro, erro, aviso).
    Mesma situação/pendência + motivo ou observação novos → novo item no histórico
    (não apaga o anterior).
    """
    if situacao not in SITUACOES:
        return None, f"Situação inválida: {situacao}", None
    if pendencia not in (None, "segunda_chamada"):
        return None, f"Pendência inválida: {pendencia}", None

    atuais = acad.listar_filtrado("matriculas", COLS_MAT, filtros={"id": matricula_id})
    if not atuais:
        return None, "Matrícula não encontrada.", None
    atual = atuais[0]
    sit_ant = atual.get("situacao")
    pend_ant = atual.get("pendencia")
    obs_ant = (atual.get("observacao") or "").strip()
    obs_nova = (observacao or "").strip()
    motivo_txt = (motivo or "").strip()

    mudou_sit_pend = situacao != sit_ant or pendencia != pend_ant
    mudou_obs = obs_nova != obs_ant

    if not mudou_sit_pend and not mudou_obs and not motivo_txt:
        return (
            None,
            "Nada a alterar (informe um motivo ou mude observação/situação).",
            None,
        )

    data_form = _parse_data(data_situacao_efetiva)
    if mudou_sit_pend:
        data_matricula = data_form or date.today().isoformat()
        data_hist = data_matricula
    else:
        # Correção de motivo/obs: preserva a data efetiva acadêmica da matrícula
        data_matricula = atual.get("data_situacao_efetiva")
        data_hist = data_form or date.today().isoformat()

    payload = {
        "situacao": situacao,
        "pendencia": pendencia,
        "observacao": obs_nova,
        "data_situacao_efetiva": data_matricula,
    }
    atualizados = acad.atualizar("matriculas", payload, id=matricula_id)
    if not atualizados:
        return None, "Falha ao atualizar matrícula.", None

    hist_motivo = motivo_txt
    if not hist_motivo and mudou_obs:
        hist_motivo = "Atualização de observação"
    if not mudou_sit_pend and motivo_txt:
        hist_motivo = motivo_txt

    acad.inserir(
        "matricula_situacao_historico",
        {
            "matricula_id": matricula_id,
            "situacao_anterior": sit_ant,
            "situacao_nova": situacao,
            "pendencia": pendencia,
            "data_efetiva": data_hist or date.today().isoformat(),
            "motivo": hist_motivo,
            "registrado_por_email": (registrado_por_email or "").strip().lower(),
        },
    )

    aviso = None
    if not mudou_sit_pend:
        aviso = (
            "Situação inalterada — motivo/observação registrados em novo item do histórico "
            "(lançamento anterior preservado)."
        )
    return atualizados[0], None, aviso


def atualizar_matriculas_lote(
    matricula_ids: list[str],
    *,
    situacao: str,
    pendencia: str | None,
    observacao: str | None = None,
    data_situacao_efetiva: Any = None,
    motivo: str,
    registrado_por_email: str,
) -> tuple[int, list[str]]:
    """Aplica a mesma situação/pendência a várias matrículas. Retorna (ok, erros)."""
    ok = 0
    erros: list[str] = []
    for mid in matricula_ids:
        atuais = acad.listar_filtrado("matriculas", COLS_MAT, filtros={"id": mid})
        obs = observacao
        if obs is None and atuais:
            obs = atuais[0].get("observacao") or ""
        _, erro, _aviso = atualizar_matricula(
            mid,
            situacao=situacao,
            pendencia=pendencia,
            observacao=obs or "",
            data_situacao_efetiva=data_situacao_efetiva,
            motivo=motivo,
            registrado_por_email=registrado_por_email,
        )
        if erro:
            erros.append(f"{mid[:8]}…: {erro}")
        else:
            ok += 1
    return ok, erros


def criar_matricula(
    *,
    email: str,
    id_oferta: str,
    situacao: str = "cursando",
    pendencia: str | None = None,
    observacao: str = "",
    motivo: str = "Inclusão manual",
    registrado_por_email: str = "",
) -> tuple[dict | None, str | None]:
    email_n = (email or "").strip().lower()
    if "@" not in email_n:
        return None, "E-mail inválido."
    if situacao not in SITUACOES:
        return None, f"Situação inválida: {situacao}"

    alunos = acad.listar_filtrado("alunos", COLS_ALUNO, filtros={"email": email_n})
    if not alunos:
        # email pode estar com casing diferente — busca ampla
        todos = acad.listar("alunos", COLS_ALUNO)
        alunos = [a for a in todos if str(a.get("email") or "").lower() == email_n]
    if not alunos:
        return None, f"Ficha do aluno não encontrada: {email_n}"
    aluno = alunos[0]

    existentes = acad.listar_filtrado(
        "matriculas", COLS_MAT, filtros={"aluno_id": aluno["id"], "id_oferta": id_oferta}
    )
    if existentes:
        return None, "Já existe matrícula deste aluno nesta oferta."

    criados = acad.inserir(
        "matriculas",
        {
            "aluno_id": aluno["id"],
            "id_oferta": id_oferta,
            "situacao": situacao,
            "pendencia": pendencia,
            "observacao": (observacao or "").strip(),
            "data_situacao_efetiva": date.today().isoformat(),
        },
    )
    if not criados:
        return None, "Falha ao criar matrícula."
    mat = criados[0]
    acad.inserir(
        "matricula_situacao_historico",
        {
            "matricula_id": mat["id"],
            "situacao_anterior": None,
            "situacao_nova": situacao,
            "pendencia": pendencia,
            "data_efetiva": date.today().isoformat(),
            "motivo": (motivo or "").strip(),
            "registrado_por_email": (registrado_por_email or "").strip().lower(),
        },
    )
    return mat, None


def matriculas_passadas_ainda_cursando(aluno_id: str) -> list[dict]:
    """
    Matrículas em ofertas que NÃO estão Ativas e ainda constam como cursando.
    Exigem ajuste manual — mudança de status do curso não as altera.
    """
    ofertas = {
        o["id_oferta"]: o
        for o in acad.listar("ofertas", "id_oferta,status,id_disciplina,id_trimestre")
    }
    saida = []
    for m in acad.listar_filtrado("matriculas", COLS_MAT, filtros={"aluno_id": aluno_id}):
        if (m.get("situacao") or "cursando") != "cursando":
            continue
        ofe = ofertas.get(m.get("id_oferta") or "", {})
        if ofe.get("status") == "Ativa":
            continue
        saida.append(
            {
                "matricula_id": m["id"],
                "id_oferta": m.get("id_oferta"),
                "status_oferta": ofe.get("status") or "?",
                "id_trimestre": ofe.get("id_trimestre") or "",
            }
        )
    return saida


def espelhar_status_curso_nas_matriculas(
    aluno_id: str,
    *,
    status_curso: str,
    data_efetiva: Any,
    motivo: str,
    registrado_por_email: str,
) -> tuple[int, list[str], list[str]]:
    """
    Propaga mudança de status do curso **somente** para a(s) oferta(s) Ativa(s).

    Ofertas Encerrada/Planejada nunca são alteradas automaticamente — se ainda
    estiverem 'cursando', o ajuste é manual (Matrículas na oferta).

    A data efetiva do status do curso vira data_situacao_efetiva na oferta atual.

    Retorna (qtd_atualizadas, erros, avisos).
    """
    data_iso = _parse_data(data_efetiva) or date.today().isoformat()
    motivo_base = (motivo or "").strip() or f"Espelho do status do curso → {status_curso}"
    avisos: list[str] = []

    passadas = matriculas_passadas_ainda_cursando(aluno_id)
    if passadas:
        ids = ", ".join(str(p["id_oferta"]) for p in passadas[:8])
        extra = f" (+{len(passadas) - 8})" if len(passadas) > 8 else ""
        avisos.append(
            f"{len(passadas)} matrícula(s) em oferta(s) passada(s)/não ativas "
            f"ainda como cursando ({ids}{extra}). "
            "Ajuste manual em Matrículas na oferta — o status do curso não as altera."
        )

    if status_curso == "formado":
        return 0, [], avisos

    if status_curso == "matriculado":
        alvo = "cursando"
        origem_ok = frozenset({"trancado", "desistente", "cancelado"})
        limpar_pendencia = False
    elif status_curso in ESPELHO_STATUS_PARA_SITUACAO:
        alvo = ESPELHO_STATUS_PARA_SITUACAO[status_curso]
        origem_ok = SITUACOES_ABERTAS
        limpar_pendencia = True
    else:
        return 0, [], avisos

    # Só oferta atual (= Ativa). Encerrada/Planejada ficam intactas.
    ofertas_ativas = {
        o["id_oferta"]
        for o in acad.listar("ofertas", "id_oferta,status")
        if o.get("status") == "Ativa"
    }
    if not ofertas_ativas:
        return 0, [], avisos

    mats = acad.listar_filtrado("matriculas", COLS_MAT, filtros={"aluno_id": aluno_id})
    ok = 0
    erros: list[str] = []
    for m in mats:
        if m.get("id_oferta") not in ofertas_ativas:
            continue
        sit = m.get("situacao") or "cursando"
        if sit in SITUACOES_FINAIS:
            continue
        if sit not in origem_ok:
            continue
        if sit == alvo and not (limpar_pendencia and m.get("pendencia")):
            continue

        pend = None if limpar_pendencia else m.get("pendencia")
        _, erro, _aviso = atualizar_matricula(
            m["id"],
            situacao=alvo,
            pendencia=pend,
            observacao=m.get("observacao") or "",
            data_situacao_efetiva=data_iso,
            motivo=motivo_base,
            registrado_por_email=registrado_por_email,
        )
        if erro:
            erros.append(f"{m.get('id_oferta')}: {erro}")
        else:
            ok += 1

    # Pós-checagem: se ainda houver divergência na oferta Ativa, avisar com clareza
    if status_curso in ESPELHO_STATUS_PARA_SITUACAO:
        alvo_chk = ESPELHO_STATUS_PARA_SITUACAO[status_curso]
        mats_chk = acad.listar_filtrado("matriculas", COLS_MAT, filtros={"aluno_id": aluno_id})
        for m in mats_chk:
            if m.get("id_oferta") not in ofertas_ativas:
                continue
            sit = m.get("situacao") or "cursando"
            if sit in SITUACOES_FINAIS:
                continue
            if sit != alvo_chk:
                erros.append(
                    f"{m.get('id_oferta')}: situação ficou '{sit}' "
                    f"(esperado '{alvo_chk}' após status={status_curso})"
                )
    return ok, erros, avisos


# reexport para a view
__all__ = [
    "SITUACOES",
    "SITUACOES_ABERTAS",
    "SITUACOES_FINAIS",
    "ESPELHO_STATUS_PARA_SITUACAO",
    "PENDENCIA_ROTULO",
    "listar_ofertas",
    "oferta_padrao_id",
    "roster_matriculas",
    "filtrar_roster",
    "historico_matricula",
    "atualizar_matricula",
    "atualizar_matriculas_lote",
    "criar_matricula",
    "matriculas_passadas_ainda_cursando",
    "espelhar_status_curso_nas_matriculas",
]
