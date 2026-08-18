"""Cadastro e persistência dos componentes de avaliação por disciplina."""

from __future__ import annotations

import re

import pandas as pd

from config import PESOS_PADRAO, TIPOS_COMPONENTE, TIPOS_COMPONENTE_LABEL
from data.sheets import ler_aba, limpar_cache_planilhas, planilha


def _inferir_tipo(nome: str) -> str:
    nome_l = nome.lower()
    if "entrega" in nome_l or "final" in nome_l:
        return "Entrega_Final"
    if "dail" in nome_l or "reuni" in nome_l:
        return "Reuniao_Diaria"
    if "ativid" in nome_l or "canvas" in nome_l or "individual" in nome_l:
        return "Atividade_Individual"
    return "Ciclo"


def _gerar_id_componente(id_disciplina: str, ordem: int) -> str:
    disc_curto = re.sub(r"[^A-Za-z0-9]", "", str(id_disciplina))[:8].upper() or "DISC"
    return f"COMP-{disc_curto}-{ordem:02d}"


def normalizar_dataframe_componentes(df: pd.DataFrame, id_disciplina: str | None = None) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "ID_Componente",
                "ID_Disciplina",
                "Nome",
                "Tipo",
                "Peso",
                "Ordem",
                "ID_Ciclo",
                "Ativo",
            ]
        )

    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]

    if "Nome" not in out.columns and "Componente" in out.columns:
        out["Nome"] = out["Componente"]

    if "Tipo" not in out.columns:
        out["Tipo"] = out["Nome"].apply(_inferir_tipo)

    if "ID_Componente" not in out.columns:
        out["ID_Componente"] = ""

    if id_disciplina:
        out["ID_Disciplina"] = id_disciplina

    out["Peso"] = pd.to_numeric(out["Peso"], errors="coerce").fillna(0)
    out["Ordem"] = pd.to_numeric(out["Ordem"], errors="coerce").fillna(0).astype(int)
    out["Ativo"] = out.get("Ativo", "Sim").astype(str)
    out["ID_Ciclo"] = out.get("ID_Ciclo", "").astype(str).replace("nan", "")
    out["Nome"] = out["Nome"].astype(str).str.strip()
    out["Tipo"] = out["Tipo"].astype(str).str.strip()

    for idx, row in out.iterrows():
        if not str(row.get("ID_Componente", "")).strip():
            out.at[idx, "ID_Componente"] = _gerar_id_componente(
                row["ID_Disciplina"], int(row["Ordem"]) or (idx + 1)
            )

    cols = [
        "ID_Componente",
        "ID_Disciplina",
        "Nome",
        "Tipo",
        "Peso",
        "Ordem",
        "ID_Ciclo",
        "Ativo",
    ]
    return out[cols].sort_values("Ordem")


def carregar_componentes_disciplina(id_disciplina: str) -> pd.DataFrame:
    id_limpo = str(id_disciplina).strip()
    try:
        df = ler_aba("Config_Componentes")
    except Exception:
        df = pd.DataFrame()

    if not df.empty and "ID_Disciplina" in df.columns:
        filtrado = df[df["ID_Disciplina"].astype(str).str.strip() == id_limpo]
        ativos = filtrado[
            filtrado.get("Ativo", "Sim").astype(str).str.lower().isin(
                ["sim", "s", "ativo", "1", "true"]
            )
        ]
        if not ativos.empty:
            return normalizar_dataframe_componentes(ativos, id_limpo)

    padrao = []
    df_ciclos = pd.DataFrame()
    try:
        from data.sheets import ler_aba as _ler
        df_ciclos = _ler("Ciclos")
        df_ciclos = df_ciclos[df_ciclos["ID_Disciplina"].astype(str).str.strip() == id_limpo]
    except Exception:
        pass

    for nome, peso, ordem in PESOS_PADRAO:
        id_ciclo = ""
        if not df_ciclos.empty and _inferir_tipo(nome) in ("Ciclo", "Entrega_Final"):
            match = df_ciclos[df_ciclos["Nome_Ciclo"].astype(str).str.strip() == nome]
            if not match.empty:
                id_ciclo = str(match.iloc[0]["ID_Ciclo"]).strip()
        padrao.append(
            {
                "ID_Componente": _gerar_id_componente(id_limpo, ordem),
                "ID_Disciplina": id_limpo,
                "Nome": nome,
                "Tipo": _inferir_tipo(nome),
                "Peso": peso,
                "Ordem": ordem,
                "ID_Ciclo": id_ciclo,
                "Ativo": "Sim",
            }
        )
    return pd.DataFrame(padrao)


def salvar_componentes_disciplina(id_disciplina: str, df_novos: pd.DataFrame) -> str | None:
    id_limpo = str(id_disciplina).strip()
    df_save = normalizar_dataframe_componentes(df_novos, id_limpo)

    if df_save["Tipo"].isin(TIPOS_COMPONENTE).sum() != len(df_save):
        return "Todos os componentes precisam ter um tipo válido."

    peso_total = float(df_save["Peso"].sum())
    if abs(peso_total - 100.0) > 0.01:
        return f"A soma dos pesos deve ser 100%. Atual: {peso_total:.1f}%"

    ciclos_tipos = df_save[df_save["Tipo"].isin(["Ciclo", "Entrega_Final"])]
    for _, row in ciclos_tipos.iterrows():
        tipo = str(row["Tipo"]).strip()
        id_ciclo = str(row["ID_Ciclo"]).strip()
        nome = str(row["Nome"]).strip()
        if tipo == "Ciclo" and not id_ciclo:
            return f"Componentes do tipo Ciclo precisam de vínculo com ID_Ciclo: {nome}"

    try:
        df_todos = ler_aba("Config_Componentes")
        df_todos = normalizar_dataframe_componentes(df_todos) if not df_todos.empty else df_todos
    except Exception:
        df_todos = pd.DataFrame(
            columns=[
                "ID_Componente",
                "ID_Disciplina",
                "Nome",
                "Tipo",
                "Peso",
                "Ordem",
                "ID_Ciclo",
                "Ativo",
            ]
        )

    if not df_todos.empty:
        df_restante = df_todos[df_todos["ID_Disciplina"].astype(str).str.strip() != id_limpo]
        df_final = pd.concat([df_restante, df_save], ignore_index=True)
    else:
        df_final = df_save

    ws = planilha.worksheet("Config_Componentes")
    ws.clear()
    ws.append_row(
        [
            "ID_Componente",
            "ID_Disciplina",
            "Nome",
            "Tipo",
            "Peso",
            "Ordem",
            "ID_Ciclo",
            "Ativo",
        ]
    )
    if not df_final.empty:
        ws.append_rows(df_final.astype(str).values.tolist())

    limpar_cache_planilhas()
    return None


def novo_componente_vazio(id_disciplina: str, proxima_ordem: int) -> dict:
    return {
        "ID_Componente": _gerar_id_componente(id_disciplina, proxima_ordem),
        "ID_Disciplina": id_disciplina,
        "Nome": f"Novo componente {proxima_ordem}",
        "Tipo": "Ciclo",
        "Peso": 0.0,
        "Ordem": proxima_ordem,
        "ID_Ciclo": "",
        "Ativo": "Sim",
    }


def opcoes_tipo_label() -> list[str]:
    return [TIPOS_COMPONENTE_LABEL[t] for t in TIPOS_COMPONENTE]


def label_para_tipo(label: str) -> str:
    for tipo, lbl in TIPOS_COMPONENTE_LABEL.items():
        if lbl == label:
            return tipo
    return label
