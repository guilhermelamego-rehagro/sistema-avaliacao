"""Encontro presencial da disciplina: flag, datas, presença e ciclo da entrega final."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from data.sheets import (
    ler_aba,
    ler_aba_frequencia,
    salvar_aba,
    salvar_aba_frequencia,
)
from domain.ciclos import filtrar_ciclos_ativos, ordenar_ciclos
from utils.datas import parse_data_planilha, parse_data_planilha_series
from utils.disciplina import normalizar_id

COLUNAS_DATAS = ["ID_Disciplina", "Data", "Descricao", "Ativo"]
COLUNAS_PRESENCA = [
    "ID_Disciplina",
    "Data",
    "Email_Aluno",
    "Nome_Aluno",
    "Sala",
    "Grupo",
    "Status",
    "Email_Lancador",
    "Nome_Lancador",
    "Data_Lancamento",
]
STATUS_PRESENCA = ["Presente", "Falta"]
_COLUNAS_AJUSTE_MIN = ["Email_Aluno", "Data", "Disciplina", "Novo_Status"]


def _sim(valor) -> bool:
    return str(valor or "").strip().lower() in {"sim", "s", "1", "true", "presencial"}


def _ativo(valor) -> bool:
    return str(valor or "Sim").strip().lower() in {"sim", "s", "1", "true", "ativo"}


def _fmt_data(valor) -> str:
    parsed = parse_data_planilha(valor)
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).strftime("%d/%m/%Y")


def _datas_para_editor(serie: pd.Series) -> pd.Series:
    parsed = parse_data_planilha_series(serie)
    saida = []
    for valor in parsed:
        if pd.isna(valor):
            saida.append(None)
        else:
            saida.append(pd.Timestamp(valor).date())
    return pd.Series(saida, dtype="object")


def normalizar_df_datas_editor(df: pd.DataFrame | None) -> pd.DataFrame:
    """Garante tipos compatíveis com st.data_editor (Data como date, não float do Sheets)."""
    cols = ["Data", "Descricao", "Ativo"]
    if df is None or df.empty:
        return pd.DataFrame(
            {
                "Data": pd.Series(dtype="object"),
                "Descricao": pd.Series(dtype=str),
                "Ativo": pd.Series(dtype=str),
            }
        )
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            out[col] = None if col == "Data" else ""
    out["Data"] = _datas_para_editor(out["Data"])
    out["Descricao"] = out["Descricao"].astype(str).str.strip().replace("nan", "")
    out["Ativo"] = out["Ativo"].map(lambda v: "Sim" if _ativo(v) else "Não")
    return out[cols]


def _garantir_colunas(df: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    out = pd.DataFrame() if df is None or df.empty else df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for col in colunas:
        if col not in out.columns:
            out[col] = ""
    extras = [c for c in out.columns if c not in colunas]
    return out[colunas + extras]


def disciplina_tem_encontro_presencial(id_disciplina: str) -> bool:
    id_limpo = normalizar_id(id_disciplina)
    if not id_limpo:
        return False
    try:
        df = ler_aba("Disciplinas")
    except Exception:
        return False
    if df.empty or "ID_Disciplina" not in df.columns:
        return False
    filtro = df[df["ID_Disciplina"].map(normalizar_id) == id_limpo]
    if filtro.empty:
        return False
    col = "Encontro_Presencial" if "Encontro_Presencial" in filtro.columns else ""
    if not col:
        return False
    return _sim(filtro.iloc[0][col])


def nome_parece_entrega_final(nome: str) -> bool:
    texto = str(nome or "").strip().lower()
    if not texto:
        return False
    return "entrega" in texto and "final" in texto


def _ids_ciclo_so_entrega_final(id_disciplina: str) -> set[str]:
    id_limpo = normalizar_id(id_disciplina)
    try:
        df = ler_aba("Config_Componentes")
    except Exception:
        return set()
    if df.empty or "ID_Disciplina" not in df.columns:
        return set()
    comps = df[df["ID_Disciplina"].map(normalizar_id) == id_limpo]
    if comps.empty or "Tipo" not in comps.columns:
        return set()
    tipo = comps["Tipo"].astype(str).str.strip()
    ids_ef = {
        normalizar_id(v)
        for v in comps.loc[tipo.eq("Entrega_Final"), "ID_Ciclo"].tolist()
        if normalizar_id(v)
    }
    ids_ciclo = {
        normalizar_id(v)
        for v in comps.loc[tipo.eq("Ciclo"), "ID_Ciclo"].tolist()
        if normalizar_id(v)
    }
    return ids_ef - ids_ciclo


def _eh_ciclo_entrega_final(row: pd.Series, ids_exclusivos: set[str]) -> bool:
    id_ciclo = normalizar_id(row.get("ID_Ciclo", ""))
    if id_ciclo and id_ciclo in ids_exclusivos:
        return True
    return nome_parece_entrega_final(row.get("Nome_Ciclo", ""))


def entrega_final_separada(id_disciplina: str) -> bool:
    """True quando a entrega final tem ciclo próprio (não o último ciclo regular)."""
    return bool(_ids_ciclo_so_entrega_final(id_disciplina))


def ciclos_visiveis_avaliacao(ciclos: pd.DataFrame, id_disciplina: str) -> pd.DataFrame:
    """Esconde o ciclo exclusivo da entrega final quando ela reaproveita o último ciclo."""
    if ciclos is None or ciclos.empty:
        return ciclos if ciclos is not None else pd.DataFrame()
    if entrega_final_separada(id_disciplina):
        return ciclos
    ids_ef = _ids_ciclo_so_entrega_final(id_disciplina)
    mask = ciclos.apply(lambda row: not _eh_ciclo_entrega_final(row, ids_ef), axis=1)
    return ciclos[mask]


def preparar_ciclos_visiveis(df_ciclos: pd.DataFrame) -> pd.DataFrame:
    if df_ciclos is None or df_ciclos.empty:
        return df_ciclos if df_ciclos is not None else pd.DataFrame()
    partes = []
    if "ID_Disciplina" not in df_ciclos.columns:
        return df_ciclos
    for id_disc, grupo in df_ciclos.groupby(df_ciclos["ID_Disciplina"].map(normalizar_id), dropna=False):
        partes.append(ciclos_visiveis_avaliacao(grupo, str(id_disc or "")))
    if not partes:
        return df_ciclos
    return pd.concat(partes, ignore_index=True)


def escolher_ciclo_aberto(ciclos: pd.DataFrame, id_disciplina: str | None = None) -> pd.Series | None:
    """Ciclo aberto para tarefas do aluno; se vários, o de maior ordem."""
    if ciclos is None or ciclos.empty:
        return None
    visiveis = ciclos_visiveis_avaliacao(ciclos, id_disciplina) if id_disciplina else preparar_ciclos_visiveis(ciclos)
    ativos = filtrar_ciclos_ativos(visiveis)
    if ativos.empty:
        return None
    return ordenar_ciclos(ativos).iloc[-1]


def id_ultimo_ciclo_regular(id_disciplina: str) -> tuple[str, str]:
    """Último ciclo da disciplina que não é a entrega final. Retorna (id, nome)."""
    id_limpo = normalizar_id(id_disciplina)
    try:
        df = ler_aba("Ciclos")
    except Exception:
        return "", ""
    if df.empty:
        return "", ""
    disc = df[df["ID_Disciplina"].map(normalizar_id) == id_limpo]
    if disc.empty:
        return "", ""
    regulares = ciclos_visiveis_avaliacao(disc, id_limpo)
    base = regulares if not regulares.empty else disc
    ordenado = ordenar_ciclos(base)
    if ordenado.empty:
        return "", ""
    row = ordenado.iloc[-1]
    return normalizar_id(row.get("ID_Ciclo", "")), str(row.get("Nome_Ciclo", "")).strip()


def resolver_id_ciclo_componente(
    tipo: str,
    id_ciclo: str,
    id_disciplina: str,
) -> tuple[str, str]:
    """Para Entrega final sem presencial, usa o último ciclo regular.

    Retorna (id_ciclo_resolvido, nome_ciclo_origem ou "").
    """
    id_c = str(id_ciclo or "").strip()
    if str(tipo).strip() != "Entrega_Final":
        return id_c, ""
    ids_exclusivos = _ids_ciclo_so_entrega_final(id_disciplina)
    if normalizar_id(id_c) and normalizar_id(id_c) in ids_exclusivos:
        return id_c, ""
    ultimo_id, ultimo_nome = id_ultimo_ciclo_regular(id_disciplina)
    if ultimo_id:
        return ultimo_id, ultimo_nome
    return id_c, ""


def carregar_datas_encontro(id_disciplina: str | None = None) -> pd.DataFrame:
    try:
        df = ler_aba("Encontro_Presencial_Datas")
    except Exception:
        df = pd.DataFrame()
    df = _garantir_colunas(df, COLUNAS_DATAS)
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["Descricao"] = df["Descricao"].astype(str).str.strip()
    df["Ativo"] = df["Ativo"].map(lambda v: "Sim" if _ativo(v) or str(v).strip() == "" else "Não")
    if id_disciplina:
        df = df[df["ID_Disciplina"] == normalizar_id(id_disciplina)]
    out = normalizar_df_datas_editor(df)
    if not out.empty:
        out = out.sort_values("Data", na_position="last")
    return out


def salvar_datas_encontro(df: pd.DataFrame, id_disciplina: str | None = None) -> str | None:
    df = _garantir_colunas(df, COLUNAS_DATAS)
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["Descricao"] = df["Descricao"].astype(str).str.strip()
    df["Ativo"] = df["Ativo"].map(lambda v: "Sim" if _ativo(v) else "Não")
    df["Data"] = df["Data"].map(_fmt_data)
    df = df[df["Data"].ne("")]
    if id_disciplina:
        df["ID_Disciplina"] = normalizar_id(id_disciplina)
    if df["ID_Disciplina"].eq("").any():
        return "Toda data precisa estar vinculada a uma disciplina."
    duplicada = df.duplicated(subset=["ID_Disciplina", "Data"], keep=False)
    if duplicada.any():
        return "Há datas repetidas na mesma disciplina."

    if id_disciplina:
        try:
            base = ler_aba("Encontro_Presencial_Datas")
        except Exception:
            base = pd.DataFrame()
        base = _garantir_colunas(base, COLUNAS_DATAS)
        base["ID_Disciplina"] = base["ID_Disciplina"].map(normalizar_id)
        base["Data"] = base["Data"].map(_fmt_data)
        resto = base[base["ID_Disciplina"] != normalizar_id(id_disciplina)]
        df = pd.concat([resto, df], ignore_index=True)

    salvar_aba("Encontro_Presencial_Datas", df, COLUNAS_DATAS)
    return None


def datas_encontro_ativas(id_disciplina: str | None = None) -> pd.DataFrame:
    try:
        df = ler_aba("Encontro_Presencial_Datas")
    except Exception:
        return pd.DataFrame(columns=COLUNAS_DATAS)
    df = _garantir_colunas(df, COLUNAS_DATAS)
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df = df[df["Ativo"].map(_ativo)]
    df["_parsed"] = parse_data_planilha_series(df["Data"])
    df = df[df["_parsed"].notna()]
    if id_disciplina:
        df = df[df["ID_Disciplina"] == normalizar_id(id_disciplina)]
    return df.sort_values("_parsed")


def datas_encontro_para_calendario(df_calendario: pd.DataFrame | None = None) -> pd.DataFrame:
    """Datas do encontro no formato do Calendario_Aulas, sem duplicar o que já existe."""
    datas = datas_encontro_ativas()
    if datas.empty:
        return pd.DataFrame(columns=["Data", "ID_Disciplina", "Disciplina"])

    try:
        disciplinas = ler_aba("Disciplinas")
    except Exception:
        disciplinas = pd.DataFrame()
    nomes = {}
    if not disciplinas.empty:
        for _, row in disciplinas.iterrows():
            nomes[normalizar_id(row.get("ID_Disciplina", ""))] = str(row.get("Nome_Disciplina", "")).strip()

    nomes_cal = {}
    if df_calendario is not None and not df_calendario.empty and "ID_Disciplina" in df_calendario.columns:
        cal = df_calendario.copy()
        cal["_id"] = cal["ID_Disciplina"].map(normalizar_id)
        parsed = pd.to_datetime(parse_data_planilha_series(cal["Data"]), errors="coerce")
        cal["_data"] = parsed.dt.strftime("%d/%m/%Y")
        existentes = set(zip(cal["_id"], cal["_data"]))
        if "Disciplina" in cal.columns:
            for _, row in cal.iterrows():
                chave = str(row.get("_id", "")).strip()
                nome = str(row.get("Disciplina", "")).strip()
                if chave and nome and chave not in nomes_cal:
                    nomes_cal[chave] = nome
    else:
        existentes = set()

    linhas = []
    for _, row in datas.iterrows():
        id_disc = row["ID_Disciplina"]
        data_str = pd.Timestamp(row["_parsed"]).strftime("%d/%m/%Y")
        if (id_disc, data_str) in existentes:
            continue
        linhas.append(
            {
                "Data": data_str,
                "ID_Disciplina": id_disc,
                "Disciplina": nomes_cal.get(id_disc) or nomes.get(id_disc, ""),
            }
        )
    return pd.DataFrame(linhas)


def carregar_presenca_encontro(id_disciplina: str, data) -> pd.DataFrame:
    data_str = _fmt_data(data)
    try:
        df = ler_aba("Presenca_Encontro")
    except Exception:
        df = pd.DataFrame()
    df = _garantir_colunas(df, COLUNAS_PRESENCA)
    if df.empty or not data_str:
        return df.iloc[0:0]
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["_data"] = df["Data"].map(_fmt_data)
    return df[
        (df["ID_Disciplina"] == normalizar_id(id_disciplina))
        & (df["_data"] == data_str)
    ].drop(columns=["_data"], errors="ignore")


def _nome_disciplina_ajuste(id_disciplina: str) -> str:
    id_limpo = normalizar_id(id_disciplina)
    try:
        cal = ler_aba_frequencia("Calendario_Aulas")
        if not cal.empty and "ID_Disciplina" in cal.columns and "Disciplina" in cal.columns:
            filtro = cal[cal["ID_Disciplina"].map(normalizar_id) == id_limpo]
            nomes = [str(x).strip() for x in filtro["Disciplina"].tolist() if str(x).strip()]
            if nomes:
                return nomes[0]
    except Exception:
        pass
    try:
        disc = ler_aba("Disciplinas")
        filtro = disc[disc["ID_Disciplina"].map(normalizar_id) == id_limpo]
        if not filtro.empty:
            return str(filtro.iloc[0]["Nome_Disciplina"]).strip()
    except Exception:
        pass
    return ""


def _upsert_ajustes_presenca(linhas: list[dict]):
    if not linhas:
        return
    try:
        df = ler_aba_frequencia("Ajustes_Presenca")
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        df = pd.DataFrame(columns=_COLUNAS_AJUSTE_MIN)
    df.columns = [str(c).strip() for c in df.columns]
    for col in _COLUNAS_AJUSTE_MIN:
        if col not in df.columns:
            df[col] = ""

    df["_email"] = df["Email_Aluno"].astype(str).str.strip().str.lower()
    df["_data"] = df["Data"].map(_fmt_data)
    df["_disc"] = df["Disciplina"].astype(str).str.strip().str.lower()

    chaves = {
        (
            str(item["Email_Aluno"]).strip().lower(),
            _fmt_data(item["Data"]),
            str(item["Disciplina"]).strip().lower(),
        )
        for item in linhas
    }
    if df.empty:
        resto = df.drop(columns=["_email", "_data", "_disc"], errors="ignore")
    else:
        manter = ~df.apply(lambda r: (r["_email"], r["_data"], r["_disc"]) in chaves, axis=1)
        resto = df.loc[manter].drop(columns=["_email", "_data", "_disc"], errors="ignore")

    extras = [c for c in resto.columns if c not in _COLUNAS_AJUSTE_MIN]
    novas = pd.DataFrame(linhas)
    for col in extras:
        if col not in novas.columns:
            novas[col] = ""
    colunas = [c for c in resto.columns if c in set(_COLUNAS_AJUSTE_MIN) | set(extras)]
    if not colunas:
        colunas = list(dict.fromkeys(_COLUNAS_AJUSTE_MIN + extras))
    for col in colunas:
        if col not in resto.columns:
            resto[col] = ""
        if col not in novas.columns:
            novas[col] = ""
    out = pd.concat([resto[colunas], novas[colunas]], ignore_index=True)
    salvar_aba_frequencia("Ajustes_Presenca", out, colunas)


def salvar_presenca_encontro(
    id_disciplina: str,
    data,
    lancamentos: pd.DataFrame,
    usuario: dict,
) -> str | None:
    data_str = _fmt_data(data)
    id_limpo = normalizar_id(id_disciplina)
    if not data_str or not id_limpo:
        return "Informe a disciplina e a data do encontro."

    df_novo = lancamentos.copy()
    df_novo["Status"] = df_novo["Status"].astype(str).str.strip()
    df_novo = df_novo[df_novo["Status"].isin(STATUS_PRESENCA)]
    if df_novo.empty:
        return "Marque ao menos um aluno como Presente ou Falta."

    agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    email_lanc = str(usuario.get("email", "")).strip()
    nome_lanc = str(usuario.get("nome", "")).strip()
    nome_disc = _nome_disciplina_ajuste(id_limpo)

    try:
        base = ler_aba("Presenca_Encontro")
    except Exception:
        base = pd.DataFrame()
    base = _garantir_colunas(base, COLUNAS_PRESENCA)
    base["ID_Disciplina"] = base["ID_Disciplina"].map(normalizar_id)
    base["_data"] = base["Data"].map(_fmt_data)
    resto = base[
        ~((base["ID_Disciplina"] == id_limpo) & (base["_data"] == data_str))
    ].drop(columns=["_data"], errors="ignore")

    linhas = []
    ajustes = []
    for _, row in df_novo.iterrows():
        email = str(row.get("Email_Aluno", "")).strip().lower()
        if not email:
            continue
        linhas.append(
            {
                "ID_Disciplina": id_limpo,
                "Data": data_str,
                "Email_Aluno": email,
                "Nome_Aluno": str(row.get("Nome_Aluno", "")).strip(),
                "Sala": str(row.get("Sala", "")).strip(),
                "Grupo": str(row.get("Grupo", "")).strip(),
                "Status": str(row["Status"]).strip(),
                "Email_Lancador": email_lanc,
                "Nome_Lancador": nome_lanc,
                "Data_Lancamento": agora,
            }
        )
        ajustes.append(
            {
                "Email_Aluno": email,
                "Data": data_str,
                "Disciplina": nome_disc,
                "Novo_Status": str(row["Status"]).strip(),
            }
        )

    out = pd.concat([resto, pd.DataFrame(linhas)], ignore_index=True)
    salvar_aba("Presenca_Encontro", _garantir_colunas(out, COLUNAS_PRESENCA), COLUNAS_PRESENCA)
    _upsert_ajustes_presenca(ajustes)
    return None
