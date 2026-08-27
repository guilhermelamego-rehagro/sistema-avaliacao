"""Filtros operacionais cruzando Entrância (Sheets) com Supabase (teste).

Política operacional (modo=operacional):
  - status_curso != matriculado → ocultar
  - matrícula na oferta: só situacao cursando (inclui pendencia 2ª chamada)
  - exigir_grupo=True (pares / banca / ordem): precisa ter grupo_id
  - exigir_grupo=False (presença / orientador): sem grupo permanece visível

Modo completo (MEC / auditoria):
  - mantém todos que estiveram na entrância ou com matrícula na oferta
  - enriquece Status_Curso, Situacao_Oferta, Pendencia, Gera_Presenca

Em ambiente=producao (sem tabelas acadêmicas): retorna o DataFrame intacto.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from auth.supabase_auth import ambiente_app
from data.supabase_academico import AmbienteProducaoError, academico_habilitado
from utils.disciplina import normalizar_id
from utils.ordenacao import chave_ordenacao_texto


def _cache_epoch() -> int:
    return int(st.session_state.get("_acad_cache_epoch", 0))


@st.cache_data(ttl=45, show_spinner=False)
def _snapshot_operacional(epoch: int) -> dict:
    _ = epoch
    from data import supabase_academico as acad

    alunos = acad.listar(
        "alunos", "id,email,nome,status_curso,turma_vinculo,turma_ingresso"
    )
    mats = acad.listar(
        "matriculas", "aluno_id,id_oferta,situacao,pendencia,grupo_id"
    )
    ofertas = acad.listar("ofertas", "id_oferta,id_disciplina,status")
    grupos = acad.listar("grupos", "id,id_oferta,nome,sala_id")
    salas = acad.listar("salas", "id,id_oferta,nome")

    status_por_email = {
        str(a.get("email") or "").strip().lower(): str(a.get("status_curso") or "")
        for a in alunos
        if a.get("email")
    }
    aluno_por_email = {
        str(a.get("email") or "").strip().lower(): a
        for a in alunos
        if a.get("email")
    }
    id_por_email = {email: a["id"] for email, a in aluno_por_email.items()}
    mats_por_aluno: dict[str, list[dict]] = {}
    for m in mats:
        mats_por_aluno.setdefault(m["aluno_id"], []).append(m)
    grupo_por_id = {g["id"]: g for g in grupos}
    sala_por_id = {s["id"]: s for s in salas}

    return {
        "status_por_email": status_por_email,
        "aluno_por_email": aluno_por_email,
        "id_por_email": id_por_email,
        "mats_por_aluno": mats_por_aluno,
        "ofertas": list(ofertas),
        "grupo_por_id": grupo_por_id,
        "sala_por_id": sala_por_id,
    }


def resolver_ofertas_disciplina(id_disciplina: str, ofertas: list[dict]) -> list[str]:
    """IDs de oferta que correspondem ao código da Entrância/Sheets."""
    chave = normalizar_id(id_disciplina)
    if not chave:
        return []
    ids: list[str] = []
    for o in ofertas:
        oid = str(o.get("id_oferta") or "")
        disc = normalizar_id(o.get("id_disciplina"))
        if disc == chave or oid == chave or oid.startswith(chave) or chave.startswith(disc):
            ids.append(oid)
        elif chave in oid or oid.endswith(chave):
            ids.append(oid)
    if len(ids) > 1:
        ativas = [
            o["id_oferta"]
            for o in ofertas
            if o["id_oferta"] in ids and o.get("status") == "Ativa"
        ]
        if len(ativas) == 1:
            return ativas
    return list(dict.fromkeys(ids))


def gera_presenca(status_curso: str, situacao: str) -> bool:
    return status_curso == "matriculado" and situacao == "cursando"


def _mat_relevante(mats: list[dict], ofertas_ids: list[str]) -> dict | None:
    if not mats:
        return None
    no_oferta = [m for m in mats if m.get("id_oferta") in ofertas_ids]
    if not no_oferta:
        return None
    for m in no_oferta:
        if m.get("situacao") == "cursando":
            return m
    return no_oferta[0]


def info_academica_disciplina(id_disciplina: str) -> dict[str, dict] | None:
    """email → metadados acadêmicos da disciplina/oferta."""
    if not academico_habilitado():
        return None
    try:
        snap = _snapshot_operacional(_cache_epoch())
    except AmbienteProducaoError:
        return None
    except Exception:
        return None

    ofertas_ids = resolver_ofertas_disciplina(id_disciplina, snap["ofertas"])
    info: dict[str, dict] = {}
    for email, aluno in snap["aluno_por_email"].items():
        aluno_id = aluno["id"]
        mat = _mat_relevante(
            snap["mats_por_aluno"].get(aluno_id, []), ofertas_ids
        )
        if not mat:
            continue
        g = snap["grupo_por_id"].get(mat.get("grupo_id") or "")
        sala = (
            snap["sala_por_id"].get((g or {}).get("sala_id") or "") if g else None
        )
        st_curso = snap["status_por_email"].get(email, "")
        situacao = str(mat.get("situacao") or "")
        info[email] = {
            "nome": aluno.get("nome") or "",
            "status_curso": st_curso,
            "situacao": situacao,
            "pendencia": mat.get("pendencia"),
            "grupo": (g or {}).get("nome") or "",
            "sala": (sala or {}).get("nome") or "",
            "turma": aluno.get("turma_vinculo")
            or aluno.get("turma_ingresso")
            or "",
            "gera_presenca": gera_presenca(st_curso, situacao),
        }
    return info


def emails_permitidos(
    id_disciplina: str,
    *,
    exigir_grupo: bool = False,
) -> set[str] | None:
    """
    Conjunto de e-mails autorizados na operação da disciplina.
    None = não filtrar (produção / falha).
    """
    info = info_academica_disciplina(id_disciplina)
    if info is None:
        return None
    permitidos: set[str] = set()
    for email, meta in info.items():
        if not meta.get("gera_presenca"):
            continue
        if exigir_grupo and not meta.get("grupo"):
            continue
        permitidos.add(email)
    return permitidos


def filtrar_entrancia_operacional(
    df: pd.DataFrame,
    id_disciplina: str,
    *,
    exigir_grupo: bool = False,
    col_email: str = "Email_Pessoal",
) -> pd.DataFrame:
    """Filtra DataFrame da Entrância (modo operacional)."""
    if df is None or df.empty:
        return df
    if ambiente_app() != "teste":
        return df
    permitidos = emails_permitidos(id_disciplina, exigir_grupo=exigir_grupo)
    if permitidos is None:
        return df
    if col_email not in df.columns:
        return df
    emails = df[col_email].astype(str).str.strip().str.lower()
    return df.loc[emails.isin(permitidos)].copy()


def preparar_alunos_presenca(
    df_entrancia_disc: pd.DataFrame,
    id_disciplina: str,
    *,
    modo: str = "operacional",
) -> pd.DataFrame:
    """
    Monta o quadro de alunos para presença.

    modo=operacional → só quem gera presença
    modo=completo → todos da entrância + matrículas da oferta (MEC/auditoria)
    """
    base = (
        df_entrancia_disc.copy()
        if df_entrancia_disc is not None
        else pd.DataFrame()
    )
    info = info_academica_disciplina(id_disciplina)

    if info is None or ambiente_app() != "teste":
        if base.empty:
            return base
        out = base.copy()
        out["Gera_Presenca"] = True
        out["Status_Curso"] = ""
        out["Situacao_Oferta"] = ""
        out["Pendencia"] = ""
        return out

    rows_por_email: dict[str, dict] = {}
    if not base.empty and "Email_Pessoal" in base.columns:
        for _, row in base.iterrows():
            email = str(row.get("Email_Pessoal") or "").strip().lower()
            if not email or "@" not in email:
                continue
            rows_por_email[email] = row.to_dict()

    emails = set(rows_por_email)
    if modo == "completo":
        emails |= set(info.keys())
    else:
        emails = {e for e in emails if info.get(e, {}).get("gera_presenca")}
        emails -= {e for e in rows_por_email if e not in info}

    linhas = []
    for email in emails:
        meta = info.get(email, {})
        ent = rows_por_email.get(email, {})
        situacao = meta.get("situacao") or ""
        st_curso = meta.get("status_curso") or ""
        gera = bool(meta.get("gera_presenca")) if meta else False
        pend = meta.get("pendencia") or ""
        linhas.append(
            {
                "Email_Pessoal": email,
                "Nome_Completo": ent.get("Nome_Completo")
                or meta.get("nome")
                or email,
                "Sala": str(ent.get("Sala") or meta.get("sala") or "").strip(),
                "Grupo": str(ent.get("Grupo") or meta.get("grupo") or "").strip(),
                "ID_Disciplina": ent.get("ID_Disciplina") or id_disciplina,
                "Turma_Ingresso": str(
                    ent.get("Turma_Ingresso") or meta.get("turma") or ""
                ).strip(),
                "Status_Curso": st_curso,
                "Situacao_Oferta": situacao,
                "Pendencia": "segunda_chamada"
                if pend == "segunda_chamada"
                else "",
                "Gera_Presenca": gera,
            }
        )

    out = pd.DataFrame(linhas)
    if out.empty:
        return out
    out["_ord_nome"] = out["Nome_Completo"].map(chave_ordenacao_texto)
    out = out.sort_values(
        by=["Gera_Presenca", "_ord_nome"], ascending=[False, True]
    ).drop(columns=["_ord_nome"])
    return out.reset_index(drop=True)
