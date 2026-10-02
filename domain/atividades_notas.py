"""
Notas efetivas das atividades individuais.

Cada célula aluno × atividade pode ter uma linha importada do Canvas e uma
linha de edição docente (Origem = "Edição"). A edição prevalece e não é
tocada por novas importações. A liberação para o aluno é por atividade.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from config import ABAS_AVALIACAO
from data.sheets import garantir_aba_avaliacao, ler_aba, limpar_cache_planilhas, planilha, salvar_aba
from utils.disciplina import normalizar_id

ABA_NOTAS = "Atividades_Individuais"
ABA_LIBERACAO = "Liberacao_Atividades"
ABA_LOG = "Log_Notas_Atividades"
ORIGEM_EDICAO = "Edição"

ACAO_EDICAO = "Edição"
ACAO_REVERSAO = "Reversão"
ACAO_IMPORTACAO = "Importação Canvas"
ACAO_LIBERACAO = "Liberação"
ACAO_OCULTACAO = "Ocultação"

_RE_ATIVIDADE = re.compile(r"\((\d+)\)\s*$")
_VALORES_SIM = {"sim", "s", "true", "1", "liberado", "liberada"}
_TZ = ZoneInfo("America/Sao_Paulo")

COLUNAS_EFETIVAS = [
    "Email_Aluno",
    "Nome_Aluno",
    "ID_Atividade",
    "Atividade",
    "Prazo",
    "Nota",
    "Nota_Canvas",
    "Editada",
]


def _agora() -> str:
    return datetime.now(_TZ).strftime("%d/%m/%Y %H:%M:%S")


def id_atividade(texto) -> str:
    """Código do Canvas no fim do nome ('... (17033)'); senão o próprio texto."""
    bruto = str(texto or "").strip()
    m = _RE_ATIVIDADE.search(bruto)
    return m.group(1) if m else bruto


def nome_curto_atividade(texto) -> str:
    return _RE_ATIVIDADE.sub("", str(texto or "")).strip()


def _numero(valor) -> float | None:
    texto = str(valor if valor is not None else "").strip().replace(",", ".")
    if not texto or texto.lower() in {"nan", "none"}:
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def formatar_nota(valor) -> str:
    return "" if valor is None or pd.isna(valor) else f"{float(valor):.2f}"


def _ler(aba: str) -> pd.DataFrame:
    try:
        df = ler_aba(aba)
    except Exception:
        df = pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=ABAS_AVALIACAO[aba])
    return df


def _linhas_disciplina(id_disciplina: str) -> pd.DataFrame:
    df = _ler(ABA_NOTAS)
    if df.empty:
        return df
    df = df[df["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disciplina)].copy()
    df["Email_Aluno"] = df["Email_Aluno"].astype(str).str.strip().str.lower()
    df["ID_Atividade"] = df["Atividade"].map(id_atividade)
    df["Nota"] = pd.to_numeric(df["Nota"].map(_numero), errors="coerce")
    origem = df["Origem"] if "Origem" in df.columns else pd.Series("", index=df.index)
    df["_edicao"] = origem.astype(str).str.strip() == ORIGEM_EDICAO
    return df


def notas_efetivas(id_disciplina: str) -> pd.DataFrame:
    """Uma linha por aluno × atividade: nota vigente, valor do Canvas e se foi editada."""
    df = _linhas_disciplina(id_disciplina)
    if df.empty:
        return pd.DataFrame(columns=COLUNAS_EFETIVAS)

    chave = ["Email_Aluno", "ID_Atividade"]
    campos = chave + ["Nome_Aluno", "Atividade", "Semana", "Nota"]
    canvas = df[~df["_edicao"]].drop_duplicates(chave, keep="last")[campos]
    edicao = df[df["_edicao"]].drop_duplicates(chave, keep="last")[campos].assign(_ed=True)
    m = canvas.merge(edicao, on=chave, how="outer", suffixes=("_c", "_e"))
    editada = m["_ed"].eq(True)

    return pd.DataFrame(
        {
            "Email_Aluno": m["Email_Aluno"],
            "Nome_Aluno": m["Nome_Aluno_c"].combine_first(m["Nome_Aluno_e"]),
            "ID_Atividade": m["ID_Atividade"],
            "Atividade": m["Atividade_c"].combine_first(m["Atividade_e"]),
            "Prazo": m["Semana_c"].combine_first(m["Semana_e"]).fillna("").astype(str),
            "Nota": m["Nota_e"].where(editada, m["Nota_c"]),
            "Nota_Canvas": m["Nota_c"],
            "Editada": editada,
        }
    ).reset_index(drop=True)


def catalogo_atividades(efetivas: pd.DataFrame) -> pd.DataFrame:
    """Atividades da disciplina ordenadas por prazo."""
    if efetivas.empty:
        return pd.DataFrame(columns=["ID_Atividade", "Atividade", "Prazo"])
    cat = (
        efetivas.sort_values("Prazo")
        .groupby("ID_Atividade", as_index=False)
        .agg(Atividade=("Atividade", "first"), Prazo=("Prazo", "first"))
    )
    cat["_prazo"] = pd.to_datetime(cat["Prazo"], format="%d/%m/%Y", errors="coerce")
    return cat.sort_values(["_prazo", "ID_Atividade"]).drop(columns="_prazo").reset_index(drop=True)


def nota_atividades_aluno(
    email: str, id_disciplina: str, *, somente_liberadas: bool = False
) -> tuple[float | None, str]:
    df = notas_efetivas(id_disciplina)
    if df.empty:
        return None, "Sem atividades importadas"
    df = df[df["Email_Aluno"] == str(email).strip().lower()]
    if somente_liberadas:
        df = df[df["ID_Atividade"].isin(atividades_liberadas(id_disciplina))]
    df = df[df["Nota"].notna()]
    if df.empty:
        return None, "Sem notas liberadas" if somente_liberadas else "Sem notas de atividades"
    return round(float(df["Nota"].mean()), 1), f"Média de {len(df)} atividade(s)"


# --- Liberação por atividade ---


def atividades_liberadas(id_disciplina: str) -> set[str]:
    df = _ler(ABA_LIBERACAO)
    if df.empty:
        return set()
    df = df[df["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disciplina)]
    ultimo = df.drop_duplicates("ID_Atividade", keep="last")
    return {
        str(r["ID_Atividade"]).strip()
        for _, r in ultimo.iterrows()
        if str(r.get("Liberado", "")).strip().lower() in _VALORES_SIM
    }


def salvar_liberacao_atividades(
    id_disciplina: str,
    mudancas: dict[str, bool],
    nomes: dict[str, str],
    email_responsavel: str,
    nome_responsavel: str,
) -> None:
    if not mudancas:
        return
    id_d = normalizar_id(id_disciplina)
    agora = _agora()
    garantir_aba_avaliacao(ABA_LIBERACAO)
    planilha.worksheet(ABA_LIBERACAO).append_rows(
        [
            [id_d, ida, nomes.get(ida, ""), "Sim" if lib else "Não", agora, email_responsavel, nome_responsavel]
            for ida, lib in mudancas.items()
        ]
    )
    registrar_historico(
        [
            {
                "ID_Disciplina": id_d,
                "ID_Atividade": ida,
                "Atividade": nomes.get(ida, ""),
                "Acao": ACAO_LIBERACAO if lib else ACAO_OCULTACAO,
            }
            for ida, lib in mudancas.items()
        ],
        email_responsavel,
        nome_responsavel,
    )


# --- Edições docentes ---


def _sem_edicoes(atual: pd.DataFrame, id_d: str, pares: set[tuple[str, str]]) -> pd.DataFrame:
    if atual.empty or not pares:
        return atual
    da_disc = atual["ID_Disciplina"].map(normalizar_id) == id_d
    edicao = atual["Origem"].astype(str).str.strip() == ORIGEM_EDICAO
    par = pd.Series(
        list(zip(atual["Email_Aluno"].astype(str).str.strip().str.lower(), atual["Atividade"].map(id_atividade))),
        index=atual.index,
    ).isin(pares)
    return atual[~(da_disc & edicao & par)]


def salvar_edicoes(
    id_disciplina: str,
    edicoes: list[dict],
    motivo: str,
    email_responsavel: str,
    nome_responsavel: str,
) -> int:
    """
    edicoes: Email_Aluno, Nome_Aluno, ID_Atividade, Atividade, Prazo, Nota_Anterior, Nota_Nova.
    Substitui edição anterior da mesma célula.
    """
    if not edicoes:
        return 0
    id_d = normalizar_id(id_disciplina)
    agora = _agora()
    garantir_aba_avaliacao(ABA_NOTAS)
    pares = {(e["Email_Aluno"], e["ID_Atividade"]) for e in edicoes}
    atual = _sem_edicoes(ler_aba(ABA_NOTAS), id_d, pares)
    novas = pd.DataFrame(
        [
            {
                "ID_Disciplina": id_d,
                "Semana": e.get("Prazo", ""),
                "Atividade": e["Atividade"],
                "Email_Aluno": e["Email_Aluno"],
                "Nome_Aluno": e["Nome_Aluno"],
                "Nota": formatar_nota(e["Nota_Nova"]),
                "Origem": ORIGEM_EDICAO,
                "Data_Importacao": agora,
            }
            for e in edicoes
        ]
    )
    salvar_aba(ABA_NOTAS, pd.concat([atual, novas], ignore_index=True), ABAS_AVALIACAO[ABA_NOTAS])
    registrar_historico(
        [
            {
                "ID_Disciplina": id_d,
                "ID_Atividade": e["ID_Atividade"],
                "Atividade": e["Atividade"],
                "Email_Aluno": e["Email_Aluno"],
                "Nome_Aluno": e["Nome_Aluno"],
                "Acao": ACAO_EDICAO,
                "Nota_Anterior": formatar_nota(e.get("Nota_Anterior")),
                "Nota_Nova": formatar_nota(e["Nota_Nova"]),
                "Motivo": motivo,
            }
            for e in edicoes
        ],
        email_responsavel,
        nome_responsavel,
    )
    return len(novas)


def reverter_edicoes(
    id_disciplina: str,
    celulas: pd.DataFrame,
    motivo: str,
    email_responsavel: str,
    nome_responsavel: str,
) -> int:
    """Remove a edição; a célula volta ao valor do Canvas (ou pendente)."""
    if celulas.empty:
        return 0
    id_d = normalizar_id(id_disciplina)
    pares = set(zip(celulas["Email_Aluno"], celulas["ID_Atividade"]))
    atual = ler_aba(ABA_NOTAS)
    salvar_aba(ABA_NOTAS, _sem_edicoes(atual, id_d, pares), ABAS_AVALIACAO[ABA_NOTAS])
    registrar_historico(
        [
            {
                "ID_Disciplina": id_d,
                "ID_Atividade": r["ID_Atividade"],
                "Atividade": r["Atividade"],
                "Email_Aluno": r["Email_Aluno"],
                "Nome_Aluno": r["Nome_Aluno"],
                "Acao": ACAO_REVERSAO,
                "Nota_Anterior": formatar_nota(r["Nota"]),
                "Nota_Nova": formatar_nota(r["Nota_Canvas"]),
                "Motivo": motivo,
            }
            for _, r in celulas.iterrows()
        ],
        email_responsavel,
        nome_responsavel,
    )
    return len(pares)


# --- Histórico ---


def registrar_historico(linhas: list[dict], email_responsavel: str, nome_responsavel: str) -> None:
    if not linhas:
        return
    colunas = ABAS_AVALIACAO[ABA_LOG]
    agora = _agora()
    garantir_aba_avaliacao(ABA_LOG)
    valores = []
    for linha in linhas:
        completa = {
            **linha,
            "Data": agora,
            "Email_Responsavel": email_responsavel,
            "Nome_Responsavel": nome_responsavel,
        }
        valores.append([str(completa.get(c, "") or "") for c in colunas])
    planilha.worksheet(ABA_LOG).append_rows(valores)
    limpar_cache_planilhas()


def carregar_historico(id_disciplina: str) -> pd.DataFrame:
    df = _ler(ABA_LOG)
    if df.empty:
        return df
    df = df[df["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disciplina)]
    return df.iloc[::-1].reset_index(drop=True)
