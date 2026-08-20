"""Calendário de aulas e dailies (planilha de frequência), lançado pelo app."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from data.sheets import garantir_colunas_frequencia, ler_aba, ler_aba_frequencia, salvar_aba_frequencia
from utils.datas import parse_data_planilha, parse_data_planilha_series
from utils.disciplina import normalizar_id

COLUNAS_CALENDARIO = ["Data", "ID_Disciplina", "Disciplina", "Categoria", "Detalhe"]

CATEGORIA_ESPECIALISTA = "Aula de especialista"
CATEGORIA_APRESENTACAO = "Apresentação de projeto"
CATEGORIAS_AULA = [CATEGORIA_ESPECIALISTA, CATEGORIA_APRESENTACAO]

ABAS_TIPO = {
    "aulas": "Calendario_Aulas",
    "dailies": "Calendario_Dailies",
}

DIAS_SEMANA = [
    (0, "Segunda"),
    (1, "Terça"),
    (2, "Quarta"),
    (3, "Quinta"),
    (4, "Sexta"),
    (5, "Sábado"),
    (6, "Domingo"),
]


def _fmt_data(valor) -> str:
    parsed = parse_data_planilha(valor)
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).strftime("%d/%m/%Y")


def _datas_para_editor(serie: pd.Series) -> list:
    parsed = parse_data_planilha_series(serie)
    saida = []
    for valor in parsed:
        if pd.isna(valor):
            saida.append(None)
        else:
            saida.append(pd.Timestamp(valor).date())
    return saida


def inferir_categoria_aula(dia: date, valor: str = "") -> str:
    atual = str(valor or "").strip()
    if atual in CATEGORIAS_AULA:
        return atual
    atual_l = atual.lower()
    if "apresent" in atual_l or "projeto" in atual_l:
        return CATEGORIA_APRESENTACAO
    if "especial" in atual_l:
        return CATEGORIA_ESPECIALISTA
    if dia.weekday() == 0:
        return CATEGORIA_APRESENTACAO
    return CATEGORIA_ESPECIALISTA


def nome_disciplina(id_disciplina: str) -> str:
    id_limpo = normalizar_id(id_disciplina)
    try:
        discs = ler_aba("Disciplinas")
    except Exception:
        discs = pd.DataFrame()
    if discs is None or discs.empty:
        return ""
    filtro = discs[discs["ID_Disciplina"].map(normalizar_id) == id_limpo]
    if filtro.empty:
        return ""
    return str(filtro.iloc[0].get("Nome_Disciplina", "")).strip()


def carregar_calendario(tipo: str) -> pd.DataFrame:
    aba = ABAS_TIPO[tipo]
    try:
        garantir_colunas_frequencia(
            aba,
            COLUNAS_CALENDARIO if tipo == "aulas" else ["Data", "ID_Disciplina", "Disciplina"],
        )
    except Exception:
        pass
    try:
        df = ler_aba_frequencia(aba)
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUNAS_CALENDARIO)
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for col in COLUNAS_CALENDARIO:
        if col not in out.columns:
            out[col] = ""
    out["ID_Disciplina"] = out["ID_Disciplina"].map(normalizar_id)
    try:
        from domain.cadastros import carregar_disciplinas

        discs = carregar_disciplinas()
        atuais = {}
        if discs is not None and not discs.empty:
            atuais = {
                normalizar_id(row["ID_Disciplina"]): str(row.get("Nome_Disciplina", "")).strip()
                for _, row in discs.iterrows()
                if normalizar_id(row["ID_Disciplina"])
            }
        if atuais:
            from utils.disciplina import remapear_coluna_id_disciplina

            out = remapear_coluna_id_disciplina(out, atuais, coluna_nome="Disciplina")
            out["ID_Disciplina"] = out["ID_Disciplina"].map(normalizar_id)
    except Exception:
        pass
    out["Disciplina"] = out["Disciplina"].astype(str).str.strip().replace("nan", "")
    out["Detalhe"] = (
        out["Detalhe"].astype(str).str.strip().replace({"nan": "", "None": "", "none": ""})
    )
    out["Data"] = out["Data"].map(_fmt_data)
    if "Categoria" not in out.columns:
        out["Categoria"] = ""
    out = out[out["Data"].ne("") | out["ID_Disciplina"].ne("")]
    extras = [c for c in out.columns if c not in COLUNAS_CALENDARIO]
    return out[COLUNAS_CALENDARIO + extras]


def datas_da_disciplina(tipo: str, id_disciplina: str) -> pd.DataFrame:
    df = carregar_calendario(tipo)
    id_limpo = normalizar_id(id_disciplina)
    filtro = df[df["ID_Disciplina"].map(normalizar_id) == id_limpo].copy()
    filtro["Data"] = _datas_para_editor(filtro["Data"])
    if tipo == "aulas":
        cats = []
        for dia, cat in zip(filtro["Data"], filtro.get("Categoria", [""] * len(filtro))):
            if dia is None:
                cats.append(CATEGORIA_ESPECIALISTA)
            else:
                cats.append(inferir_categoria_aula(dia, str(cat)))
        filtro["Categoria"] = cats
        if "Detalhe" not in filtro.columns:
            filtro["Detalhe"] = ""
        filtro["Detalhe"] = filtro["Detalhe"].astype(str).replace("nan", "").str.strip()
        filtro = filtro[["Data", "Categoria", "Detalhe"]]
    else:
        filtro = filtro[["Data"]]
    filtro = filtro.sort_values("Data", na_position="last")
    return filtro.reset_index(drop=True)


def gerar_datas(
    inicio: date,
    fim: date,
    dias_semana: list[int],
    *,
    excluir: set[date] | None = None,
) -> list[date]:
    if inicio is None or fim is None or not dias_semana:
        return []
    if fim < inicio:
        inicio, fim = fim, inicio
    escolhidos = {int(d) for d in dias_semana}
    pular = excluir or set()
    atual = inicio
    saida: list[date] = []
    while atual <= fim:
        if atual.weekday() in escolhidos and atual not in pular:
            saida.append(atual)
        atual += timedelta(days=1)
    return saida


def _linhas_editor(df_edit: pd.DataFrame, id_disciplina: str, nome: str, *, aulas: bool) -> pd.DataFrame:
    if df_edit is None or df_edit.empty:
        return pd.DataFrame(columns=COLUNAS_CALENDARIO)
    out = df_edit.copy()
    if "Data" not in out.columns:
        return pd.DataFrame(columns=COLUNAS_CALENDARIO)
    linhas = []
    vistos: set[tuple[str, str]] = set()
    for _, row in out.iterrows():
        texto = _fmt_data(row.get("Data"))
        if not texto:
            continue
        parsed = parse_data_planilha(texto)
        dia = pd.Timestamp(parsed).date() if not pd.isna(parsed) else date.today()
        categoria = inferir_categoria_aula(dia, row.get("Categoria", "")) if aulas else ""
        chave = texto
        if chave in vistos:
            continue
        vistos.add(chave)
        linhas.append(
            {
                "Data": texto,
                "ID_Disciplina": normalizar_id(id_disciplina),
                "Disciplina": nome,
                "Categoria": categoria,
                "Detalhe": str(row.get("Detalhe", "") or "").strip() if aulas else "",
            }
        )
    return pd.DataFrame(linhas, columns=COLUNAS_CALENDARIO)


def salvar_calendario_disciplina(
    tipo: str,
    id_disciplina: str,
    df_edit: pd.DataFrame,
) -> str | None:
    if tipo not in ABAS_TIPO:
        return "Tipo de calendário inválido."
    id_limpo = normalizar_id(id_disciplina)
    if not id_limpo:
        return "Selecione a disciplina."
    nome = nome_disciplina(id_limpo)
    novas = _linhas_editor(df_edit, id_limpo, nome, aulas=tipo == "aulas")
    if novas.empty:
        return "Informe ao menos uma data válida."

    base = carregar_calendario(tipo)
    resto = base[base["ID_Disciplina"] != id_limpo]
    out = pd.concat([resto, novas], ignore_index=True)
    parsed = parse_data_planilha_series(out["Data"])
    out = out.assign(_ord=parsed).sort_values(["ID_Disciplina", "_ord"], na_position="last")
    out = out.drop(columns=["_ord"])
    extras = [c for c in out.columns if c not in COLUNAS_CALENDARIO]
    salvar_aba_frequencia(ABAS_TIPO[tipo], out, COLUNAS_CALENDARIO + extras)
    return None


def atualizar_aula(
    id_disciplina: str,
    dia: date,
    *,
    categoria: str | None = None,
    detalhe: str | None = None,
) -> str | None:
    """Atualiza categoria e/ou detalhe (ciclo, tema) de uma aula já lançada."""
    if categoria is not None and categoria not in CATEGORIAS_AULA:
        return "Categoria inválida."
    id_limpo = normalizar_id(id_disciplina)
    if not id_limpo or dia is None:
        return "Selecione a disciplina e a data."
    df = carregar_calendario("aulas")
    if df.empty:
        return "Não há aula nesta data."
    datas = parse_data_planilha_series(df["Data"]).map(
        lambda x: pd.Timestamp(x).date() if pd.notna(x) else None
    )
    mask = (df["ID_Disciplina"].map(normalizar_id) == id_limpo) & (datas == dia)
    if not mask.any():
        return "Não há aula nesta data para alterar."
    if "Detalhe" not in df.columns:
        df["Detalhe"] = ""
    if categoria is not None:
        df.loc[mask, "Categoria"] = categoria
    if detalhe is not None:
        df.loc[mask, "Detalhe"] = str(detalhe).strip()
    nome = nome_disciplina(id_limpo)
    sem_nome = mask & df["Disciplina"].astype(str).str.strip().isin(["", "nan"])
    df.loc[sem_nome, "Disciplina"] = nome
    extras = [c for c in df.columns if c not in COLUNAS_CALENDARIO]
    salvar_aba_frequencia(ABAS_TIPO["aulas"], df, COLUNAS_CALENDARIO + extras)
    return None


def alterar_categoria_aula(id_disciplina: str, dia: date, categoria: str) -> str | None:
    return atualizar_aula(id_disciplina, dia, categoria=categoria)


def detalhes_por_dia(id_disciplina: str) -> dict[date, str]:
    df = carregar_calendario("aulas")
    id_limpo = normalizar_id(id_disciplina)
    saida: dict[date, str] = {}
    if df.empty:
        return saida
    if "Detalhe" not in df.columns:
        return saida
    bloco = df[df["ID_Disciplina"].map(normalizar_id) == id_limpo]
    for _, row in bloco.iterrows():
        parsed = parse_data_planilha(row.get("Data"))
        if pd.isna(parsed):
            continue
        texto = str(row.get("Detalhe", "") or "").strip()
        if texto.lower() in {"", "nan", "none"}:
            continue
        saida[pd.Timestamp(parsed).date()] = texto
    return saida


def eventos_por_dia(id_disciplina: str) -> dict[date, list[str]]:
    """Agrupa aulas (por categoria), daily, encontro, feriado e recesso."""
    agrupado: dict[date, list[str]] = {}

    def _add(dia: date, tipo: str):
        lista = agrupado.setdefault(dia, [])
        if tipo not in lista:
            lista.append(tipo)

    df_aulas = carregar_calendario("aulas")
    id_limpo = normalizar_id(id_disciplina)
    bloco = df_aulas[df_aulas["ID_Disciplina"].map(normalizar_id) == id_limpo]
    for _, row in bloco.iterrows():
        parsed = parse_data_planilha(row.get("Data"))
        if pd.isna(parsed):
            continue
        dia = pd.Timestamp(parsed).date()
        _add(dia, inferir_categoria_aula(dia, row.get("Categoria", "")))

    df_dailies = carregar_calendario("dailies")
    bloco_d = df_dailies[df_dailies["ID_Disciplina"].map(normalizar_id) == id_limpo]
    for valor in bloco_d["Data"]:
        parsed = parse_data_planilha(valor)
        if pd.isna(parsed):
            continue
        _add(pd.Timestamp(parsed).date(), "Daily")

    try:
        from domain.encontro_presencial import datas_encontro_ativas

        enc = datas_encontro_ativas(id_disciplina)
    except Exception:
        enc = pd.DataFrame()
    if enc is not None and not enc.empty:
        for valor in enc["_parsed"]:
            if pd.isna(valor):
                continue
            _add(pd.Timestamp(valor).date(), "Encontro presencial")

    try:
        from domain.feriados import datas_bloqueio

        anos = {d.year for d in agrupado} or {date.today().year}
        hoje = date.today()
        anos.update({hoje.year - 1, hoje.year, hoje.year + 1})
        for dia, itens in datas_bloqueio(sorted(anos)).items():
            for tipo, nome in itens:
                rotulo = f"{tipo}: {nome}" if nome else tipo
                _add(dia, rotulo)
    except Exception:
        pass
    return dict(sorted(agrupado.items()))


def agenda_disciplina(id_disciplina: str) -> pd.DataFrame:
    """Aulas, dailies e encontro da disciplina, ordenados por data."""
    linhas = []
    notas = detalhes_por_dia(id_disciplina)
    for dia, tipos in eventos_por_dia(id_disciplina).items():
        ts = pd.Timestamp(dia)
        for rotulo in tipos:
            detalhe = notas.get(dia, "") if rotulo in CATEGORIAS_AULA else ""
            linhas.append(
                {
                    "Data": ts.strftime("%d/%m/%Y"),
                    "_ord": ts.normalize(),
                    "Dia": DIAS_SEMANA[int(ts.weekday())][1],
                    "Tipo": rotulo,
                    "Detalhe": detalhe,
                    "Disciplina": nome_disciplina(id_disciplina),
                }
            )
    if not linhas:
        return pd.DataFrame(columns=["Data", "Dia", "Tipo", "Detalhe", "Disciplina"])
    out = pd.DataFrame(linhas).sort_values(["_ord", "Tipo"]).drop(columns=["_ord"])
    return out.reset_index(drop=True)
