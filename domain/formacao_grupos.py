"""Formação de grupos por oferta (Supabase teste)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from data import supabase_academico as acad
from utils.disciplina import normalizar_id
from utils.ordenacao import chave_ordenacao_grupo, chave_ordenacao_texto

COLS_OFERTA = "id_oferta,id_disciplina,id_trimestre,status,fase,link_plataforma"
COLS_SALA = "id,id_oferta,nome,created_at"
COLS_GRUPO = "id,id_oferta,nome,sala_id,created_at"
COLS_MAT = "id,aluno_id,id_oferta,situacao,grupo_id"
COLS_ALUNO = "id,email,nome,status_curso,turma_vinculo,turma_ingresso"


def mapa_nomes_disciplinas() -> dict[str, str]:
    """ID_Disciplina normalizado → nome (planilha Disciplinas)."""
    try:
        from domain.cadastros import carregar_disciplinas

        df = carregar_disciplinas()
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    saida: dict[str, str] = {}
    for _, row in df.iterrows():
        did = normalizar_id(row.get("ID_Disciplina"))
        nome = str(row.get("Nome_Disciplina") or "").strip()
        if did and nome:
            saida[did] = nome
    return saida


def rotulo_oferta(o: dict, nomes: dict[str, str] | None = None) -> str:
    """Ex.: 20263TRIB · Tributário · Ativa · 2026-3"""
    oid = str(o.get("id_oferta") or "")
    disc = normalizar_id(o.get("id_disciplina"))
    nomes = nomes if nomes is not None else mapa_nomes_disciplinas()
    nome = nomes.get(disc) or disc or "—"
    status = o.get("status") or "—"
    trim = o.get("id_trimestre") or "—"
    return f"{oid} · {nome} · {status} · {trim}"


def listar_ofertas() -> list[dict]:
    ofertas = acad.listar("ofertas", COLS_OFERTA)

    def chave(o: dict):
        status = str(o.get("status") or "")
        # Ativa primeiro, depois Planejada, Encerrada
        ordem = {"Ativa": 0, "Planejada": 1, "Encerrada": 2}.get(status, 9)
        return (ordem, str(o.get("id_oferta") or ""))

    return sorted(ofertas, key=chave)


def oferta_padrao_id(ofertas: list[dict] | None = None) -> str | None:
    ofs = ofertas if ofertas is not None else listar_ofertas()
    for o in ofs:
        if o.get("status") == "Ativa":
            return o["id_oferta"]
    return ofs[0]["id_oferta"] if ofs else None


def salas_da_oferta(id_oferta: str) -> list[dict]:
    salas = [
        s for s in acad.listar("salas", COLS_SALA) if s.get("id_oferta") == id_oferta
    ]
    return sorted(salas, key=lambda s: str(s.get("nome") or "").lower())


def grupos_da_oferta(id_oferta: str) -> list[dict]:
    grupos = [
        g for g in acad.listar("grupos", COLS_GRUPO) if g.get("id_oferta") == id_oferta
    ]
    return sorted(grupos, key=lambda g: chave_ordenacao_grupo(g.get("nome")))


def criar_sala(id_oferta: str, nome: str) -> tuple[dict | None, str | None]:
    nome = (nome or "").strip()
    if not nome:
        return None, "Informe o nome da sala."
    existentes = salas_da_oferta(id_oferta)
    if any(str(s.get("nome") or "").lower() == nome.lower() for s in existentes):
        return None, f"Já existe sala '{nome}' nesta oferta."
    criados = acad.inserir("salas", {"id_oferta": id_oferta, "nome": nome})
    if not criados:
        return None, "Falha ao criar sala."
    return criados[0], None


def criar_grupo(
    id_oferta: str, nome: str, sala_id: str | None
) -> tuple[dict | None, str | None]:
    nome = (nome or "").strip()
    if not nome:
        return None, "Informe o nome do grupo."
    existentes = grupos_da_oferta(id_oferta)
    if any(str(g.get("nome") or "").lower() == nome.lower() for g in existentes):
        return None, f"Já existe grupo '{nome}' nesta oferta."
    payload: dict[str, Any] = {"id_oferta": id_oferta, "nome": nome}
    if sala_id:
        payload["sala_id"] = sala_id
    criados = acad.inserir("grupos", payload)
    if not criados:
        return None, "Falha ao criar grupo."
    return criados[0], None


def atualizar_grupo(
    grupo_id: str, *, nome: str | None = None, sala_id: str | None = ...
) -> tuple[dict | None, str | None]:
    payload: dict[str, Any] = {}
    if nome is not None:
        nome_limpo = nome.strip()
        if not nome_limpo:
            return None, "Nome do grupo não pode ser vazio."
        payload["nome"] = nome_limpo
    if sala_id is not ...:
        payload["sala_id"] = sala_id
    if not payload:
        return None, "Nada para atualizar."
    atualizados = acad.atualizar("grupos", payload, id=grupo_id)
    if not atualizados:
        return None, "Falha ao atualizar grupo."
    return atualizados[0], None


def roster_oferta(id_oferta: str) -> list[dict]:
    """Matrículas cursando + dados do aluno + nome do grupo."""
    mats = [
        m
        for m in acad.listar("matriculas", COLS_MAT)
        if m.get("id_oferta") == id_oferta and m.get("situacao") == "cursando"
    ]
    alunos = {a["id"]: a for a in acad.listar("alunos", COLS_ALUNO)}
    grupos = {g["id"]: g for g in grupos_da_oferta(id_oferta)}
    salas = {s["id"]: s for s in salas_da_oferta(id_oferta)}

    roster = []
    for m in mats:
        a = alunos.get(m["aluno_id"], {})
        g = grupos.get(m["grupo_id"]) if m.get("grupo_id") else None
        sala = salas.get(g["sala_id"]) if g and g.get("sala_id") else None
        roster.append(
            {
                "matricula_id": m["id"],
                "aluno_id": m["aluno_id"],
                "email": a.get("email") or "",
                "nome": a.get("nome") or "",
                "status_curso": a.get("status_curso") or "",
                "turma": a.get("turma_vinculo") or a.get("turma_ingresso") or "",
                "grupo_id": m.get("grupo_id"),
                "grupo_nome": g.get("nome") if g else "",
                "sala_nome": sala.get("nome") if sala else "",
                "sem_grupo": not bool(m.get("grupo_id")),
            }
        )
    return sorted(
        roster,
        key=lambda r: (
            r["sem_grupo"],
            chave_ordenacao_texto(r["nome"]),
            chave_ordenacao_texto(r["email"]),
        ),
    )

def contagens_grupos(roster: list[dict], grupos: list[dict]) -> dict[str, int]:
    cnt = Counter(r["grupo_id"] for r in roster if r.get("grupo_id"))
    out = {g["id"]: int(cnt.get(g["id"], 0)) for g in grupos}
    out["__sem__"] = sum(1 for r in roster if r.get("sem_grupo"))
    return out


def atribuir_grupo(matricula_id: str, grupo_id: str | None) -> tuple[bool, str | None]:
    acad.atualizar("matriculas", {"grupo_id": grupo_id}, id=matricula_id)
    return True, None
