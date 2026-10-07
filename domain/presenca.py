"""Cálculo de presenças, dailies e grid de frequência em lote."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config import ICONE_STATUS_PRESENCA, MINUTOS_PRESENCA
from data.sheets import ler_aba, ler_aba_frequencia, salvar_aba_frequencia
from domain.ciclos import hoje_normalizado
from utils.datas import parse_data_planilha_series
from utils.disciplina import mapa_codigo_disciplina_legado, normalizar_id, remapear_coluna_id_disciplina


@st.cache_data(ttl=900, show_spinner=False)
def carregar_base_presenca() -> dict:
    """Carrega de uma vez as abas usadas em frequência e dailies (cache compartilhado)."""
    calendario = ler_aba_frequencia("Calendario_Aulas")
    try:
        from domain.encontro_presencial import datas_encontro_para_calendario

        extra = datas_encontro_para_calendario(calendario)
        if extra is not None and not extra.empty:
            calendario = pd.concat([calendario, extra], ignore_index=True)
    except Exception:
        pass
    return {
        "bd": ler_aba_frequencia("BD_Presenca"),
        "ajustes": ler_aba_frequencia("Ajustes_Presenca"),
        "calendario": calendario,
        "calendario_dailies": ler_aba_frequencia("Calendario_Dailies"),
        "entrancia": ler_aba("Entrancia_Turma"),
    }


def _ids_atuais_disciplinas() -> dict[str, str]:
    try:
        from domain.cadastros import carregar_disciplinas

        discs = carregar_disciplinas()
    except Exception:
        return {}
    if discs is None or discs.empty:
        return {}
    return {
        normalizar_id(row["ID_Disciplina"]): str(row.get("Nome_Disciplina", "")).strip()
        for _, row in discs.iterrows()
        if normalizar_id(row["ID_Disciplina"])
    }


def _preparar_entrancia(df_entrancia: pd.DataFrame) -> pd.DataFrame:
    df = df_entrancia.copy()
    atuais = _ids_atuais_disciplinas()
    if atuais:
        df = remapear_coluna_id_disciplina(df, atuais)
    df["Email_Limpo"] = df["Email_Pessoal"].astype(str).str.strip().str.lower()
    df["ID_Disc_Limpo"] = df["ID_Disciplina"].map(normalizar_id)
    return df


def _mapa_ids_legado_calendario(df: pd.DataFrame) -> dict[str, str]:
    atuais = _ids_atuais_disciplinas()
    if not atuais:
        return {}
    amostras = []
    nomes = df["Disciplina"] if "Disciplina" in df.columns else [""] * len(df)
    for codigo, nome in zip(df.get("ID_Disciplina", []), nomes):
        amostras.append((str(codigo), str(nome)))
    return mapa_codigo_disciplina_legado(atuais, amostras)


def _preparar_calendario(df_calendario: pd.DataFrame) -> pd.DataFrame:
    df = df_calendario.copy()
    if "ID_Disciplina" not in df.columns:
        df["ID_Disciplina"] = ""
    if "Data" not in df.columns:
        df["Data"] = ""
    if "Disciplina" not in df.columns:
        df["Disciplina"] = ""
    df["ID_Disc_Limpo"] = df["ID_Disciplina"].map(normalizar_id)
    mapa = _mapa_ids_legado_calendario(df)
    if mapa:
        df["ID_Disc_Limpo"] = df["ID_Disc_Limpo"].map(lambda v: mapa.get(v, v))
        df["ID_Disciplina"] = df["ID_Disc_Limpo"]
    df["Data_Formatada"] = pd.to_datetime(
        parse_data_planilha_series(df["Data"]), errors="coerce"
    ).dt.normalize()
    df["Chave_Disc"] = df["Disciplina"].astype(str).str.strip().str.lower()
    return df


_PALAVRAS_DAILY = ("daily", "dailie", "reuniao", "reunião", "orientacao", "orientação")


def _eh_chave_daily(chave: str) -> bool:
    texto = str(chave or "").strip().lower()
    return any(p in texto for p in _PALAVRAS_DAILY)


def _chaves_compativeis(a: str, b: str) -> bool:
    ca = str(a or "").strip().lower()
    cb = str(b or "").strip().lower()
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    return ca in cb or cb in ca


def _preparar_meet(df_bd_presenca: pd.DataFrame) -> pd.DataFrame:
    if df_bd_presenca.empty or "Email" not in df_bd_presenca.columns:
        return pd.DataFrame(columns=["Email_Limpo", "Data_Formatada", "Chave_Disc", "Minutos"])

    df = df_bd_presenca.copy()
    df["Email_Limpo"] = df["Email"].astype(str).str.strip().str.lower()
    df["Data_Formatada"] = pd.to_datetime(
        parse_data_planilha_series(df["Data"]), errors="coerce"
    ).dt.normalize()
    df["Chave_Disc"] = df["Disciplina"].astype(str).str.strip().str.lower()
    return (
        df.groupby(["Email_Limpo", "Data_Formatada", "Chave_Disc"], as_index=False)["Minutos"]
        .sum()
    )


def _cruzar_minutos(base: pd.DataFrame, meet: pd.DataFrame, *, tipo: str = "aulas") -> pd.DataFrame:
    out = base.copy()
    if meet.empty or out.empty:
        out["Minutos"] = 0.0
        return out

    meet = meet.copy()
    meet["Data_Formatada"] = pd.to_datetime(meet["Data_Formatada"], errors="coerce").dt.normalize()
    meet_exato = meet.rename(columns={"Minutos": "Minutos_Meet"})
    out = out.merge(
        meet_exato,
        on=["Email_Limpo", "Data_Formatada", "Chave_Disc"],
        how="left",
    )
    out["Minutos"] = pd.to_numeric(out["Minutos_Meet"], errors="coerce").fillna(0)
    out = out.drop(columns=["Minutos_Meet"], errors="ignore")

    pendentes = out["Minutos"].eq(0)
    if not pendentes.any():
        return out

    for idx in out.index[pendentes]:
        email = out.at[idx, "Email_Limpo"]
        data = out.at[idx, "Data_Formatada"]
        chave = out.at[idx, "Chave_Disc"]
        candidatos = meet[
            (meet["Email_Limpo"] == email) & (meet["Data_Formatada"] == data)
        ]
        if candidatos.empty:
            continue
        if tipo == "dailies":
            compat = candidatos[candidatos["Chave_Disc"].map(_eh_chave_daily)]
            if compat.empty:
                compat = candidatos[
                    candidatos["Chave_Disc"].map(lambda c: _chaves_compativeis(chave, c))
                ]
        else:
            compat = candidatos[
                candidatos["Chave_Disc"].map(lambda c: _chaves_compativeis(chave, c))
            ]
            if compat.empty and not _eh_chave_daily(chave):
                compat = candidatos[~candidatos["Chave_Disc"].map(_eh_chave_daily)]
        if not compat.empty:
            out.at[idx, "Minutos"] = float(compat["Minutos"].sum())
    return out


def _preparar_ajustes(df_ajustes: pd.DataFrame) -> pd.DataFrame:
    if df_ajustes.empty or "Email_Aluno" not in df_ajustes.columns:
        return pd.DataFrame(columns=["Email_Limpo", "Data_Str", "Chave_Disc", "Novo_Status"])

    df = df_ajustes.copy()
    df["Email_Limpo"] = df["Email_Aluno"].astype(str).str.strip().str.lower()
    df["Chave_Disc"] = df["Disciplina"].astype(str).str.strip().str.lower()
    df["Data_Parsed"] = parse_data_planilha_series(df["Data"])
    df["Data_Str"] = df["Data_Parsed"].dt.strftime("%d/%m/%Y")

    col_status = "Novo_Status"
    for candidata in ("Novo_Status", "Novo Status", "Status"):
        if candidata in df.columns:
            col_status = candidata
            break
    else:
        df["Novo_Status"] = ""
        col_status = "Novo_Status"

    if col_status != "Novo_Status":
        df["Novo_Status"] = df[col_status]

    return df[["Email_Limpo", "Data_Str", "Chave_Disc", "Novo_Status"]]


def _aplicar_status_presenca(matriz: pd.DataFrame, df_ajustes: pd.DataFrame) -> pd.DataFrame:
    hoje = hoje_normalizado()
    df = matriz.copy()
    df["Data_Formatada"] = pd.to_datetime(df["Data_Formatada"], errors="coerce").dt.normalize()
    df["Data_Str"] = df["Data_Formatada"].dt.strftime("%d/%m/%Y")

    if not df_ajustes.empty:
        df = df.merge(df_ajustes, on=["Email_Limpo", "Data_Str", "Chave_Disc"], how="left")

    # Só apura no dia seguinte (aula ~22h BRT; script de presença a cada 4h).
    pendente = df["Data_Formatada"] >= hoje
    invalido = df["Data_Formatada"].isna()
    tem_ajuste = (
        df["Novo_Status"].notna() & df["Novo_Status"].astype(str).str.strip().ne("")
        if "Novo_Status" in df.columns
        else pd.Series(False, index=df.index)
    )

    df["Status_Tecnico"] = "Falta"
    df["Status_Aluno"] = "Falta"

    df.loc[invalido, "Status_Tecnico"] = "Erro"
    df.loc[invalido, "Status_Aluno"] = "Data Inválida"
    df.loc[pendente & ~invalido, "Status_Tecnico"] = "Futuro"
    df.loc[pendente & ~invalido, "Status_Aluno"] = "Agendada"

    if tem_ajuste.any():
        df.loc[tem_ajuste, "Status_Tecnico"] = "Ajuste"
        df.loc[tem_ajuste, "Status_Aluno"] = df.loc[tem_ajuste, "Novo_Status"]

    base = ~invalido & ~pendente & ~tem_ajuste
    df.loc[base & (df["Minutos"] >= MINUTOS_PRESENCA), "Status_Tecnico"] = "Presente"
    df.loc[base & (df["Minutos"] >= MINUTOS_PRESENCA), "Status_Aluno"] = "Presente"
    df.loc[base & (df["Minutos"] > 0) & (df["Minutos"] < MINUTOS_PRESENCA), "Status_Tecnico"] = "Conectado"
    df.loc[base & (df["Minutos"] > 0) & (df["Minutos"] < MINUTOS_PRESENCA), "Status_Aluno"] = "Falta"

    df["Data"] = df["Data_Formatada"]
    return df


def calcular_matriz_presencas(email_aluno: str, dfs_cache: dict | None = None) -> pd.DataFrame:
    if dfs_cache is None:
        dfs_cache = carregar_base_presenca()
        df_bd_presenca = dfs_cache["bd"].copy()
        df_ajustes = dfs_cache["ajustes"].copy()
        df_calendario = dfs_cache["calendario"].copy()
        df_entrancia = dfs_cache["entrancia"].copy()
    else:
        df_bd_presenca = dfs_cache["bd"].copy()
        df_ajustes = dfs_cache["ajustes"].copy()
        df_calendario = dfs_cache["calendario"].copy()
        df_entrancia = dfs_cache["entrancia"].copy()

    email_aluno = str(email_aluno).strip().lower()
    df_entrancia = _preparar_entrancia(df_entrancia)
    disciplinas_aluno = df_entrancia.loc[
        df_entrancia["Email_Limpo"] == email_aluno, "ID_Disc_Limpo"
    ].unique()
    if len(disciplinas_aluno) == 0:
        return pd.DataFrame()

    df_calendario = _preparar_calendario(df_calendario)
    aulas = df_calendario[df_calendario["ID_Disc_Limpo"].isin(disciplinas_aluno)].copy()
    aulas["Email_Limpo"] = email_aluno

    meet = _preparar_meet(df_bd_presenca)
    meet = meet[meet["Email_Limpo"] == email_aluno]
    matriz = _cruzar_minutos(aulas, meet, tipo="aulas")

    ajustes = _preparar_ajustes(df_ajustes)
    ajustes = ajustes[ajustes["Email_Limpo"] == email_aluno]
    return _aplicar_status_presenca(matriz, ajustes)


def calcular_matriz_dailies(email_aluno: str, dfs_cache: dict | None = None) -> pd.DataFrame:
    if dfs_cache is None:
        dfs_cache = carregar_base_presenca()
    df_bd_presenca = dfs_cache["bd"].copy()
    df_entrancia = _preparar_entrancia(dfs_cache["entrancia"].copy())
    df_calendario_dailies = _preparar_calendario(dfs_cache["calendario_dailies"].copy())

    email_aluno = str(email_aluno).strip().lower()
    disciplinas_aluno = df_entrancia.loc[
        df_entrancia["Email_Limpo"] == email_aluno, "ID_Disc_Limpo"
    ].unique()
    if len(disciplinas_aluno) == 0:
        return pd.DataFrame()

    dailies = df_calendario_dailies[
        df_calendario_dailies["ID_Disc_Limpo"].isin(disciplinas_aluno)
    ].copy()
    dailies["Email_Limpo"] = email_aluno

    meet = _preparar_meet(df_bd_presenca)
    meet = meet[meet["Email_Limpo"] == email_aluno]
    matriz = _cruzar_minutos(dailies, meet, tipo="dailies")
    return _aplicar_status_dailies(matriz)


def _aplicar_status_dailies(matriz: pd.DataFrame) -> pd.DataFrame:
    hoje = hoje_normalizado()
    df = matriz.copy()
    df["Data_Formatada"] = pd.to_datetime(df["Data_Formatada"], errors="coerce").dt.normalize()
    df["Status_Tecnico"] = "Falta"
    df["Status_Aluno"] = "Falta"
    df.loc[df["Data_Formatada"].isna(), ["Status_Tecnico", "Status_Aluno"]] = [
        "Erro",
        "Data Inválida",
    ]
    df.loc[df["Data_Formatada"] >= hoje, "Status_Tecnico"] = "Futuro"
    df.loc[df["Data_Formatada"] >= hoje, "Status_Aluno"] = "Agendada"
    passado = (df["Data_Formatada"] < hoje) & df["Data_Formatada"].notna()
    df.loc[passado & (df["Minutos"] > 0), "Status_Tecnico"] = "Presente"
    df.loc[passado & (df["Minutos"] > 0), "Status_Aluno"] = "Presente"
    df["Data"] = df["Data_Formatada"]
    return df


def sequencia_faltas(status_aluno: pd.Series) -> tuple[int, int]:
    """Retorna (sequência atual no fim, maior sequência) de faltas consecutivas."""
    faltou = status_aluno.astype(str).str.strip().eq("Falta").tolist()
    if not faltou:
        return 0, 0
    max_seq = atual = 0
    for item in faltou:
        if item:
            atual += 1
            if atual > max_seq:
                max_seq = atual
        else:
            atual = 0
    atual_fim = 0
    for item in reversed(faltou):
        if item:
            atual_fim += 1
        else:
            break
    return atual_fim, max_seq


def compilar_grid_de_matriz(
    matriz: pd.DataFrame, alunos_turma: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    meta = alunos_turma.copy()
    meta["Email_Limpo"] = meta["Email_Pessoal"].astype(str).str.strip().str.lower()
    meta = meta.set_index("Email_Limpo")

    resumo_rows = []
    grid_rows = []

    for email, grupo in matriz.groupby("Email_Limpo"):
        if email not in meta.index:
            continue
        aluno = meta.loc[email]
        if isinstance(aluno, pd.DataFrame):
            aluno = aluno.iloc[0]
        vivido = grupo[
            ~grupo["Status_Tecnico"].isin(["Futuro", "Erro"])
        ].sort_values("Data")
        futuro = grupo[grupo["Status_Tecnico"] == "Futuro"]
        pres = len(vivido[vivido["Status_Aluno"] == "Presente"])
        faltas = len(vivido[vivido["Status_Aluno"] == "Falta"])
        total_vivido = len(vivido)
        pct_real = (pres / total_vivido * 100) if total_vivido > 0 else 100.0
        pct_proj = ((pres + len(futuro)) / len(grupo) * 100) if len(grupo) > 0 else 100.0
        seguidas, _max_seguidas = sequencia_faltas(vivido["Status_Aluno"])

        resumo_rows.append(
            {
                "Email_Cru": aluno["Email_Pessoal"],
                "Nome": aluno["Nome_Completo"],
                "Turma": str(aluno.get("Turma_Ingresso", "-")),
                "Sala": str(aluno["Sala"]),
                "Grupo": str(aluno["Grupo"]),
                "% Realizado": float(pct_real),
                "% Projetado": float(pct_proj),
                "Faltas": int(faltas),
                "Faltas seguidas": int(seguidas),
            }
        )

        for _, row in grupo.sort_values("Data").iterrows():
            data_ref = row.get("Data")
            if pd.isna(data_ref):
                continue
            icone = ICONE_STATUS_PRESENCA.get(row["Status_Tecnico"], "-")
            grid_rows.append(
                {
                    "Email_Cru": aluno["Email_Pessoal"],
                    "Data_Visual": pd.Timestamp(data_ref).strftime("%d/%m"),
                    "Data_Sort": data_ref,
                    "Status": icone,
                }
            )

    return pd.DataFrame(resumo_rows), pd.DataFrame(grid_rows)


def matriz_frequencia_turma(
    id_disciplina: str,
    alunos_turma: pd.DataFrame,
    dfs_cache: dict | None = None,
) -> pd.DataFrame:
    """Uma linha por aluno × aula, com Status_Tecnico/Status_Aluno já apurados."""
    if dfs_cache is None:
        dfs_cache = carregar_base_presenca()

    id_disciplina = normalizar_id(id_disciplina)
    emails_alvo = alunos_turma["Email_Pessoal"].astype(str).str.strip().str.lower().tolist()

    df_calendario = _preparar_calendario(dfs_cache["calendario"].copy())
    aulas = df_calendario[df_calendario["ID_Disc_Limpo"] == id_disciplina].copy()
    if aulas.empty:
        return pd.DataFrame()

    emails_df = pd.DataFrame({"Email_Limpo": emails_alvo})
    base = aulas.assign(_k=1).merge(emails_df.assign(_k=1), on="_k").drop(columns="_k")

    meet = _preparar_meet(dfs_cache["bd"].copy())
    meet = meet[meet["Email_Limpo"].isin(emails_alvo)]
    matriz = _cruzar_minutos(base, meet, tipo="aulas")

    ajustes = _preparar_ajustes(dfs_cache["ajustes"].copy())
    ajustes = ajustes[ajustes["Email_Limpo"].isin(emails_alvo)]
    return _aplicar_status_presenca(matriz, ajustes)


def matriz_dailies_turma(
    id_disciplina: str,
    alunos_turma: pd.DataFrame,
    dfs_cache: dict | None = None,
) -> pd.DataFrame:
    """Uma linha por aluno × daily, com Status_Tecnico/Status_Aluno já apurados."""
    if dfs_cache is None:
        dfs_cache = carregar_base_presenca()

    id_disciplina = normalizar_id(id_disciplina)
    emails_alvo = alunos_turma["Email_Pessoal"].astype(str).str.strip().str.lower().tolist()

    df_calendario = _preparar_calendario(dfs_cache["calendario_dailies"].copy())
    dailies = df_calendario[df_calendario["ID_Disc_Limpo"] == id_disciplina].copy()
    if dailies.empty:
        return pd.DataFrame()

    emails_df = pd.DataFrame({"Email_Limpo": emails_alvo})
    base = dailies.assign(_k=1).merge(emails_df.assign(_k=1), on="_k").drop(columns="_k")

    meet = _preparar_meet(dfs_cache["bd"].copy())
    meet = meet[meet["Email_Limpo"].isin(emails_alvo)]
    matriz = _cruzar_minutos(base, meet, tipo="dailies")
    return _aplicar_status_dailies(matriz)


def compilar_grid_frequencia(
    id_disciplina: str,
    alunos_turma: pd.DataFrame,
    dfs_cache: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compila resumo e grid de frequência para todos os alunos de uma disciplina em lote.
    Retorna (df_resumo, df_grid_detalhe).
    """
    matriz = matriz_frequencia_turma(id_disciplina, alunos_turma, dfs_cache)
    if matriz.empty:
        return pd.DataFrame(), pd.DataFrame()
    return compilar_grid_de_matriz(matriz, alunos_turma)


COLUNAS_AJUSTE = [
    "Data",
    "Email_Aluno",
    "Disciplina",
    "Novo_Status",
    "Justificativa",
    "Aluno",
    "Ajustado_Por",
    "Ajustado_Em",
]


def _chave_ajuste(email, data, disciplina) -> tuple[str, str, str]:
    data_ts = parse_data_planilha_series(pd.Series([data])).iloc[0]
    data_str = "" if pd.isna(data_ts) else pd.Timestamp(data_ts).strftime("%d/%m/%Y")
    return (
        str(email or "").strip().lower(),
        data_str,
        str(disciplina or "").strip().lower(),
    )


def ajustes_da_matriz(matriz: pd.DataFrame, dfs_cache: dict) -> pd.DataFrame:
    """Ajustes que valem em alguma aula da matriz (uma linha por aluno × aula ajustada)."""
    if matriz.empty:
        return pd.DataFrame()
    bruto = dfs_cache["ajustes"].copy()
    if bruto.empty or "Email_Aluno" not in bruto.columns:
        return pd.DataFrame()
    bruto.columns = [str(c).strip() for c in bruto.columns]
    for col in COLUNAS_AJUSTE:
        if col not in bruto.columns:
            bruto[col] = ""
    chaves = bruto.apply(
        lambda r: _chave_ajuste(r["Email_Aluno"], r["Data"], r["Disciplina"]), axis=1
    )
    bruto["Email_Limpo"] = [c[0] for c in chaves]
    bruto["Data_Str"] = [c[1] for c in chaves]
    bruto["Chave_Disc"] = [c[2] for c in chaves]

    aulas = matriz[matriz["Status_Tecnico"] == "Ajuste"][
        ["Email_Limpo", "Data_Str", "Chave_Disc", "Data_Formatada", "Status_Aluno"]
    ]
    extras = ["Justificativa", "Ajustado_Por", "Ajustado_Em", "Disciplina"]
    return aulas.merge(
        bruto[["Email_Limpo", "Data_Str", "Chave_Disc"] + extras].drop_duplicates(
            ["Email_Limpo", "Data_Str", "Chave_Disc"], keep="last"
        ),
        on=["Email_Limpo", "Data_Str", "Chave_Disc"],
        how="left",
    )


def gravar_ajustes_presenca(
    novos: list[dict], remover: list[tuple[str, str, str]], usuario: dict
) -> None:
    """Grava/substitui ajustes e remove os pedidos, lendo a aba atualizada antes de reescrever.

    ``novos``: dicts com Data, Email_Aluno, Disciplina, Novo_Status, Justificativa, Aluno.
    ``remover``: chaves (email, data dd/mm/aaaa, disciplina), comparadas sem caixa.
    """
    ler_aba_frequencia.clear()
    df = ler_aba_frequencia("Ajustes_Presenca").copy()
    df.columns = [str(c).strip() for c in df.columns]
    for col in COLUNAS_AJUSTE:
        if col not in df.columns:
            df[col] = ""
    colunas = list(dict.fromkeys(COLUNAS_AJUSTE + list(df.columns)))

    agora = pd.Timestamp.now(tz="America/Sao_Paulo").strftime("%d/%m/%Y %H:%M")
    autor = str(usuario.get("nome") or usuario.get("email") or "").strip()
    linhas_novas = [
        {**item, "Ajustado_Por": autor, "Ajustado_Em": agora} for item in novos
    ]
    sair = {_chave_ajuste(*c) for c in remover}
    sair |= {
        _chave_ajuste(i["Email_Aluno"], i["Data"], i["Disciplina"]) for i in linhas_novas
    }
    if not df.empty and sair:
        chaves = df.apply(
            lambda r: _chave_ajuste(r["Email_Aluno"], r["Data"], r["Disciplina"]), axis=1
        )
        df = df[~chaves.map(lambda c: c in sair)]

    out = pd.concat([df[colunas], pd.DataFrame(linhas_novas, columns=colunas)], ignore_index=True)
    salvar_aba_frequencia("Ajustes_Presenca", out, colunas)


def compilar_grid_dailies(
    id_disciplina: str,
    alunos_turma: pd.DataFrame,
    dfs_cache: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    matriz = matriz_dailies_turma(id_disciplina, alunos_turma, dfs_cache)
    if matriz.empty:
        return pd.DataFrame(), pd.DataFrame()
    return compilar_grid_de_matriz(matriz, alunos_turma)
