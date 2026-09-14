"""Ficha acadêmica do aluno (Supabase teste): status, turmas, histórico."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from data import supabase_academico as acad
from utils.ordenacao import chave_ordenacao_texto

STATUS_CURSO = (
    "matriculado",
    "trancado",
    "desistente",
    "cancelado",
    "formado",
)

COLS_ALUNO = (
    "id,email,nome,status_curso,data_status_efetiva,"
    "turma_ingresso,turma_vinculo,observacao,user_id,updated_at"
)


def listar_turmas() -> list[dict]:
    turmas = acad.listar("turmas", "id_turma,status,observacao")
    return sorted(turmas, key=lambda t: str(t.get("id_turma") or ""))


def listar_alunos() -> list[dict]:
    alunos = acad.listar("alunos", COLS_ALUNO)
    ofertas = acad.listar("ofertas", "id_oferta,status")
    matriculas = acad.listar("matriculas", "aluno_id,id_oferta,situacao")
    contagens = calcular_n_ofertas_ativas(alunos, ofertas, matriculas)
    for aluno in alunos:
        aluno["n_ofertas_ativas"] = contagens.get(str(aluno.get("id")), 0)
    return sorted(
        alunos,
        key=lambda a: (
            chave_ordenacao_texto(a.get("nome")),
            chave_ordenacao_texto(a.get("email")),
        ),
    )


def calcular_n_ofertas_ativas(
    alunos: list[dict], ofertas: list[dict], matriculas: list[dict]
) -> dict[str, int]:
    """Conta ofertas distintas Ativas com matrícula `cursando` por aluno."""
    ativas = {
        str(oferta.get("id_oferta"))
        for oferta in ofertas
        if oferta.get("status") == "Ativa" and oferta.get("id_oferta")
    }
    por_aluno: dict[str, set[str]] = {}
    for matricula in matriculas:
        aluno_id = str(matricula.get("aluno_id") or "")
        id_oferta = str(matricula.get("id_oferta") or "")
        if (
            aluno_id
            and id_oferta in ativas
            and matricula.get("situacao") == "cursando"
        ):
            por_aluno.setdefault(aluno_id, set()).add(id_oferta)
    return {aluno_id: len(ofertas_aluno) for aluno_id, ofertas_aluno in por_aluno.items()}


def filtrar_alunos(
    alunos: list[dict],
    *,
    status: str | list[str] | None = None,
    turma: str | list[str] | None = None,
    busca: str = "",
) -> list[dict]:
    q = (busca or "").strip().lower()
    if isinstance(status, str):
        status_ok = {status} if status else None
    elif status:
        status_ok = {s for s in status if s}
    else:
        status_ok = None
    if isinstance(turma, str):
        turma_ok = {turma} if turma else None
    elif turma:
        turma_ok = {t for t in turma if t}
    else:
        turma_ok = None

    saida = []
    for a in alunos:
        if status_ok and a.get("status_curso") not in status_ok:
            continue
        turma_ref = a.get("turma_vinculo") or a.get("turma_ingresso") or ""
        if turma_ok and turma_ref not in turma_ok:
            continue
        if q:
            blob = f"{a.get('nome', '')} {a.get('email', '')}".lower()
            if q not in blob:
                continue
        saida.append(a)
    return saida


def historico_status(aluno_id: str, limite: int = 20) -> list[dict]:
    linhas = acad.listar_filtrado(
        "aluno_status_historico",
        "id,status_anterior,status_novo,data_efetiva,motivo,registrado_por_email,created_at",
        filtros={"aluno_id": aluno_id},
        order="created_at",
    )
    # order asc; pegar os mais recentes no fim
    return list(reversed(linhas[-limite:]))


def _parse_data(valor) -> str | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor.isoformat()
    texto = str(valor).strip()
    if not texto or texto.lower() in {"nan", "none", "nat"}:
        return None
    if len(texto) >= 10 and texto[4] == "-" and texto[7] == "-":
        return texto[:10]
    # dd/mm/yyyy
    if "/" in texto:
        partes = texto.split("/")
        if len(partes) == 3:
            d, m, a = partes
            return f"{int(a):04d}-{int(m):02d}-{int(d):02d}"
    return texto[:10]


def _requer_confirmacao_sem_aproveitamento(status_anterior: str, status_novo: str) -> bool:
    return status_novo == "matriculado" and status_anterior in {"desistente", "cancelado"}


def _aviso_aproveitamento_trancado(status_anterior: str, status_novo: str) -> str | None:
    if status_novo == "matriculado" and status_anterior == "trancado":
        return (
            "Reingresso a partir de trancado: aproveitamento de histórico é possível "
            "(dispensa/crédito conforme política — motor ainda não automatizado)."
        )
    return None


def atualizar_ficha(
    aluno_id: str,
    *,
    status_curso: str,
    data_status_efetiva: Any,
    turma_ingresso: str | None,
    turma_vinculo: str | None,
    observacao: str,
    motivo: str,
    registrado_por_email: str,
    confirmou_sem_aproveitamento: bool = False,
    status_anterior: str | None = None,
) -> tuple[dict | None, str | None, str | None]:
    """
    Retorna (ficha_atualizada, erro, aviso_informativo).
    """
    if status_curso not in STATUS_CURSO:
        return None, f"Status inválido: {status_curso}", None

    atuais = acad.listar_filtrado("alunos", COLS_ALUNO, filtros={"id": aluno_id})
    if not atuais:
        return None, "Aluno não encontrado.", None
    atual = atuais[0]
    anterior = status_anterior if status_anterior is not None else atual.get("status_curso")

    if _requer_confirmacao_sem_aproveitamento(str(anterior or ""), status_curso):
        if not confirmou_sem_aproveitamento:
            return (
                None,
                "Reingresso de desistente/cancelado exige confirmação: "
                "sem aproveitamento de histórico acadêmico.",
                None,
            )

    aviso = _aviso_aproveitamento_trancado(str(anterior or ""), status_curso)
    data_iso = _parse_data(data_status_efetiva)
    if status_curso != anterior and not data_iso:
        data_iso = date.today().isoformat()

    payload = {
        "status_curso": status_curso,
        "data_status_efetiva": data_iso,
        "turma_ingresso": turma_ingresso or None,
        "turma_vinculo": turma_vinculo or None,
        "observacao": (observacao or "").strip(),
    }
    atualizados = acad.atualizar("alunos", payload, id=aluno_id)
    if not atualizados:
        return None, "Falha ao atualizar ficha.", None

    if status_curso != anterior:
        acad.inserir(
            "aluno_status_historico",
            {
                "aluno_id": aluno_id,
                "status_anterior": anterior,
                "status_novo": status_curso,
                "data_efetiva": data_iso or date.today().isoformat(),
                "motivo": (motivo or "").strip(),
                "registrado_por_email": (registrado_por_email or "").strip().lower(),
            },
        )
        from domain.matriculas_oferta import espelhar_status_curso_nas_matriculas

        n_mats, erros_mat, avisos_mat = espelhar_status_curso_nas_matriculas(
            aluno_id,
            status_curso=status_curso,
            data_efetiva=data_iso,
            motivo=motivo,
            registrado_por_email=registrado_por_email,
        )
        partes_aviso = [aviso] if aviso else []
        if n_mats:
            partes_aviso.append(
                f"{n_mats} matrícula(s) na oferta Ativa "
                f"atualizada(s) com a data efetiva do status do curso."
            )
        partes_aviso.extend(avisos_mat)
        if erros_mat:
            partes_aviso.append(
                "Atenção ao espelhar a oferta atual: " + "; ".join(erros_mat[:5])
            )
        aviso = " ".join(partes_aviso) if partes_aviso else None

    return atualizados[0], None, aviso


def reingressar(
    aluno_id: str,
    *,
    data_efetiva: Any,
    motivo: str,
    registrado_por_email: str,
    confirmou_sem_aproveitamento: bool,
    turma_vinculo: str | None = None,
) -> tuple[dict | None, str | None, str | None]:
    atuais = acad.listar_filtrado("alunos", COLS_ALUNO, filtros={"id": aluno_id})
    if not atuais:
        return None, "Aluno não encontrado.", None
    atual = atuais[0]
    anterior = str(atual.get("status_curso") or "")
    if anterior == "matriculado":
        return None, "Aluno já está matriculado.", None
    if anterior not in {"trancado", "desistente", "cancelado"}:
        return None, f"Não é possível reingressar a partir de status={anterior}.", None

    return atualizar_ficha(
        aluno_id,
        status_curso="matriculado",
        data_status_efetiva=data_efetiva or date.today(),
        turma_ingresso=atual.get("turma_ingresso"),
        turma_vinculo=turma_vinculo or atual.get("turma_vinculo") or atual.get("turma_ingresso"),
        observacao=atual.get("observacao") or "",
        motivo=motivo or "Reingresso",
        registrado_por_email=registrado_por_email,
        confirmou_sem_aproveitamento=confirmou_sem_aproveitamento,
        status_anterior=anterior,
    )


COLS_MAT_HIST = (
    "id,aluno_id,id_oferta,situacao,pendencia,observacao,"
    "grupo_id,data_situacao_efetiva,updated_at"
)


def historico_escolar(aluno_id: str) -> list[dict]:
    """
    Disciplinas/ofertas do aluno (visão tipo histórico escolar).
    Situação vem de `matriculas`. Nota final é opcional (preenchida pela view
    quando o boletim Sheets estiver disponível).
    """
    mats = acad.listar_filtrado(
        "matriculas", COLS_MAT_HIST, filtros={"aluno_id": aluno_id}
    )
    if not mats:
        return []

    ofertas = {
        o["id_oferta"]: o
        for o in acad.listar(
            "ofertas",
            "id_oferta,id_disciplina,id_trimestre,status,fase",
        )
    }
    grupos = {g["id"]: g for g in acad.listar("grupos", "id,id_oferta,nome,sala_id")}
    salas = {s["id"]: s for s in acad.listar("salas", "id,id_oferta,nome")}

    nomes_disc: dict[str, str] = {}
    try:
        from domain.cadastros import carregar_disciplinas
        from utils.disciplina import normalizar_id

        discs = carregar_disciplinas()
        if discs is not None and not discs.empty:
            for _, row in discs.iterrows():
                did = normalizar_id(row.get("ID_Disciplina"))
                if did:
                    nomes_disc[did] = str(row.get("Nome_Disciplina") or "").strip()
    except Exception:
        pass

    linhas: list[dict] = []
    for m in mats:
        oid = m.get("id_oferta") or ""
        ofe = ofertas.get(oid) or {}
        id_disc = str(ofe.get("id_disciplina") or "").strip()
        g = grupos.get(m["grupo_id"]) if m.get("grupo_id") else None
        sala = salas.get(g["sala_id"]) if g and g.get("sala_id") else None
        linhas.append(
            {
                "matricula_id": m["id"],
                "id_oferta": oid,
                "id_disciplina": id_disc,
                "disciplina": nomes_disc.get(id_disc) or id_disc or "—",
                "trimestre": ofe.get("id_trimestre") or "",
                "status_oferta": ofe.get("status") or "",
                "fase": ofe.get("fase") or "",
                "situacao": m.get("situacao") or "",
                "pendencia": m.get("pendencia"),
                "data_situacao": m.get("data_situacao_efetiva") or "",
                "grupo": (g or {}).get("nome") or "",
                "sala": (sala or {}).get("nome") or "",
                "grupo_id": m.get("grupo_id"),
                "observacao": m.get("observacao") or "",
            }
        )

    ordem_status = {"Ativa": 0, "Planejada": 1, "Encerrada": 2}
    return sorted(
        linhas,
        key=lambda r: (
            ordem_status.get(str(r.get("status_oferta") or ""), 9),
            chave_ordenacao_texto(r.get("trimestre")),
            chave_ordenacao_texto(r.get("disciplina")),
            chave_ordenacao_texto(r.get("id_oferta")),
        ),
    )


def enriquecer_historico_com_notas(
    historico: list[dict], email: str, *, incluir_notas: bool
) -> list[dict]:
    """Anexa nota final do boletim (Sheets) quando solicitado e houver grupo."""
    if not incluir_notas or not historico:
        for r in historico:
            r.setdefault("nota_final", None)
            r.setdefault("resultado_boletim", None)
        return historico

    from domain.notas import calcular_boletim_aluno, nota_final_boletim, status_academico

    email_l = (email or "").strip().lower()
    for r in historico:
        r["nota_final"] = None
        r["resultado_boletim"] = None
        id_disc = str(r.get("id_disciplina") or "").strip()
        grupo = str(r.get("grupo") or "").strip()
        sala = str(r.get("sala") or "").strip()
        if not id_disc or not grupo or not email_l:
            continue
        try:
            df = calcular_boletim_aluno(email_l, id_disc, grupo, sala)
            nota = nota_final_boletim(df)
            r["nota_final"] = nota
            if nota is not None:
                r["resultado_boletim"] = status_academico(None, nota)
        except Exception:
            continue
    return historico

