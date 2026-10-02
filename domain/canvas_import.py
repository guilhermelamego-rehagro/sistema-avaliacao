"""Importação de atividades individuais a partir do export de notas do Canvas."""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from config import ABAS_AVALIACAO
from data.sheets import garantir_aba_avaliacao, ler_aba, salvar_aba
from utils.disciplina import normalizar_id

ABA_ATIVIDADES = "Atividades_Individuais"
ABA_MAPA = "Canvas_Alunos"
DESCARTAR = "DESCARTAR"

COL_NOME = "Student"
COL_ID = "ID"
COL_LOGIN = "SIS Login ID"
COL_SECAO = "Section"

_RE_ATIVIDADE = re.compile(r"\((\d+)\)\s*$")
_RE_PRAZO = re.compile(r"(\d{2}/\d{2}/\d{4})")
_RE_CICLO = re.compile(r"ciclo\s+de\s+entregas\s*(\d+)", re.IGNORECASE)
_PARTICULAS = {"de", "da", "do", "das", "dos", "e"}
_TZ = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class AtividadeCanvas:
    id: str
    coluna: str
    ciclo: str
    prazo: pd.Timestamp | None
    pontos: float


def _hoje() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(_TZ).date())


def _agora() -> str:
    return datetime.now(_TZ).strftime("%d/%m/%Y %H:%M:%S")


def _num_br(valor) -> float | None:
    texto = str(valor if valor is not None else "").strip()
    if not texto or texto.lower() in {"nan", "none", "(somente leitura)", "-"}:
        return None
    texto = texto.replace(".", "").replace(",", ".") if "," in texto else texto
    try:
        return float(texto)
    except ValueError:
        return None


def normalizar_nome(nome) -> str:
    """'Sobrenome, Nome' → 'nome sobrenome'; sem acento, minúsculo, só letras."""
    texto = str(nome or "").strip()
    if "," in texto:
        sobrenome, primeiro = texto.split(",", 1)
        texto = f"{primeiro.strip()} {sobrenome.strip()}"
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    texto = re.sub(r"[^a-z ]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _tokens(nome_normalizado: str) -> frozenset[str]:
    return frozenset(t for t in nome_normalizado.split() if t not in _PARTICULAS)


def ler_export_canvas(conteudo: bytes, nome_arquivo: str) -> tuple[pd.DataFrame, list[AtividadeCanvas]]:
    """Lê o export de notas do Canvas (uma coluna por atividade)."""
    if nome_arquivo.lower().endswith(".xlsx"):
        df = pd.read_excel(io.BytesIO(conteudo), dtype=str)
    else:
        df = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                df = pd.read_csv(io.BytesIO(conteudo), dtype=str, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        if df is None:
            raise ValueError("Não foi possível ler o arquivo (codificação desconhecida).")

    df.columns = [str(c).strip() for c in df.columns]
    faltando = [c for c in (COL_NOME, COL_ID) if c not in df.columns]
    if faltando:
        raise ValueError(
            "O arquivo não parece um export de notas do Canvas "
            f"(colunas ausentes: {', '.join(faltando)})."
        )

    nomes = df[COL_NOME].fillna("").astype(str).str.strip()
    linha_pontos = df[nomes.str.lower().str.startswith("points possible")]
    df = df[~nomes.str.lower().str.startswith("points possible") & nomes.ne("")].copy()

    atividades: list[AtividadeCanvas] = []
    for col in df.columns:
        m = _RE_ATIVIDADE.search(col)
        if not m:
            continue
        pontos = _num_br(linha_pontos.iloc[0][col]) if not linha_pontos.empty else None
        m_prazo = _RE_PRAZO.search(col)
        prazo = (
            pd.to_datetime(m_prazo.group(1), format="%d/%m/%Y", errors="coerce") if m_prazo else None
        )
        m_ciclo = _RE_CICLO.search(col)
        atividades.append(
            AtividadeCanvas(
                id=m.group(1),
                coluna=col,
                ciclo=m_ciclo.group(1) if m_ciclo else "",
                prazo=None if prazo is None or pd.isna(prazo) else pd.Timestamp(prazo),
                pontos=pontos if pontos and pontos > 0 else 10.0,
            )
        )
    if not atividades:
        raise ValueError("Nenhuma coluna de atividade encontrada (esperado nome terminando em '(código)').")

    df[COL_ID] = df[COL_ID].fillna("").astype(str).str.strip()
    for col in (COL_LOGIN, COL_SECAO):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    return df.reset_index(drop=True), atividades


def carregar_alunos_disciplina(id_disciplina: str) -> pd.DataFrame:
    """Alunos vinculados à disciplina na Entrância (um por e-mail)."""
    df = ler_aba("Entrancia_Turma")
    if df.empty:
        return pd.DataFrame(columns=["Email", "Nome", "Grupo", "Sala"])
    id_d = normalizar_id(id_disciplina)
    out = df[df["ID_Disciplina"].map(normalizar_id) == id_d].copy()
    out["Email"] = out["Email_Pessoal"].astype(str).str.strip().str.lower()
    out["Nome"] = out["Nome_Completo"].astype(str).str.strip()
    for col in ("Grupo", "Sala"):
        valores = out[col] if col in out.columns else pd.Series("", index=out.index)
        out[col] = valores.fillna("").astype(str).str.strip().replace({"nan": "", "None": ""})
    out = out[out["Email"].str.contains("@", na=False)]
    return out.drop_duplicates("Email")[["Email", "Nome", "Grupo", "Sala"]].reset_index(drop=True)


def carregar_mapa_canvas() -> dict[str, str]:
    """ID do aluno no Canvas → e-mail institucional (ou DESCARTAR)."""
    garantir_aba_avaliacao(ABA_MAPA)
    try:
        df = ler_aba(ABA_MAPA)
    except Exception:
        return {}
    if df.empty or "ID_Canvas" not in df.columns:
        return {}
    mapa: dict[str, str] = {}
    for _, row in df.iterrows():
        idc = str(row.get("ID_Canvas", "")).strip()
        email = str(row.get("Email_Aluno", "")).strip()
        if idc and email:
            mapa[idc] = email if email == DESCARTAR else email.lower()
    return mapa


def cruzar_alunos(
    df_canvas: pd.DataFrame,
    alunos_disc: pd.DataFrame,
    base_alunos: pd.DataFrame | None = None,
    mapa_salvo: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    Associa cada linha do Canvas a um aluno do app.

    Ordem: vínculo salvo (ID do Canvas) → nome exato → nome parcial
    (todos os nomes de um lado contidos no outro, candidato único).
    """
    mapa_salvo = mapa_salvo or {}
    alunos = alunos_disc.copy()
    alunos["_n"] = alunos["Nome"].map(normalizar_nome)
    alunos["_t"] = alunos["_n"].map(_tokens)
    nome_por_email = dict(zip(alunos["Email"], alunos["Nome"]))
    por_nome: dict[str, list[str]] = {}
    for email, n in zip(alunos["Email"], alunos["_n"]):
        por_nome.setdefault(n, []).append(email)

    base_por_nome: dict[str, str] = {}
    if base_alunos is not None and not base_alunos.empty:
        for _, b in base_alunos.iterrows():
            base_por_nome.setdefault(
                normalizar_nome(b.get("Nome_Completo", "")),
                str(b.get("Email_Pessoal", "")).strip().lower(),
            )

    usados: set[str] = set()
    linhas = []
    for _, row in df_canvas.iterrows():
        id_canvas = str(row.get(COL_ID, "")).strip()
        nome_canvas = str(row.get(COL_NOME, "")).strip()
        login = str(row.get(COL_LOGIN, "")).strip()
        n = normalizar_nome(nome_canvas)
        t = _tokens(n)
        email, metodo, obs = "", "", ""

        salvo = mapa_salvo.get(id_canvas, "")
        if salvo == DESCARTAR:
            metodo, obs = "descartado", "Descartado em importação anterior"
        elif salvo:
            email, metodo = salvo, "vinculo_salvo"
        else:
            exatos = [e for e in por_nome.get(n, []) if e not in usados]
            if len(exatos) == 1:
                email, metodo = exatos[0], "nome_exato"
            elif len(exatos) > 1:
                obs = "Nome repetido na disciplina — escolha manualmente"
            else:
                parciais = [
                    e
                    for e, te in zip(alunos["Email"], alunos["_t"])
                    if e not in usados
                    and min(len(te), len(t)) >= 2
                    and (te <= t or t <= te)
                ]
                if len(parciais) == 1:
                    email, metodo = parciais[0], "nome_parcial"
                elif len(parciais) > 1:
                    obs = "Mais de um nome parecido na disciplina — escolha manualmente"

        if email and email in usados:
            obs = f"E-mail {email} já associado a outra linha do Canvas"
            email, metodo = "", ""
        if not metodo:
            if "@" not in login:
                obs = obs or "Login sem e-mail (provável aluno de teste do Canvas)"
            elif n in base_por_nome:
                obs = obs or f"Existe no app ({base_por_nome[n]}), mas não está vinculado a esta disciplina"
            else:
                obs = obs or "Nome não encontrado no app"
        if email:
            usados.add(email)

        linhas.append(
            {
                "ID_Canvas": id_canvas,
                "Nome_Canvas": nome_canvas,
                "Turma_Canvas": str(row.get(COL_SECAO, "")).strip(),
                "Login_Canvas": login,
                "Email_App": email,
                "Nome_App": nome_por_email.get(email, ""),
                "Metodo": metodo,
                "Observacao": obs,
            }
        )
    return pd.DataFrame(linhas)


def alunos_app_sem_canvas(alunos_disc: pd.DataFrame, cruzamento: pd.DataFrame) -> pd.DataFrame:
    casados = set(cruzamento.loc[cruzamento["Email_App"].ne(""), "Email_App"])
    out = alunos_disc[~alunos_disc["Email"].isin(casados)].copy()
    out["Observacao"] = out["Grupo"].map(lambda g: "Sem grupo (possível desistente)" if not g else "")
    return out.reset_index(drop=True)


def montar_notas(
    df_canvas: pd.DataFrame,
    atividades: list[AtividadeCanvas],
    cruzamento: pd.DataFrame,
    hoje: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Converte para uma linha por aluno+atividade, nota 0–100.

    Célula vazia vira 0 se o prazo já passou e a atividade já tem nota de
    alguém na turma; caso contrário fica pendente (não é gravada).
    """
    hoje = hoje or _hoje()
    corrigidas = {
        a.id: bool(df_canvas[a.coluna].map(_num_br).notna().any()) for a in atividades
    }
    email_por_id = dict(zip(cruzamento["ID_Canvas"], cruzamento["Email_App"]))
    nome_por_id = dict(zip(cruzamento["ID_Canvas"], cruzamento["Nome_App"]))

    linhas = []
    for _, row in df_canvas.iterrows():
        id_canvas = str(row.get(COL_ID, "")).strip()
        email = email_por_id.get(id_canvas, "")
        if not email:
            continue
        for a in atividades:
            bruto = _num_br(row.get(a.coluna))
            if bruto is not None:
                situacao, nota = "nota", round(bruto / a.pontos * 100, 2)
            elif a.prazo is not None and a.prazo < hoje and corrigidas[a.id]:
                situacao, nota = "zero_vencida", 0.0
            else:
                situacao, nota = "pendente", None
            linhas.append(
                {
                    "Email_Aluno": email,
                    "Nome_Aluno": nome_por_id.get(id_canvas, "") or str(row.get(COL_NOME, "")),
                    "ID_Atividade": a.id,
                    "Atividade": a.coluna,
                    "Ciclo": a.ciclo,
                    "Prazo": a.prazo.strftime("%d/%m/%Y") if a.prazo is not None else "",
                    "Nota_Canvas": bruto,
                    "Nota": nota,
                    "Situacao": situacao,
                }
            )
    return pd.DataFrame(linhas)


def _id_atividade(texto) -> str:
    m = _RE_ATIVIDADE.search(str(texto or "").strip())
    return m.group(1) if m else ""


def contar_substituicoes(id_disciplina: str, ids_atividades: set[str]) -> int:
    try:
        df = ler_aba(ABA_ATIVIDADES)
    except Exception:
        return 0
    if df.empty:
        return 0
    mask = (df["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disciplina)) & df[
        "Atividade"
    ].map(_id_atividade).isin(ids_atividades)
    return int(mask.sum())


def gravar_importacao(
    id_disciplina: str,
    notas: pd.DataFrame,
    ids_atividades: set[str],
    vinculos: pd.DataFrame,
    email_responsavel: str,
) -> int:
    """
    Substitui as notas destas atividades na disciplina e salva os vínculos
    Canvas → e-mail institucional para as próximas importações.
    """
    colunas = ABAS_AVALIACAO[ABA_ATIVIDADES]
    id_d = normalizar_id(id_disciplina)
    agora = _agora()

    garantir_aba_avaliacao(ABA_ATIVIDADES)
    atual = ler_aba(ABA_ATIVIDADES)
    if not atual.empty:
        manter = ~(
            (atual["ID_Disciplina"].map(normalizar_id) == id_d)
            & atual["Atividade"].map(_id_atividade).isin(ids_atividades)
        )
        atual = atual[manter]

    gravar = notas[notas["Situacao"].ne("pendente")]
    novas = pd.DataFrame(
        {
            "ID_Disciplina": id_d,
            "Semana": gravar["Prazo"].values,
            "Atividade": gravar["Atividade"].values,
            "Email_Aluno": gravar["Email_Aluno"].values,
            "Nome_Aluno": gravar["Nome_Aluno"].values,
            "Nota": gravar["Nota"].map(lambda v: f"{float(v):.2f}").values,
            "Origem": "Canvas",
            "Data_Importacao": agora,
        }
    )
    salvar_aba(ABA_ATIVIDADES, pd.concat([atual, novas], ignore_index=True), colunas)

    if vinculos is not None and not vinculos.empty:
        garantir_aba_avaliacao(ABA_MAPA)
        mapa_cols = ABAS_AVALIACAO[ABA_MAPA]
        try:
            mapa = ler_aba(ABA_MAPA)
        except Exception:
            mapa = pd.DataFrame(columns=mapa_cols)
        if not mapa.empty:
            mapa = mapa[~mapa["ID_Canvas"].astype(str).str.strip().isin(set(vinculos["ID_Canvas"]))]
        novos = vinculos.assign(Atualizado_Em=agora, Email_Responsavel=email_responsavel)
        salvar_aba(ABA_MAPA, pd.concat([mapa, novos], ignore_index=True), mapa_cols)

    return len(novas)
