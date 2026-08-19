"""Leitura e gravação dos cadastros acadêmicos (Disciplinas, Ciclos, Config_Professores)."""

from __future__ import annotations

import re
import time

import pandas as pd

from config import ABAS_AVALIACAO, ABAS_FREQUENCIA
from data.sheets import ler_aba, ler_aba_frequencia, salvar_aba, salvar_aba_frequencia
from utils.datas import parse_data_planilha, parse_data_planilha_series
from utils.disciplina import mapa_codigo_disciplina_legado, normalizar_id

COLUNAS_DISCIPLINAS = ["ID_Disciplina", "Nome_Disciplina", "Status", "Encontro_Presencial"]
ENCONTRO_OPCOES = ["Não", "Sim"]
COLUNAS_CICLOS = [
    "ID_Ciclo",
    "Nome_Ciclo",
    "ID_Disciplina",
    "Data início",
    "Data fim",
    "Status",
    "Ordem",
]
COLUNAS_PROFESSORES = [
    "Disciplina",
    "Ciclo",
    "ID_Disciplina",
    "ID_Ciclo",
    "Professor",
    "Tipo",
    "Sala",
]
ALIAS_PROFESSORES = {
    "Professor": ("Nome", "Nome_Professor", "Professor(a)"),
    "Tipo": ("Tipo_Professor", "Tipo Professor", "Função", "Funcao", "Papel"),
    "Sala": ("Sala_Turma", "Sala Turma", "Turma", "Sala_Aluno"),
    "ID_Ciclo": ("Id_Ciclo", "Ciclo_ID"),
    "ID_Disciplina": ("Id_Disciplina", "Disciplina_ID"),
}

STATUS_OPCOES = ["ativo", "inativo"]
TIPOS_PROFESSOR_CONFIG = ["Orientador", "Especialista"]


def _garantir_colunas(df: pd.DataFrame, obrigatorias: list[str]) -> pd.DataFrame:
    out = pd.DataFrame() if df is None or df.empty else df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for col in obrigatorias:
        if col not in out.columns:
            out[col] = ""
    extras = [c for c in out.columns if c not in obrigatorias]
    return out[obrigatorias + extras]


def _colunas_gravacao(df: pd.DataFrame, obrigatorias: list[str]) -> list[str]:
    extras = [c for c in df.columns if c not in obrigatorias]
    return obrigatorias + extras


def _status_norm(valor) -> str:
    texto = str(valor or "").strip().lower()
    if texto in {"ativo", "ativa", "sim", "s", "1", "true"}:
        return "ativo"
    return "inativo"


def _encontro_norm(valor) -> str:
    texto = str(valor or "").strip().lower()
    if texto in {"sim", "s", "1", "true", "presencial"}:
        return "Sim"
    return "Não"


def carregar_disciplinas() -> pd.DataFrame:
    try:
        df = ler_aba("Disciplinas")
    except Exception:
        df = pd.DataFrame()
    df = _garantir_colunas(df, COLUNAS_DISCIPLINAS)
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["Nome_Disciplina"] = df["Nome_Disciplina"].astype(str).str.strip()
    df["Status"] = df["Status"].map(_status_norm)
    df["Encontro_Presencial"] = df["Encontro_Presencial"].map(_encontro_norm)
    return df


def salvar_disciplinas(df: pd.DataFrame) -> str | None:
    df = _garantir_colunas(df, COLUNAS_DISCIPLINAS)
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["Nome_Disciplina"] = df["Nome_Disciplina"].astype(str).str.strip()
    df["Status"] = df["Status"].map(_status_norm)
    df["Encontro_Presencial"] = df["Encontro_Presencial"].map(_encontro_norm)
    df = df[df["ID_Disciplina"].ne("") | df["Nome_Disciplina"].ne("")]
    if df.empty:
        return "Informe ao menos uma disciplina com código e nome."
    sem_id = df["ID_Disciplina"].eq("")
    sem_nome = df["Nome_Disciplina"].eq("")
    if sem_id.any() or sem_nome.any():
        return "Toda disciplina precisa de código (ID_Disciplina) e nome."
    if df["ID_Disciplina"].duplicated().any():
        return "Há códigos de disciplina repetidos."
    ativos = df[df["Status"] == "ativo"]
    if len(ativos) == 0:
        return "Marque uma disciplina como ativa."
    if len(ativos) > 1:
        return "Deixe apenas uma disciplina com status ativo."
    salvar_aba("Disciplinas", df, _colunas_gravacao(df, COLUNAS_DISCIPLINAS))
    return None


_ABAS_CODIGO_AVALIACAO = [
    "Disciplinas",
    "Ciclos",
    "Config_Professores",
    "Entrancia_Turma",
    "Avaliacoes",
    "Respostas_Curso",
] + list(ABAS_AVALIACAO.keys())

_ABAS_CODIGO_FREQUENCIA = list(dict.fromkeys(
    list(ABAS_FREQUENCIA.keys())
    + [
        "Calendario_Aulas",
        "Calendario_Dailies",
        "Calendario_Unificado",
        "BD_Presenca",
        "Ajustes_Presenca",
    ]
))

_COLUNAS_CODIGO = {
    "ID_Disciplina",
    "Id_Disciplina",
    "ID_Ciclo",
    "Id_Ciclo",
    "ID do Ciclo",
    "ID_Componente",
}

_COLUNAS_CODIGO_FREQ_EXATO = {"Disciplina"}


def pares_codigo_alterado(antes: pd.DataFrame, depois: pd.DataFrame) -> list[tuple[str, str]]:
    """Detecta troca de código na mesma linha do cadastro (ex.: 20263TRI → TRIB)."""
    pares = []
    n = min(len(antes), len(depois))
    for i in range(n):
        antigo = normalizar_id(antes.iloc[i].get("ID_Disciplina", ""))
        novo = normalizar_id(depois.iloc[i].get("ID_Disciplina", ""))
        if antigo and novo and antigo != novo:
            pares.append((antigo, novo))
    return pares


def _valor_codigo_renomeado(valor, antigo: str, novo: str) -> str:
    atual = normalizar_id(valor)
    if not atual:
        return "" if valor is None or (isinstance(valor, float) and pd.isna(valor)) else str(valor).strip()
    if atual == antigo:
        return novo
    if atual.startswith(antigo + "-") or atual.startswith(antigo + "_"):
        return novo + atual[len(antigo) :]
    antigo_comp = re.sub(r"[^A-Za-z0-9]", "", antigo)[:8].upper()
    novo_comp = re.sub(r"[^A-Za-z0-9]", "", novo)[:8].upper()
    prefixo = f"COMP-{antigo_comp}-"
    if antigo_comp and atual.upper().startswith(prefixo):
        return f"COMP-{novo_comp}-" + atual[len(prefixo) :]
    return atual


def _renomear_colunas_df(
    df: pd.DataFrame,
    antigo: str,
    novo: str,
    *,
    colunas_exatas: set[str] | None = None,
) -> tuple[pd.DataFrame, int]:
    if df is None or df.empty:
        return df, 0
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    trocas = 0
    extras = colunas_exatas or set()
    for col in out.columns:
        nome_col = col.strip()
        so_exato = nome_col in extras
        if nome_col not in _COLUNAS_CODIGO and not so_exato:
            continue
        novos = []
        mudou_col = 0
        for v in out[col]:
            orig = normalizar_id(v)
            if so_exato:
                n = novo if orig == antigo else orig
            else:
                n = _valor_codigo_renomeado(v, antigo, novo)
            if orig and n != orig:
                novos.append(n)
                mudou_col += 1
            else:
                novos.append(v)
        if mudou_col:
            out[col] = novos
            trocas += mudou_col
    return out, trocas


def propagar_codigo_disciplina(antigo: str, novo: str, *, incluir_disciplinas: bool = False) -> list[str]:
    """Atualiza o código da disciplina (e prefixos de ciclo/componente) nas abas relacionadas."""
    antigo = normalizar_id(antigo)
    novo = normalizar_id(novo)
    if not antigo or not novo or antigo == novo:
        return []
    avisos: list[str] = []
    vistas = set()
    for nome in _ABAS_CODIGO_AVALIACAO:
        if nome in vistas:
            continue
        vistas.add(nome)
        if nome == "Disciplinas" and not incluir_disciplinas:
            continue
        try:
            df = ler_aba(nome)
        except Exception:
            continue
        atualizado, n = _renomear_colunas_df(df, antigo, novo)
        if n == 0:
            continue
        try:
            salvar_aba(nome, atualizado, list(atualizado.columns))
            avisos.append(f"{nome}: {n} célula(s)")
            time.sleep(0.4)
        except Exception as exc:
            avisos.append(f"{nome}: não foi possível gravar ({exc})")

    avisos.extend(propagar_codigo_frequencia(antigo, novo))
    return avisos


def _amostras_codigo_frequencia() -> list[tuple[str, str]]:
    amostras: list[tuple[str, str]] = []
    for nome in _ABAS_CODIGO_FREQUENCIA:
        try:
            df = ler_aba_frequencia(nome)
        except Exception:
            continue
        if df is None or df.empty or "ID_Disciplina" not in df.columns:
            continue
        nomes = df["Disciplina"] if "Disciplina" in df.columns else [""] * len(df)
        for codigo, nome_disc in zip(df["ID_Disciplina"], nomes):
            amostras.append((str(codigo), str(nome_disc)))
    return amostras


def inferir_pares_codigo_frequencia() -> list[tuple[str, str]]:
    """Detecta 20263TRI na planilha de presença vs TRIB no cadastro."""
    discs = carregar_disciplinas()
    if discs.empty:
        return []
    atuais = {
        normalizar_id(row["ID_Disciplina"]): str(row.get("Nome_Disciplina", "")).strip()
        for _, row in discs.iterrows()
        if normalizar_id(row["ID_Disciplina"])
    }
    mapa = mapa_codigo_disciplina_legado(atuais, _amostras_codigo_frequencia())
    return [(antigo, novo) for antigo, novo in mapa.items() if antigo != novo]


def alinhar_codigos_frequencia() -> list[str]:
    """Reescreve IDs antigos na planilha de presenças para o código atual da disciplina."""
    avisos: list[str] = []
    for antigo, novo in inferir_pares_codigo_frequencia():
        partes = propagar_codigo_frequencia(antigo, novo)
        if partes:
            avisos.extend([f"{antigo} → {novo}: {msg}" for msg in partes])
        else:
            avisos.append(f"{antigo} → {novo}: nada a alterar")
    return avisos


def propagar_codigo_frequencia(antigo: str, novo: str) -> list[str]:
    antigo = normalizar_id(antigo)
    novo = normalizar_id(novo)
    if not antigo or not novo or antigo == novo:
        return []
    avisos: list[str] = []
    for nome in _ABAS_CODIGO_FREQUENCIA:
        try:
            df = ler_aba_frequencia(nome)
        except Exception:
            continue
        atualizado, n = _renomear_colunas_df(
            df, antigo, novo, colunas_exatas=_COLUNAS_CODIGO_FREQ_EXATO
        )
        if n == 0:
            continue
        try:
            salvar_aba_frequencia(nome, atualizado, list(atualizado.columns))
            avisos.append(f"{nome}: {n} célula(s)")
            time.sleep(0.4)
        except Exception as exc:
            avisos.append(f"{nome}: não foi possível gravar ({exc})")
    return avisos


def _fmt_data_planilha(valor) -> str:
    parsed = parse_data_planilha(valor)
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).strftime("%d/%m/%Y")


def _datas_para_editor(serie: pd.Series) -> list:
    """Converte serial do Sheets ou dd/mm/aaaa em date; vazio vira None (não 01/01/1970)."""
    parsed = parse_data_planilha_series(serie)
    saida = []
    for valor in parsed:
        if pd.isna(valor):
            saida.append(None)
        else:
            saida.append(pd.Timestamp(valor).date())
    return saida


def carregar_ciclos() -> pd.DataFrame:
    try:
        df = ler_aba("Ciclos")
    except Exception:
        df = pd.DataFrame()
    df = _garantir_colunas(df, COLUNAS_CICLOS)
    df["ID_Ciclo"] = df["ID_Ciclo"].map(normalizar_id)
    df["Nome_Ciclo"] = df["Nome_Ciclo"].astype(str).str.strip()
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["Status"] = df["Status"].map(_status_norm)
    df["Ordem"] = pd.to_numeric(df["Ordem"], errors="coerce")
    for col in ("Data início", "Data fim"):
        df[col] = _datas_para_editor(df[col])
    if "ID_Disciplina" in df.columns:
        df = df.sort_values(["ID_Disciplina", "Ordem"], na_position="last")
    return df


def salvar_ciclos(df: pd.DataFrame) -> str | None:
    df = _garantir_colunas(df, COLUNAS_CICLOS)
    df["ID_Ciclo"] = df["ID_Ciclo"].map(normalizar_id)
    df["Nome_Ciclo"] = df["Nome_Ciclo"].astype(str).str.strip()
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["Status"] = df["Status"].map(_status_norm)
    df["Data início"] = df["Data início"].map(_fmt_data_planilha)
    df["Data fim"] = df["Data fim"].map(_fmt_data_planilha)
    df["Ordem"] = pd.to_numeric(df["Ordem"], errors="coerce")
    df = df[df["ID_Ciclo"].ne("") | df["Nome_Ciclo"].ne("")]
    if df.empty:
        return "Informe ao menos um ciclo."
    if df["ID_Ciclo"].eq("").any() or df["Nome_Ciclo"].eq("").any():
        return "Todo ciclo precisa de ID_Ciclo e Nome_Ciclo."
    if df["ID_Disciplina"].eq("").any():
        return "Todo ciclo precisa estar vinculado a uma disciplina."
    if df["ID_Ciclo"].duplicated().any():
        return "Há IDs de ciclo repetidos."
    ordem_num = pd.to_numeric(df["Ordem"], errors="coerce")
    com_ordem = df[ordem_num.notna() & (ordem_num > 0)].copy()
    com_ordem["_ordem"] = ordem_num[com_ordem.index]
    duplicada = com_ordem.duplicated(subset=["ID_Disciplina", "_ordem"], keep=False)
    if duplicada.any():
        return (
            "A ordem se repete na mesma disciplina. "
            "Use 1, 2, 3… em cada disciplina (o Ciclo 1 de outra disciplina também pode ser 1)."
        )
    df["Ordem"] = df["Ordem"].fillna(0).astype(int).astype(str)
    salvar_aba("Ciclos", df, _colunas_gravacao(df, COLUNAS_CICLOS))
    return None


def _preencher_alias(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for destino, aliases in ALIAS_PROFESSORES.items():
        atual = out[destino].astype(str).str.strip() if destino in out.columns else pd.Series("", index=out.index)
        vazio = atual.isin(["", "nan", "None", "none"])
        if destino not in out.columns:
            out[destino] = ""
            vazio = pd.Series(True, index=out.index)
        if not vazio.any():
            continue
        for alias in aliases:
            if alias not in out.columns:
                continue
            candidato = out[alias].astype(str).str.strip()
            out.loc[vazio, destino] = candidato[vazio]
            atual = out[destino].astype(str).str.strip()
            vazio = atual.isin(["", "nan", "None", "none"])
            if not vazio.any():
                break
    return out


def _preencher_tipo_base_alunos(df: pd.DataFrame) -> pd.DataFrame:
    """Se Tipo estiver vazio, tenta o Tipo_Professor da Base_Alunos pelo nome."""
    if df.empty or "Professor" not in df.columns:
        return df
    try:
        base = ler_aba("Base_Alunos")
    except Exception:
        return df
    col_tipo = None
    for candidata in ("Tipo_Professor", "Tipo Professor", "Tipo"):
        if candidata in base.columns:
            col_tipo = candidata
            break
    if col_tipo is None or "Nome_Completo" not in base.columns:
        return df
    mapa = {}
    for _, row in base.iterrows():
        nome = str(row.get("Nome_Completo", "")).strip().lower()
        tipo = str(row.get(col_tipo, "")).strip().title()
        if nome and tipo and tipo.lower() not in {"", "nan", "none"}:
            mapa[nome] = tipo
    out = df.copy()
    def _tipo(row):
        atual = str(row.get("Tipo", "")).strip()
        if atual and atual.lower() not in {"nan", "none"}:
            return atual
        return mapa.get(str(row.get("Professor", "")).strip().lower(), "")
    out["Tipo"] = out.apply(_tipo, axis=1)
    return out


def _completar_ids_e_nomes_professor(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    try:
        ciclos = ler_aba("Ciclos")
    except Exception:
        ciclos = pd.DataFrame()
    try:
        discs = ler_aba("Disciplinas")
    except Exception:
        discs = pd.DataFrame()

    mapa_ciclo_disc = {}
    mapa_ciclo_nome = {}
    if not ciclos.empty:
        for _, row in ciclos.iterrows():
            cid = normalizar_id(row.get("ID_Ciclo", ""))
            if cid:
                mapa_ciclo_disc[cid] = normalizar_id(row.get("ID_Disciplina", ""))
                mapa_ciclo_nome[cid] = str(row.get("Nome_Ciclo", "")).strip()

    mapa_disc_nome = {}
    if not discs.empty:
        for _, row in discs.iterrows():
            did = normalizar_id(row.get("ID_Disciplina", ""))
            if did:
                mapa_disc_nome[did] = str(row.get("Nome_Disciplina", "")).strip()

    out["ID_Ciclo"] = out["ID_Ciclo"].map(normalizar_id)
    out["ID_Disciplina"] = out["ID_Disciplina"].map(normalizar_id)
    sem_disc = out["ID_Disciplina"].eq("")
    out.loc[sem_disc, "ID_Disciplina"] = out.loc[sem_disc, "ID_Ciclo"].map(mapa_ciclo_disc).fillna("")
    if "Disciplina" not in out.columns:
        out["Disciplina"] = ""
    if "Ciclo" not in out.columns:
        out["Ciclo"] = ""
    sem_nome_disc = out["Disciplina"].astype(str).str.strip().isin(["", "nan", "None"])
    out.loc[sem_nome_disc, "Disciplina"] = out.loc[sem_nome_disc, "ID_Disciplina"].map(mapa_disc_nome).fillna("")
    sem_nome_ciclo = out["Ciclo"].astype(str).str.strip().isin(["", "nan", "None"])
    out.loc[sem_nome_ciclo, "Ciclo"] = out.loc[sem_nome_ciclo, "ID_Ciclo"].map(mapa_ciclo_nome).fillna("")
    return out


def carregar_professores() -> pd.DataFrame:
    try:
        df = ler_aba("Config_Professores")
    except Exception:
        df = pd.DataFrame()
    df = _garantir_colunas(df, COLUNAS_PROFESSORES)
    df = _preencher_alias(df)
    df["ID_Ciclo"] = df["ID_Ciclo"].map(normalizar_id)
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["Professor"] = df["Professor"].astype(str).str.strip()
    df["Tipo"] = df["Tipo"].astype(str).str.strip().str.title()
    df.loc[df["Tipo"].str.lower().isin(["nan", "none", ""]), "Tipo"] = ""
    df["Sala"] = df["Sala"].map(
        lambda x: "" if str(x).strip().lower() in {"nan", "none", ""} else str(x).strip()
    )
    df = _completar_ids_e_nomes_professor(df)
    df = _preencher_tipo_base_alunos(df)
    df["Tipo"] = df["Tipo"].astype(str).str.strip().str.title()
    df.loc[df["Tipo"].str.lower().isin(["nan", "none"]), "Tipo"] = ""
    return df


def salvar_professores(df: pd.DataFrame) -> str | None:
    df = _garantir_colunas(df, COLUNAS_PROFESSORES)
    df = _completar_ids_e_nomes_professor(df)
    df["ID_Ciclo"] = df["ID_Ciclo"].map(normalizar_id)
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["Professor"] = df["Professor"].astype(str).str.strip()
    df["Tipo"] = df["Tipo"].astype(str).str.strip().str.title()
    df.loc[df["Tipo"].str.lower().isin(["nan", "none"]), "Tipo"] = ""
    df["Sala"] = df["Sala"].astype(str).str.strip()
    df.loc[df["Sala"].str.lower().isin(["nan", "none"]), "Sala"] = ""
    df = df[df["Professor"].ne("") | df["ID_Ciclo"].ne("")]
    if df.empty:
        return "Informe ao menos um professor."
    if df["ID_Ciclo"].eq("").any():
        return "Cada linha precisa do ID do ciclo."
    if df["Professor"].eq("").any():
        return "Cada linha precisa do nome do professor."
    orientadores = df[df["Tipo"] == "Orientador"]
    if not orientadores.empty and orientadores["Sala"].eq("").any():
        return "Orientador precisa da sala (é filtrado pela sala do aluno na avaliação do curso)."
    salvar_aba("Config_Professores", df, _colunas_gravacao(df, COLUNAS_PROFESSORES))
    return None
