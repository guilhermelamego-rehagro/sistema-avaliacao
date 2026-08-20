"""Cria a estrutura padrão de ciclos e componentes ao cadastrar uma disciplina."""

from __future__ import annotations

import pandas as pd

from config import CICLO_ENTREGA_FINAL, CICLOS_PADRAO, PESOS_PADRAO
from data.sheets import ler_aba
from domain.cadastros import carregar_ciclos, salvar_ciclos
from domain.componentes import (
    _gerar_id_componente,
    _inferir_tipo,
    carregar_componentes_disciplina,
    salvar_componentes_disciplina,
)
from domain.encontro_presencial import id_ultimo_ciclo_regular, entrega_final_separada
from utils.disciplina import normalizar_id

COLUNAS_COMP = [
    "ID_Componente",
    "ID_Disciplina",
    "Nome",
    "Tipo",
    "Peso",
    "Ordem",
    "ID_Ciclo",
    "Ativo",
]


def _ids_ciclo_existentes() -> set[str]:
    try:
        df = ler_aba("Ciclos")
    except Exception:
        return set()
    if df.empty or "ID_Ciclo" not in df.columns:
        return set()
    return {normalizar_id(v) for v in df["ID_Ciclo"].tolist() if normalizar_id(v)}


def _novo_id_ciclo(existentes: set[str], id_disciplina: str, sufixo: str) -> str:
    base = f"{normalizar_id(id_disciplina)}-{sufixo}"
    if base not in existentes:
        existentes.add(base)
        return base
    n = 2
    while f"{base}-{n}" in existentes:
        n += 1
    candidato = f"{base}-{n}"
    existentes.add(candidato)
    return candidato


def _componentes_persistidos(id_disciplina: str) -> pd.DataFrame:
    id_limpo = normalizar_id(id_disciplina)
    try:
        df = ler_aba("Config_Componentes")
    except Exception:
        return pd.DataFrame(columns=COLUNAS_COMP)
    if df.empty or "ID_Disciplina" not in df.columns:
        return pd.DataFrame(columns=COLUNAS_COMP)
    return df[df["ID_Disciplina"].map(normalizar_id) == id_limpo]


def _ciclos_da_disciplina(df_ciclos: pd.DataFrame, id_disciplina: str) -> pd.DataFrame:
    if df_ciclos is None or df_ciclos.empty:
        return pd.DataFrame()
    return df_ciclos[df_ciclos["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disciplina)]


def _id_ciclo_por_nome_ou_ordem(ciclos: pd.DataFrame, nome: str, ordem: int) -> str:
    if ciclos is None or ciclos.empty:
        return ""
    por_nome = ciclos[ciclos["Nome_Ciclo"].astype(str).str.strip().str.lower() == nome.strip().lower()]
    if not por_nome.empty:
        return normalizar_id(por_nome.iloc[0]["ID_Ciclo"])
    ordens = pd.to_numeric(ciclos["Ordem"], errors="coerce")
    por_ordem = ciclos[ordens == ordem]
    if not por_ordem.empty:
        return normalizar_id(por_ordem.iloc[0]["ID_Ciclo"])
    return ""


def garantir_estrutura_padrao(id_disciplina: str) -> list[str]:
    """Garante 4 ciclos e os 7 componentes padrão, sem sobrescrever o que já existe."""
    id_limpo = normalizar_id(id_disciplina)
    if not id_limpo:
        return []
    avisos: list[str] = []
    avisos.extend(_garantir_ciclos_regulares(id_limpo))
    avisos.extend(_garantir_componentes_padrao(id_limpo))
    return avisos


def _garantir_ciclos_regulares(id_disciplina: str) -> list[str]:
    df = carregar_ciclos()
    da_disc = _ciclos_da_disciplina(df, id_disciplina)
    existentes_ids = _ids_ciclo_existentes()
    novos = []
    for nome, ordem in CICLOS_PADRAO:
        if _id_ciclo_por_nome_ou_ordem(da_disc, nome, ordem):
            continue
        novos.append(
            {
                "ID_Ciclo": _novo_id_ciclo(existentes_ids, id_disciplina, f"C{ordem}"),
                "Nome_Ciclo": nome,
                "ID_Disciplina": id_disciplina,
                "Data_Inicio_Ciclo": None,
                "Data_Apresentacao": None,
                "Data início": None,
                "Data fim": None,
                "Status": "inativo",
                "Ordem": ordem,
            }
        )
    if not novos:
        return []
    df_save = pd.concat([df, pd.DataFrame(novos)], ignore_index=True)
    erro = salvar_ciclos(df_save)
    if erro:
        return [f"Não foi possível criar os ciclos padrão: {erro}"]
    nomes = ", ".join(item["Nome_Ciclo"] for item in novos)
    return [f"Ciclos padrão criados ({nomes}). Preencha as datas em Cadastro de ciclos."]


def _garantir_componentes_padrao(id_disciplina: str) -> list[str]:
    if not _componentes_persistidos(id_disciplina).empty:
        return []
    ciclos = _ciclos_da_disciplina(carregar_ciclos(), id_disciplina)
    linhas = []
    for nome, peso, ordem in PESOS_PADRAO:
        tipo = _inferir_tipo(nome)
        id_ciclo = ""
        if tipo == "Ciclo":
            id_ciclo = _id_ciclo_por_nome_ou_ordem(ciclos, nome, ordem)
        linhas.append(
            {
                "ID_Componente": _gerar_id_componente(id_disciplina, ordem),
                "ID_Disciplina": id_disciplina,
                "Nome": nome,
                "Tipo": tipo,
                "Peso": peso,
                "Ordem": ordem,
                "ID_Ciclo": id_ciclo,
                "Ativo": "Sim",
            }
        )
    erro = salvar_componentes_disciplina(id_disciplina, pd.DataFrame(linhas))
    if erro:
        return [f"Não foi possível criar os componentes padrão: {erro}"]
    return [
        "Componentes padrão criados: 4 ciclos, entrega final, reuniões diárias e atividades individuais."
    ]


def entrega_final_ja_separada(id_disciplina: str) -> bool:
    return entrega_final_separada(id_disciplina)


def aplicar_decisao_entrega_final(id_disciplina: str, separar: bool) -> str | None:
    """Liga ou desliga o ciclo próprio da entrega final e atualiza o componente."""
    id_limpo = normalizar_id(id_disciplina)
    garantir_estrutura_padrao(id_limpo)
    comps = carregar_componentes_disciplina(id_limpo)
    if comps.empty:
        return "Não há componentes para vincular a entrega final."
    mask_ef = comps["Tipo"].astype(str).str.strip() == "Entrega_Final"
    if not mask_ef.any():
        return "A disciplina não tem componente do tipo Entrega final."

    if separar:
        id_ciclo = _garantir_ciclo_entrega_final(id_limpo)
        if not id_ciclo:
            return "Não foi possível criar o ciclo da entrega final."
        comps.loc[mask_ef, "ID_Ciclo"] = id_ciclo
    else:
        ultimo_id, _ = id_ultimo_ciclo_regular(id_limpo)
        comps.loc[mask_ef, "ID_Ciclo"] = ultimo_id

    return salvar_componentes_disciplina(id_limpo, comps)


def _garantir_ciclo_entrega_final(id_disciplina: str) -> str:
    nome, ordem = CICLO_ENTREGA_FINAL
    df = carregar_ciclos()
    da_disc = _ciclos_da_disciplina(df, id_disciplina)
    ja = _id_ciclo_por_nome_ou_ordem(da_disc, nome, ordem)
    if ja:
        return ja
    existentes_ids = _ids_ciclo_existentes()
    novo_id = _novo_id_ciclo(existentes_ids, id_disciplina, "EF")
    if not da_disc.empty:
        ordem_num = pd.to_numeric(da_disc["Ordem"], errors="coerce")
        if ordem_num.notna().any():
            ordem = int(ordem_num.max()) + 1
    novo = {
        "ID_Ciclo": novo_id,
        "Nome_Ciclo": nome,
        "ID_Disciplina": id_disciplina,
        "Data_Inicio_Ciclo": None,
        "Data_Apresentacao": None,
        "Data início": None,
        "Data fim": None,
        "Status": "inativo",
        "Ordem": ordem,
    }
    erro = salvar_ciclos(pd.concat([df, pd.DataFrame([novo])], ignore_index=True))
    if erro:
        return ""
    return novo_id
