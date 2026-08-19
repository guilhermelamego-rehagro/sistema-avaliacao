"""Matriz (versões), carrosséis, turmas e ofertas — sem alterar notas nem grupos."""

from __future__ import annotations

import re
import time
from datetime import date

import pandas as pd

from data.sheets import ler_aba, salvar_aba
from domain.cadastros import carregar_disciplinas
from utils.datas import parse_data_planilha, parse_data_planilha_series
from utils.disciplina import normalizar_id

COLUNAS_MATRIZES = ["ID_Matriz", "Nome", "Versao", "Status", "Observacao"]
COLUNAS_ITENS = ["ID_Matriz", "Ordem", "ID_Disciplina", "Encontro_Presencial_Sugerido"]
COLUNAS_CARROSSEIS = [
    "ID_Carrossel",
    "Nome",
    "ID_Matriz",
    "Posicao_Inicio",
    "Data_Inicio",
    "Status",
]
COLUNAS_CARROSSEL_ITENS = ["ID_Carrossel", "Ordem", "ID_Disciplina"]
COLUNAS_TURMAS = ["ID_Turma", "ID_Carrossel", "Posicao_Entrada", "Status", "Observacao"]
COLUNAS_TRIMESTRES = [
    "ID_Trimestre",
    "Ano",
    "Numero",
    "Nome",
    "Data_Inicio",
    "Data_Fim",
    "Status",
]
COLUNAS_OFERTAS = [
    "ID_Oferta",
    "ID_Carrossel",
    "ID_Matriz",
    "ID_Disciplina",
    "ID_Trimestre",
    "Ano",
    "Trimestre",
    "Tipo",
    "Status",
    "Data_Prevista_Inicio",
    "Data_Prevista_Fim",
    "Encontro_Presencial",
    "Observacao",
]
COLUNAS_OFERTA_TURMAS = ["ID_Oferta", "ID_Turma"]
COLUNAS_EXCECOES = ["ID_Oferta", "Email_Aluno", "Nome_Aluno", "Tipo", "Motivo"]

STATUS_MATRIZ = ["vigente", "inativa"]
STATUS_CARROSSEL = ["ativo", "inativo"]
STATUS_TURMA = ["ativo", "inativo", "formado"]
STATUS_OFERTA = ["Planejada", "Ativa", "Encerrada"]
TIPO_OFERTA = ["Regular", "Especial"]
TIPO_EXCECAO = ["Incluir", "Desvincular"]
ENCONTRO_OPCOES = ["Não", "Sim"]
NUMEROS_TRIMESTRE = ["1", "2", "3", "4"]
STATUS_TRIMESTRE = ["Planejado", "Em andamento", "Encerrado"]


def _garantir_colunas(df: pd.DataFrame, obrigatorias: list[str]) -> pd.DataFrame:
    out = pd.DataFrame() if df is None or df.empty else df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for col in obrigatorias:
        if col not in out.columns:
            out[col] = ""
    extras = [c for c in out.columns if c not in obrigatorias]
    return out[obrigatorias + extras]


def _ler(nome: str, colunas: list[str]) -> pd.DataFrame:
    try:
        df = ler_aba(nome)
    except Exception:
        df = pd.DataFrame()
    return _garantir_colunas(df, colunas)


def _gravar(nome: str, df: pd.DataFrame, colunas: list[str]) -> None:
    salvar_aba(nome, _garantir_colunas(df, colunas), colunas)


def _status_lista(valor, opcoes: list[str], padrao: str) -> str:
    texto = str(valor or "").strip()
    mapa = {o.lower(): o for o in opcoes}
    return mapa.get(texto.lower(), padrao)


def _encontro(valor) -> str:
    texto = str(valor or "").strip().lower()
    if texto in {"sim", "s", "1", "true", "presencial"}:
        return "Sim"
    return "Não"


def _int_ou_vazio(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = str(valor).strip()
    if texto.lower() in {"", "nan", "none"}:
        return ""
    try:
        return int(float(texto))
    except ValueError:
        return texto


def _fmt_data(valor) -> str:
    parsed = parse_data_planilha(valor)
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).strftime("%d/%m/%Y")


def _data_ou_none(valor) -> date | None:
    parsed = parse_data_planilha(valor)
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).date()


def _datas_para_editor(serie: pd.Series) -> list:
    parsed = parse_data_planilha_series(serie)
    saida = []
    for valor in parsed:
        if pd.isna(valor):
            saida.append(None)
        else:
            saida.append(pd.Timestamp(valor).date())
    return saida


def codigo_trimestre(ano, numero) -> str:
    a = _int_ou_vazio(ano)
    n = _int_ou_vazio(numero)
    if not a or not n:
        return ""
    return f"{int(a)}-{int(n)}"


def rotulo_trimestre(ano, numero) -> str:
    a = _int_ou_vazio(ano)
    n = _int_ou_vazio(numero)
    if not a or not n:
        return ""
    return f"{int(a)}/{int(n)}"


def parse_id_trimestre(valor) -> tuple[str, str]:
    texto = normalizar_id(valor).replace("/", "-")
    if "-" in texto:
        ano, num = texto.split("-", 1)
        return str(_int_ou_vazio(ano) or ""), str(_int_ou_vazio(num) or "")
    return "", ""


def proximo_id(existentes, prefixo: str) -> str:
    usados = {normalizar_id(x) for x in existentes if normalizar_id(x)}
    n = 1
    while f"{prefixo}{n}" in usados:
        n += 1
    return f"{prefixo}{n}"


_TURMA_PREFIXO = re.compile(r"^T(\d+)", re.I)
_ABAS_CODIGO_TURMA = ("Turmas", "Oferta_Turmas", "Base_Alunos", "Entrancia_Turma")


def normalizar_codigo_turma(valor) -> str:
    """Código canônico com zero à esquerda (T06, T14). Aceita T06-07/2024 → T06."""
    texto = normalizar_id(valor).upper().replace(" ", "")
    if not texto:
        return ""
    if texto.isdigit():
        return f"T{texto.zfill(2)}"
    match = _TURMA_PREFIXO.match(texto)
    if match:
        return f"T{match.group(1).zfill(2)}"
    return texto


def encontro_sugerido_por_ordem(ordem: int) -> str:
    """Ímpar = meio de semestre (sem encontro); par = fim de semestre (com encontro)."""
    try:
        numero = int(ordem)
    except (TypeError, ValueError):
        return "Não"
    return "Sim" if numero % 2 == 0 else "Não"


def nome_disciplina(df_disc: pd.DataFrame, id_disc: str) -> str:
    id_limpo = normalizar_id(id_disc)
    if df_disc.empty or not id_limpo:
        return id_limpo
    match = df_disc[df_disc["ID_Disciplina"].map(normalizar_id) == id_limpo]
    if match.empty:
        return id_limpo
    return str(match.iloc[0]["Nome_Disciplina"]).strip() or id_limpo


def rotulo_disciplina(df_disc: pd.DataFrame, id_disc: str) -> str:
    id_limpo = normalizar_id(id_disc)
    nome = nome_disciplina(df_disc, id_limpo)
    if not id_limpo:
        return ""
    if nome == id_limpo:
        return id_limpo
    return f"{id_limpo} — {nome}"


# --- Matrizes ---


def carregar_matrizes() -> pd.DataFrame:
    df = _ler("Matrizes", COLUNAS_MATRIZES)
    df["ID_Matriz"] = df["ID_Matriz"].map(normalizar_id)
    df["Nome"] = df["Nome"].astype(str).str.strip()
    df["Versao"] = df["Versao"].map(_int_ou_vazio)
    df["Status"] = df["Status"].map(lambda v: _status_lista(v, STATUS_MATRIZ, "inativa"))
    df["Observacao"] = df["Observacao"].astype(str).str.strip().replace({"nan": "", "None": ""})
    return df


def carregar_matriz_itens() -> pd.DataFrame:
    df = _ler("Matriz_Itens", COLUNAS_ITENS)
    df["ID_Matriz"] = df["ID_Matriz"].map(normalizar_id)
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["Ordem"] = pd.to_numeric(df["Ordem"], errors="coerce")
    df["Encontro_Presencial_Sugerido"] = df["Encontro_Presencial_Sugerido"].map(_encontro)
    if not df.empty:
        df = df.sort_values(["ID_Matriz", "Ordem"], na_position="last")
    return df


def itens_da_matriz(id_matriz: str, itens: pd.DataFrame | None = None) -> pd.DataFrame:
    if itens is None:
        itens = carregar_matriz_itens()
    id_limpo = normalizar_id(id_matriz)
    if itens.empty:
        return itens
    out = itens[itens["ID_Matriz"].map(normalizar_id) == id_limpo].copy()
    return out.sort_values("Ordem", na_position="last")


def salvar_matriz(
    linha: dict,
    itens: pd.DataFrame,
    matrizes: pd.DataFrame | None = None,
    todos_itens: pd.DataFrame | None = None,
) -> str | None:
    id_matriz = normalizar_id(linha.get("ID_Matriz", ""))
    nome = str(linha.get("Nome", "")).strip()
    if not id_matriz:
        return "Informe o código da matriz."
    if not nome:
        return "Informe o nome da versão da matriz (ex.: Matriz GGA 2024)."

    if matrizes is None:
        matrizes = carregar_matrizes()
    status = _status_lista(linha.get("Status"), STATUS_MATRIZ, "inativa")
    versao = _int_ou_vazio(linha.get("Versao")) or 1
    nova = {
        "ID_Matriz": id_matriz,
        "Nome": nome,
        "Versao": versao,
        "Status": status,
        "Observacao": str(linha.get("Observacao", "")).strip(),
    }
    resto = matrizes[matrizes["ID_Matriz"].map(normalizar_id) != id_matriz]
    if status == "vigente":
        resto = resto.copy()
        resto["Status"] = "inativa"
    matrizes = pd.concat([resto, pd.DataFrame([nova])], ignore_index=True)

    itens = _garantir_colunas(itens, COLUNAS_ITENS)
    itens["ID_Matriz"] = id_matriz
    itens["ID_Disciplina"] = itens["ID_Disciplina"].map(normalizar_id)
    itens["Ordem"] = pd.to_numeric(itens["Ordem"], errors="coerce")
    itens["Encontro_Presencial_Sugerido"] = itens["Encontro_Presencial_Sugerido"].map(_encontro)
    itens = itens[itens["ID_Disciplina"].ne("")]
    if itens.empty:
        return "Inclua ao menos uma disciplina na ordem da matriz."
    if itens["ID_Disciplina"].duplicated().any():
        return "Há disciplina repetida nesta matriz."
    itens = itens.sort_values("Ordem", na_position="last")
    itens["Ordem"] = range(1, len(itens) + 1)
    itens["Encontro_Presencial_Sugerido"] = [
        _encontro(v)
        if str(v or "").strip() and str(v).strip().lower() not in {"nan", "none"}
        else encontro_sugerido_por_ordem(ordem)
        for ordem, v in zip(itens["Ordem"], itens["Encontro_Presencial_Sugerido"])
    ]

    if todos_itens is None:
        todos_itens = carregar_matriz_itens()
    resto_itens = todos_itens[todos_itens["ID_Matriz"].map(normalizar_id) != id_matriz]
    todos_itens = pd.concat([resto_itens, itens[COLUNAS_ITENS]], ignore_index=True)
    _gravar("Matrizes", matrizes, COLUNAS_MATRIZES)
    _gravar("Matriz_Itens", todos_itens, COLUNAS_ITENS)
    return None


def remover_matriz(id_matriz: str) -> str | None:
    id_limpo = normalizar_id(id_matriz)
    if not id_limpo:
        return "Matriz sem código."
    carrosseis = carregar_carrosseis()
    if not carrosseis.empty and (carrosseis["ID_Matriz"].map(normalizar_id) == id_limpo).any():
        return "Há carrossel usando esta matriz. Remova ou altere o carrossel antes."
    matrizes = carregar_matrizes()
    matrizes = matrizes[matrizes["ID_Matriz"].map(normalizar_id) != id_limpo]
    itens = carregar_matriz_itens()
    itens = itens[itens["ID_Matriz"].map(normalizar_id) != id_limpo]
    _gravar("Matrizes", matrizes, COLUNAS_MATRIZES)
    _gravar("Matriz_Itens", itens, COLUNAS_ITENS)
    return None


def criar_matriz_das_disciplinas(nome: str = "") -> tuple[str | None, str]:
    discs = carregar_disciplinas()
    discs = discs[discs["ID_Disciplina"].map(normalizar_id).ne("")]
    if discs.empty:
        return "Cadastre disciplinas antes de criar a matriz.", ""
    matrizes = carregar_matrizes()
    id_matriz = proximo_id(matrizes["ID_Matriz"], "MX")
    versao = 1
    if not matrizes.empty:
        nums = pd.to_numeric(matrizes["Versao"], errors="coerce")
        if nums.notna().any():
            versao = int(nums.max()) + 1
    nome_limpo = str(nome or "").strip() or f"Matriz GGA {versao}"
    itens_linhas = []
    for i, (_, row) in enumerate(discs.iterrows(), start=1):
        itens_linhas.append(
            {
                "ID_Matriz": id_matriz,
                "Ordem": i,
                "ID_Disciplina": normalizar_id(row["ID_Disciplina"]),
                "Encontro_Presencial_Sugerido": encontro_sugerido_por_ordem(i),
            }
        )
    erro = salvar_matriz(
        {
            "ID_Matriz": id_matriz,
            "Nome": nome_limpo,
            "Versao": versao,
            "Status": "vigente" if matrizes.empty else "inativa",
            "Observacao": "Criada a partir das disciplinas cadastradas. Ajuste a ordem se preciso.",
        },
        pd.DataFrame(itens_linhas),
        matrizes=matrizes,
        todos_itens=carregar_matriz_itens(),
    )
    return erro, id_matriz


def duplicar_matriz(id_origem: str) -> tuple[str | None, str]:
    id_limpo = normalizar_id(id_origem)
    matrizes = carregar_matrizes()
    origem = matrizes[matrizes["ID_Matriz"].map(normalizar_id) == id_limpo]
    if origem.empty:
        return "Matriz de origem não encontrada.", ""
    itens = itens_da_matriz(id_limpo)
    if itens.empty:
        return "A matriz de origem não tem disciplinas.", ""
    novo_id = proximo_id(matrizes["ID_Matriz"], "MX")
    versao_origem = _int_ou_vazio(origem.iloc[0]["Versao"]) or 1
    nums = pd.to_numeric(matrizes["Versao"], errors="coerce")
    versao = int(nums.max()) + 1 if nums.notna().any() else versao_origem + 1
    nome_base = str(origem.iloc[0]["Nome"]).strip() or "Matriz"
    erro = salvar_matriz(
        {
            "ID_Matriz": novo_id,
            "Nome": f"{nome_base} (cópia)" if "(cópia)" not in nome_base.lower() else nome_base,
            "Versao": versao,
            "Status": "inativa",
            "Observacao": f"Cópia de {id_limpo}. Altere ordem, disciplinas ou quantidade.",
        },
        itens.assign(ID_Matriz=novo_id),
    )
    return erro, novo_id


# --- Carrosséis ---


def carregar_carrosseis() -> pd.DataFrame:
    df = _ler("Carrosseis", COLUNAS_CARROSSEIS)
    df["ID_Carrossel"] = df["ID_Carrossel"].map(normalizar_id)
    df["Nome"] = df["Nome"].astype(str).str.strip()
    df["ID_Matriz"] = df["ID_Matriz"].map(normalizar_id)
    df["Posicao_Inicio"] = pd.to_numeric(df["Posicao_Inicio"], errors="coerce")
    df["Status"] = df["Status"].map(lambda v: _status_lista(v, STATUS_CARROSSEL, "ativo"))
    df["Data_Inicio"] = _datas_para_editor(df["Data_Inicio"])
    return df


def carregar_carrossel_itens() -> pd.DataFrame:
    df = _ler("Carrossel_Itens", COLUNAS_CARROSSEL_ITENS)
    df["ID_Carrossel"] = df["ID_Carrossel"].map(normalizar_id)
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["Ordem"] = pd.to_numeric(df["Ordem"], errors="coerce")
    df = df[df["ID_Carrossel"].ne("") & df["ID_Disciplina"].ne("")]
    if not df.empty:
        df = df.sort_values(["ID_Carrossel", "Ordem"], na_position="last")
    return df.reset_index(drop=True)


def _ids_em_ordem(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty or "ID_Disciplina" not in df.columns:
        return []
    bloco = df.copy()
    if "Ordem" in bloco.columns:
        bloco = bloco.sort_values("Ordem", na_position="last")
    return [normalizar_id(x) for x in bloco["ID_Disciplina"] if normalizar_id(x)]


def _encontro_da_matriz(itens_matriz: pd.DataFrame, id_disc: str, ordem: int) -> str:
    id_limpo = normalizar_id(id_disc)
    if itens_matriz is not None and not itens_matriz.empty:
        match = itens_matriz[itens_matriz["ID_Disciplina"].map(normalizar_id) == id_limpo]
        if not match.empty:
            return _encontro(match.iloc[0]["Encontro_Presencial_Sugerido"])
    return encontro_sugerido_por_ordem(ordem)


def _montar_sequencia(
    linhas: pd.DataFrame,
    itens_matriz: pd.DataFrame,
    *,
    encontro_pela_posicao: bool,
) -> pd.DataFrame:
    if linhas is None or linhas.empty:
        return pd.DataFrame(columns=["Ordem", "ID_Disciplina", "Encontro_Presencial_Sugerido"])
    out = linhas.copy()
    out["ID_Disciplina"] = out["ID_Disciplina"].map(normalizar_id)
    out["Ordem"] = pd.to_numeric(out["Ordem"], errors="coerce")
    out = out[out["ID_Disciplina"].ne("")].sort_values("Ordem", na_position="last")
    out["Ordem"] = range(1, len(out) + 1)
    encontros = []
    for _, row in out.iterrows():
        ordem = int(row["Ordem"])
        if encontro_pela_posicao:
            encontros.append(encontro_sugerido_por_ordem(ordem))
        else:
            encontros.append(_encontro_da_matriz(itens_matriz, row["ID_Disciplina"], ordem))
    out["Encontro_Presencial_Sugerido"] = encontros
    return out[["Ordem", "ID_Disciplina", "Encontro_Presencial_Sugerido"]].reset_index(drop=True)


def validar_ordem_carrossel(id_matriz: str, ordem: pd.DataFrame) -> str | None:
    matriz = itens_da_matriz(id_matriz)
    ids_matriz = _ids_em_ordem(matriz)
    ids_ordem = _ids_em_ordem(ordem)
    if not ids_ordem:
        return "Informe a ordem das disciplinas desta volta."
    if len(ids_ordem) != len(set(ids_ordem)):
        return "Há disciplina repetida na ordem do carrossel."
    if set(ids_ordem) != set(ids_matriz):
        faltam = [i for i in ids_matriz if i not in ids_ordem]
        extra = [i for i in ids_ordem if i not in set(ids_matriz)]
        partes = [
            "A ordem do carrossel precisa ter as **mesmas** disciplinas da matriz."
        ]
        if faltam:
            partes.append("Faltam: " + ", ".join(faltam) + ".")
        if extra:
            partes.append("Não pertencem à matriz: " + ", ".join(extra) + ".")
        partes.append(
            "Se o conjunto for outro (ex.: 10 disciplinas vs 12), crie outra versão da matriz."
        )
        return " ".join(partes)
    return None


def sequencia_volta(
    id_carrossel: str = "",
    id_matriz: str = "",
    *,
    itens_carr: pd.DataFrame | None = None,
    itens_matriz: pd.DataFrame | None = None,
    carrosseis: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Ordem desta volta: itens próprios do carrossel, ou a ordem da matriz."""
    id_carr = normalizar_id(id_carrossel)
    id_mat = normalizar_id(id_matriz)
    if itens_carr is None:
        itens_carr = carregar_carrossel_itens()
    if not id_mat and id_carr:
        if carrosseis is None:
            carrosseis = carregar_carrosseis()
        match = carrosseis[carrosseis["ID_Carrossel"].map(normalizar_id) == id_carr]
        if not match.empty:
            id_mat = normalizar_id(match.iloc[0]["ID_Matriz"])
    if itens_matriz is None:
        itens_matriz = carregar_matriz_itens()
    matriz = itens_da_matriz(id_mat, itens_matriz) if id_mat else pd.DataFrame()
    custom = pd.DataFrame()
    if id_carr and itens_carr is not None and not itens_carr.empty:
        custom = itens_carr[itens_carr["ID_Carrossel"].map(normalizar_id) == id_carr]
    if not custom.empty:
        return _montar_sequencia(custom, matriz, encontro_pela_posicao=True)
    return _montar_sequencia(matriz, matriz, encontro_pela_posicao=False)


def carrossel_tem_ordem_propria(
    id_carrossel: str, itens_carr: pd.DataFrame | None = None
) -> bool:
    id_carr = normalizar_id(id_carrossel)
    if not id_carr:
        return False
    if itens_carr is None:
        itens_carr = carregar_carrossel_itens()
    if itens_carr is None or itens_carr.empty:
        return False
    return (itens_carr["ID_Carrossel"].map(normalizar_id) == id_carr).any()


def _gravar_ordem_carrossel(id_carrossel: str, ordem: pd.DataFrame | None) -> None:
    id_carr = normalizar_id(id_carrossel)
    todos = carregar_carrossel_itens()
    resto = todos[todos["ID_Carrossel"].map(normalizar_id) != id_carr]
    if ordem is None or ordem.empty:
        _gravar("Carrossel_Itens", resto, COLUNAS_CARROSSEL_ITENS)
        return
    bloco = ordem.copy()
    bloco["ID_Carrossel"] = id_carr
    bloco["ID_Disciplina"] = bloco["ID_Disciplina"].map(normalizar_id)
    bloco["Ordem"] = pd.to_numeric(bloco["Ordem"], errors="coerce")
    bloco = bloco[bloco["ID_Disciplina"].ne("")].sort_values("Ordem", na_position="last")
    bloco["Ordem"] = range(1, len(bloco) + 1)
    bloco = bloco[COLUNAS_CARROSSEL_ITENS]
    _gravar("Carrossel_Itens", pd.concat([resto, bloco], ignore_index=True), COLUNAS_CARROSSEL_ITENS)


def salvar_carrossel(linha: dict, ordem_disciplinas: pd.DataFrame | None = None) -> str | None:
    id_carr = normalizar_id(linha.get("ID_Carrossel", ""))
    id_matriz = normalizar_id(linha.get("ID_Matriz", ""))
    nome = str(linha.get("Nome", "")).strip()
    if not id_carr:
        return "Informe o código do carrossel."
    if not id_matriz:
        return "Selecione a matriz deste carrossel."
    matriz = itens_da_matriz(id_matriz)
    if matriz.empty:
        return "A matriz escolhida ainda não tem disciplinas."
    usar_custom = ordem_disciplinas is not None
    if usar_custom:
        erro_ord = validar_ordem_carrossel(id_matriz, ordem_disciplinas)
        if erro_ord:
            return erro_ord
        if _ids_em_ordem(ordem_disciplinas) == _ids_em_ordem(matriz):
            usar_custom = False
    seq = (
        _montar_sequencia(ordem_disciplinas, matriz, encontro_pela_posicao=True)
        if usar_custom
        else _montar_sequencia(matriz, matriz, encontro_pela_posicao=False)
    )
    posicao = pd.to_numeric(linha.get("Posicao_Inicio"), errors="coerce")
    if pd.isna(posicao) or int(posicao) < 1 or int(posicao) > len(seq):
        return "A posição de início precisa ser uma disciplina desta volta."
    posicao = int(posicao)
    if not nome:
        discs = carregar_disciplinas()
        id_disc = str(seq.iloc[posicao - 1]["ID_Disciplina"])
        nome_matriz = ""
        mats = carregar_matrizes()
        match = mats[mats["ID_Matriz"].map(normalizar_id) == id_matriz]
        if not match.empty:
            nome_matriz = str(match.iloc[0]["Nome"]).strip()
        nome = f"{nome_matriz or id_matriz} · início {nome_disciplina(discs, id_disc)}"
    nova = {
        "ID_Carrossel": id_carr,
        "Nome": nome,
        "ID_Matriz": id_matriz,
        "Posicao_Inicio": posicao,
        "Data_Inicio": _fmt_data(linha.get("Data_Inicio")),
        "Status": _status_lista(linha.get("Status"), STATUS_CARROSSEL, "ativo"),
    }
    df = carregar_carrosseis()
    resto = df[df["ID_Carrossel"].map(normalizar_id) != id_carr]
    df = pd.concat([resto, pd.DataFrame([nova])], ignore_index=True)
    df["Data_Inicio"] = df["Data_Inicio"].map(_fmt_data)
    _gravar("Carrosseis", df, COLUNAS_CARROSSEIS)
    _gravar_ordem_carrossel(id_carr, ordem_disciplinas if usar_custom else None)
    return None


def remover_carrossel(id_carrossel: str) -> str | None:
    id_limpo = normalizar_id(id_carrossel)
    turmas = carregar_turmas()
    if not turmas.empty and (turmas["ID_Carrossel"].map(normalizar_id) == id_limpo).any():
        return "Há turma neste carrossel. Remova ou mova a turma antes."
    ofertas = carregar_ofertas()
    if not ofertas.empty and (ofertas["ID_Carrossel"].map(normalizar_id) == id_limpo).any():
        return "Há oferta neste carrossel. Remova ou altere a oferta antes."
    df = carregar_carrosseis()
    df = df[df["ID_Carrossel"].map(normalizar_id) != id_limpo]
    df["Data_Inicio"] = df["Data_Inicio"].map(_fmt_data)
    _gravar("Carrosseis", df, COLUNAS_CARROSSEIS)
    _gravar_ordem_carrossel(id_limpo, None)
    return None


# --- Turmas ---


def carregar_turmas() -> pd.DataFrame:
    df = _ler("Turmas", COLUNAS_TURMAS)
    df["ID_Turma"] = df["ID_Turma"].map(normalizar_codigo_turma)
    df["ID_Carrossel"] = df["ID_Carrossel"].map(normalizar_id)
    df["Posicao_Entrada"] = pd.to_numeric(df["Posicao_Entrada"], errors="coerce")
    df["Status"] = df["Status"].map(lambda v: _status_lista(v, STATUS_TURMA, "ativo"))
    df["Observacao"] = df["Observacao"].astype(str).str.strip().replace({"nan": "", "None": ""})
    df = _deduplicar_turmas(df)
    if not df.empty:
        df = df.sort_values("ID_Turma", key=lambda s: s.map(_chave_turma))
    return df.reset_index(drop=True)


def _deduplicar_turmas(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    out["_k"] = out["ID_Turma"].map(normalizar_codigo_turma)
    if "Posicao_Entrada" in out.columns:
        out["_p"] = pd.to_numeric(out["Posicao_Entrada"], errors="coerce")
    else:
        out["_p"] = pd.NA
    out = out.sort_values(["_k", "_p"], na_position="first")
    out = out.drop_duplicates("_k", keep="last")
    return out.drop(columns=["_k", "_p"])


def _chave_turma(codigo: str) -> tuple:
    texto = normalizar_codigo_turma(codigo)
    if texto.startswith("T") and texto[1:].isdigit():
        return (0, int(texto[1:]), texto)
    return (1, 0, texto)


def _colunas_turma_alvo(nome_aba: str, df: pd.DataFrame) -> list[str]:
    """Não altera Config_Professores nem coluna Turma de sala — só ingresso/código."""
    cols = [c for c in df.columns if c in ("ID_Turma", "Turma_Ingresso")]
    if (
        nome_aba == "Base_Alunos"
        and "Turma_Ingresso" not in df.columns
        and "Turma" in df.columns
    ):
        cols.append("Turma")
    return cols


def _celula_turma_equivale(valor, alvo: str) -> bool:
    alvo_n = normalizar_codigo_turma(alvo)
    if not alvo_n:
        return False
    cru = str(valor or "").strip().upper().replace(" ", "")
    if cru in {"", "NAN", "NONE"}:
        return False
    if cru == str(alvo).strip().upper().replace(" ", ""):
        return True
    return normalizar_codigo_turma(valor) == alvo_n


def _aplicar_codigo_turma_df(
    df: pd.DataFrame, colunas: list[str], antigo: str, novo: str
) -> tuple[pd.DataFrame, int]:
    if df is None or df.empty or not colunas:
        return df, 0
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    trocas = 0
    for col in colunas:
        if col not in out.columns:
            continue
        novos = []
        mudou = 0
        for v in out[col]:
            orig = str(v or "").strip()
            if _celula_turma_equivale(v, antigo) and orig != novo:
                novos.append(novo)
                mudou += 1
            else:
                novos.append(v)
        if mudou:
            out[col] = novos
            trocas += mudou
    return out, trocas


def _padronizar_colunas_turma_df(df: pd.DataFrame, colunas: list[str]) -> tuple[pd.DataFrame, int]:
    if df is None or df.empty or not colunas:
        return df, 0
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    trocas = 0
    for col in colunas:
        if col not in out.columns:
            continue
        novos = []
        mudou = 0
        for v in out[col]:
            n = normalizar_codigo_turma(v)
            orig = str(v or "").strip()
            if n and orig and n != orig:
                novos.append(n)
                mudou += 1
            else:
                novos.append(v)
        if mudou:
            out[col] = novos
            trocas += mudou
    return out, trocas


def _gravar_abas_turma(
    antigo: str | None,
    novo: str | None,
    *,
    padronizar_tudo: bool,
    pular: set[str] | None = None,
) -> list[str]:
    avisos: list[str] = []
    ignorar = pular or set()
    for nome in _ABAS_CODIGO_TURMA:
        if nome in ignorar:
            continue
        try:
            df = ler_aba(nome)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        df.columns = [str(c).strip() for c in df.columns]
        colunas = _colunas_turma_alvo(nome, df)
        if padronizar_tudo:
            atualizado, n = _padronizar_colunas_turma_df(df, colunas)
        else:
            atualizado, n = _aplicar_codigo_turma_df(df, colunas, antigo or "", novo or "")
        extra = False
        if nome == "Turmas" and "ID_Turma" in atualizado.columns:
            antes = len(atualizado)
            atualizado["ID_Turma"] = atualizado["ID_Turma"].map(normalizar_codigo_turma)
            atualizado = _deduplicar_turmas(atualizado)
            extra = len(atualizado) < antes
        if n == 0 and not extra:
            continue
        try:
            salvar_aba(nome, atualizado, list(atualizado.columns))
            partes = []
            if n:
                partes.append(f"{n} célula(s)")
            if extra:
                partes.append("duplicatas unificadas")
            avisos.append(f"{nome}: {', '.join(partes)}")
            time.sleep(0.4)
        except Exception as exc:
            avisos.append(f"{nome}: não foi possível gravar ({exc})")
    return avisos


def propagar_codigo_turma(antigo: str, novo: str) -> list[str]:
    antigo_n = normalizar_codigo_turma(antigo) or str(antigo).strip()
    novo_n = normalizar_codigo_turma(novo)
    if not antigo_n or not novo_n or antigo_n == novo_n:
        return []
    return _gravar_abas_turma(antigo, novo_n, padronizar_tudo=False)


def padronizar_nomenclatura_turmas() -> list[str]:
    """T06-07/2024 e T6 passam a T06 em Turmas, Base_Alunos, Entrância e ofertas."""
    return _gravar_abas_turma(None, None, padronizar_tudo=True)


def salvar_turma(linha: dict, id_anterior: str = "") -> tuple[str | None, list[str]]:
    codigo = normalizar_codigo_turma(linha.get("ID_Turma", ""))
    id_carr = normalizar_id(linha.get("ID_Carrossel", ""))
    if not codigo:
        return "Informe o código da turma (ex.: T06).", []
    if not id_carr:
        return "Selecione o carrossel desta turma.", []
    carrosseis = carregar_carrosseis()
    carr = carrosseis[carrosseis["ID_Carrossel"].map(normalizar_id) == id_carr]
    if carr.empty:
        return "Carrossel não encontrado.", []
    itens = sequencia_volta(id_carr)
    posicao = pd.to_numeric(linha.get("Posicao_Entrada"), errors="coerce")
    if pd.isna(posicao) or int(posicao) < 1 or itens.empty or int(posicao) > len(itens):
        return "A posição de entrada precisa ser uma disciplina desta volta do carrossel.", []
    nova = {
        "ID_Turma": codigo,
        "ID_Carrossel": id_carr,
        "Posicao_Entrada": int(posicao),
        "Status": _status_lista(linha.get("Status"), STATUS_TURMA, "ativo"),
        "Observacao": str(linha.get("Observacao", "")).strip(),
    }
    df = carregar_turmas()
    ant = normalizar_codigo_turma(id_anterior) if id_anterior else ""
    excluir = {c for c in (codigo, ant) if c}
    resto = df[~df["ID_Turma"].map(normalizar_codigo_turma).isin(excluir)]
    df = pd.concat([resto, pd.DataFrame([nova])], ignore_index=True)
    df = _deduplicar_turmas(df)
    _gravar("Turmas", df, COLUNAS_TURMAS)
    origem = id_anterior if (ant and ant != codigo) else codigo
    avisos = _gravar_abas_turma(origem, codigo, padronizar_tudo=False, pular={"Turmas"})
    return None, avisos


def remover_turma(id_turma: str) -> str | None:
    codigo = normalizar_codigo_turma(id_turma)
    vinculos = carregar_oferta_turmas()
    if not vinculos.empty and (vinculos["ID_Turma"].map(normalizar_codigo_turma) == codigo).any():
        return "Esta turma está associada a uma oferta. Desassocie antes de remover."
    df = carregar_turmas()
    df = df[df["ID_Turma"].map(normalizar_codigo_turma) != codigo]
    _gravar("Turmas", df, COLUNAS_TURMAS)
    return None


def importar_turmas_da_base(id_carrossel: str = "") -> tuple[str | None, int]:
    alunos = carregar_alunos_base()
    if alunos.empty:
        return "Não há alunos na Base_Alunos para importar turmas.", 0
    existentes = set(carregar_turmas()["ID_Turma"].map(normalizar_codigo_turma))
    novas = []
    for codigo in sorted(alunos["Turma_Norm"].dropna().unique(), key=_chave_turma):
        codigo = normalizar_codigo_turma(codigo)
        if not codigo or codigo in existentes:
            continue
        novas.append(
            {
                "ID_Turma": codigo,
                "ID_Carrossel": normalizar_id(id_carrossel),
                "Posicao_Entrada": "",
                "Status": "ativo",
                "Observacao": "Importada da Base_Alunos. Defina a posição de entrada.",
            }
        )
        existentes.add(codigo)
    if not novas:
        return None, 0
    df = pd.concat([carregar_turmas(), pd.DataFrame(novas)], ignore_index=True)
    _gravar("Turmas", df, COLUNAS_TURMAS)
    return None, len(novas)


def trilha_turma(id_turma: str) -> list[dict]:
    turmas = carregar_turmas()
    codigo = normalizar_codigo_turma(id_turma)
    match = turmas[turmas["ID_Turma"].map(normalizar_codigo_turma) == codigo]
    if match.empty:
        return []
    return trilha_posicao(
        str(match.iloc[0]["ID_Carrossel"]),
        match.iloc[0]["Posicao_Entrada"],
    )


def trilha_posicao(id_carrossel: str, posicao_entrada) -> list[dict]:
    carrosseis = carregar_carrosseis()
    id_carr = normalizar_id(id_carrossel)
    carr = carrosseis[carrosseis["ID_Carrossel"].map(normalizar_id) == id_carr]
    if carr.empty:
        return []
    itens = sequencia_volta(id_carr)
    if itens.empty:
        return []
    posicao = pd.to_numeric(posicao_entrada, errors="coerce")
    if pd.isna(posicao):
        return []
    seq = itens.sort_values("Ordem").reset_index(drop=True)
    n = len(seq)
    start = (int(posicao) - 1) % n
    discs = carregar_disciplinas()
    saida = []
    for k in range(n):
        row = seq.iloc[(start + k) % n]
        id_disc = normalizar_id(row["ID_Disciplina"])
        saida.append(
            {
                "passo": k + 1,
                "ordem_matriz": int(row["Ordem"]) if pd.notna(row["Ordem"]) else k + 1,
                "ID_Disciplina": id_disc,
                "Nome": nome_disciplina(discs, id_disc),
                "Encontro_Presencial_Sugerido": _encontro(row["Encontro_Presencial_Sugerido"]),
            }
        )
    return saida


# --- Trimestres ---


def carregar_trimestres() -> pd.DataFrame:
    df = _ler("Trimestres", COLUNAS_TRIMESTRES)
    df["ID_Trimestre"] = df["ID_Trimestre"].map(normalizar_id)
    df["Ano"] = df["Ano"].map(_int_ou_vazio)
    df["Numero"] = df["Numero"].map(_int_ou_vazio)
    df["Nome"] = df["Nome"].astype(str).str.strip().replace({"nan": "", "None": ""})
    df["Status"] = df["Status"].map(lambda v: _status_lista(v, STATUS_TRIMESTRE, "Planejado"))
    df["Data_Inicio"] = _datas_para_editor(df["Data_Inicio"])
    df["Data_Fim"] = _datas_para_editor(df["Data_Fim"])
    if not df.empty:
        df = df.sort_values(["Ano", "Numero"], na_position="last")
    for idx, row in df.iterrows():
        if not normalizar_id(row.get("ID_Trimestre", "")):
            df.at[idx, "ID_Trimestre"] = codigo_trimestre(row.get("Ano"), row.get("Numero"))
        if not str(row.get("Nome", "")).strip():
            df.at[idx, "Nome"] = rotulo_trimestre(row.get("Ano"), row.get("Numero"))
    return df


def trimestre_por_id(id_trimestre: str, trimestres: pd.DataFrame | None = None) -> pd.Series | None:
    if trimestres is None:
        trimestres = carregar_trimestres()
    id_limpo = normalizar_id(id_trimestre).replace("/", "-")
    if trimestres.empty or not id_limpo:
        return None
    match = trimestres[trimestres["ID_Trimestre"].map(lambda v: normalizar_id(v).replace("/", "-")) == id_limpo]
    if match.empty:
        return None
    return match.iloc[0]


def salvar_trimestres(df: pd.DataFrame) -> str | None:
    df = _garantir_colunas(df, COLUNAS_TRIMESTRES)
    df["Ano"] = df["Ano"].map(_int_ou_vazio)
    df["Numero"] = df["Numero"].map(_int_ou_vazio)
    df = df[df["Ano"].astype(str).ne("") | df["Numero"].astype(str).ne("")]
    if df.empty:
        return "Informe ao menos um trimestre (ano e número 1 a 4)."
    for idx, row in df.iterrows():
        ano = row.get("Ano")
        num = row.get("Numero")
        if not ano or str(num) not in NUMEROS_TRIMESTRE:
            return "Cada trimestre precisa de ano e número de 1 a 4."
        df.at[idx, "ID_Trimestre"] = codigo_trimestre(ano, num)
        nome = str(row.get("Nome", "")).strip()
        df.at[idx, "Nome"] = nome or rotulo_trimestre(ano, num)
        df.at[idx, "Status"] = _status_lista(row.get("Status"), STATUS_TRIMESTRE, "Planejado")
        df.at[idx, "Data_Inicio"] = _fmt_data(row.get("Data_Inicio"))
        df.at[idx, "Data_Fim"] = _fmt_data(row.get("Data_Fim"))
    if df["ID_Trimestre"].duplicated().any():
        return "Há trimestre repetido (mesmo ano e número)."
    _gravar("Trimestres", df, COLUNAS_TRIMESTRES)
    return None


def gerar_trimestres_do_ano(ano: int) -> tuple[str | None, int]:
    ano = int(ano)
    atuais = carregar_trimestres()
    existentes = set(atuais["ID_Trimestre"].map(lambda v: normalizar_id(v).replace("/", "-")))
    novas = []
    for n in range(1, 5):
        codigo = codigo_trimestre(ano, n)
        if codigo in existentes:
            continue
        novas.append(
            {
                "ID_Trimestre": codigo,
                "Ano": ano,
                "Numero": n,
                "Nome": rotulo_trimestre(ano, n),
                "Data_Inicio": "",
                "Data_Fim": "",
                "Status": "Planejado",
            }
        )
    if not novas:
        return None, 0
    juntos = pd.concat([atuais, pd.DataFrame(novas)], ignore_index=True)
    juntos["Data_Inicio"] = juntos["Data_Inicio"].map(_fmt_data)
    juntos["Data_Fim"] = juntos["Data_Fim"].map(_fmt_data)
    erro = salvar_trimestres(juntos)
    return erro, len(novas)


# --- Ofertas ---


def carregar_ofertas() -> pd.DataFrame:
    df = _ler("Ofertas", COLUNAS_OFERTAS)
    df["ID_Oferta"] = df["ID_Oferta"].map(normalizar_id)
    df["ID_Carrossel"] = df["ID_Carrossel"].map(normalizar_id)
    df["ID_Matriz"] = df["ID_Matriz"].map(normalizar_id)
    df["ID_Disciplina"] = df["ID_Disciplina"].map(normalizar_id)
    df["ID_Trimestre"] = df["ID_Trimestre"].map(lambda v: normalizar_id(v).replace("/", "-"))
    df["Ano"] = df["Ano"].map(_int_ou_vazio)
    df["Trimestre"] = df["Trimestre"].map(lambda v: str(_int_ou_vazio(v) or "").strip())
    sem_tri = df["ID_Trimestre"].eq("") & df["Ano"].astype(str).ne("") & df["Trimestre"].ne("")
    df.loc[sem_tri, "ID_Trimestre"] = [
        codigo_trimestre(a, t) for a, t in zip(df.loc[sem_tri, "Ano"], df.loc[sem_tri, "Trimestre"])
    ]
    df["Tipo"] = df["Tipo"].map(lambda v: _status_lista(v, TIPO_OFERTA, "Regular"))
    df["Status"] = df["Status"].map(lambda v: _status_lista(v, STATUS_OFERTA, "Planejada"))
    df["Encontro_Presencial"] = df["Encontro_Presencial"].map(_encontro)
    df["Observacao"] = df["Observacao"].astype(str).str.strip().replace({"nan": "", "None": ""})
    df["Data_Prevista_Inicio"] = _datas_para_editor(df["Data_Prevista_Inicio"])
    df["Data_Prevista_Fim"] = _datas_para_editor(df["Data_Prevista_Fim"])
    return df


def carregar_oferta_turmas() -> pd.DataFrame:
    df = _ler("Oferta_Turmas", COLUNAS_OFERTA_TURMAS)
    df["ID_Oferta"] = df["ID_Oferta"].map(normalizar_id)
    df["ID_Turma"] = df["ID_Turma"].map(normalizar_codigo_turma)
    df = df[df["ID_Oferta"].ne("") & df["ID_Turma"].ne("")]
    return df.drop_duplicates(subset=["ID_Oferta", "ID_Turma"])


def carregar_excecoes() -> pd.DataFrame:
    df = _ler("Oferta_Excecoes", COLUNAS_EXCECOES)
    df["ID_Oferta"] = df["ID_Oferta"].map(normalizar_id)
    df["Email_Aluno"] = df["Email_Aluno"].astype(str).str.strip().str.lower()
    df["Nome_Aluno"] = df["Nome_Aluno"].astype(str).str.strip().replace({"nan": "", "None": ""})
    df["Tipo"] = df["Tipo"].map(lambda v: _status_lista(v, TIPO_EXCECAO, "Desvincular"))
    df["Motivo"] = df["Motivo"].astype(str).str.strip().replace({"nan": "", "None": ""})
    df = df[df["ID_Oferta"].ne("") & df["Email_Aluno"].ne("") & df["Email_Aluno"].ne("nan")]
    return df


def turmas_da_oferta(id_oferta: str, vinculos: pd.DataFrame | None = None) -> list[str]:
    if vinculos is None:
        vinculos = carregar_oferta_turmas()
    id_limpo = normalizar_id(id_oferta)
    if vinculos.empty:
        return []
    return sorted(
        vinculos[vinculos["ID_Oferta"].map(normalizar_id) == id_limpo]["ID_Turma"]
        .map(normalizar_codigo_turma)
        .tolist(),
        key=_chave_turma,
    )


def encontro_sugerido_oferta(id_carrossel: str, id_disciplina: str) -> str:
    carrosseis = carregar_carrosseis()
    id_carr = normalizar_id(id_carrossel)
    carr = carrosseis[carrosseis["ID_Carrossel"].map(normalizar_id) == id_carr]
    if carr.empty:
        return "Não"
    itens = sequencia_volta(id_carr)
    id_disc = normalizar_id(id_disciplina)
    match = itens[itens["ID_Disciplina"].map(normalizar_id) == id_disc]
    if match.empty:
        return "Não"
    return _encontro(match.iloc[0]["Encontro_Presencial_Sugerido"])


def id_oferta_sugerido(id_trimestre, id_disciplina: str, existentes=None) -> str:
    ano, num = parse_id_trimestre(id_trimestre)
    disc = normalizar_id(id_disciplina)
    base = f"{ano}T{num}-{disc}" if ano and num and disc else ""
    if not base:
        return proximo_id(existentes or [], "OF")
    usados = {normalizar_id(x) for x in (existentes or [])}
    if base not in usados:
        return base
    n = 2
    while f"{base}-{n}" in usados:
        n += 1
    return f"{base}-{n}"


def salvar_oferta(linha: dict, turmas: list[str]) -> str | None:
    id_oferta = normalizar_id(linha.get("ID_Oferta", ""))
    id_disc = normalizar_id(linha.get("ID_Disciplina", ""))
    tipo = _status_lista(linha.get("Tipo"), TIPO_OFERTA, "Regular")
    id_carr = normalizar_id(linha.get("ID_Carrossel", ""))
    if not id_disc:
        return "Selecione a disciplina da oferta."
    id_tri = normalizar_id(linha.get("ID_Trimestre", "")).replace("/", "-")
    if not id_tri:
        id_tri = codigo_trimestre(linha.get("Ano"), linha.get("Trimestre"))
    tri_row = trimestre_por_id(id_tri)
    if tri_row is None:
        return "Selecione um trimestre acadêmico cadastrado (ex.: 2026/1)."
    ano = _int_ou_vazio(tri_row["Ano"])
    trimestre = str(_int_ou_vazio(tri_row["Numero"]) or "").strip()
    data_ini = linha.get("Data_Prevista_Inicio") or tri_row.get("Data_Inicio")
    data_fim = linha.get("Data_Prevista_Fim") or tri_row.get("Data_Fim")
    id_matriz = ""
    if tipo == "Regular":
        if not id_carr:
            return "Oferta regular precisa de um carrossel."
        carrosseis = carregar_carrosseis()
        carr = carrosseis[carrosseis["ID_Carrossel"].map(normalizar_id) == id_carr]
        if carr.empty:
            return "Carrossel não encontrado."
        id_matriz = normalizar_id(carr.iloc[0]["ID_Matriz"])
        itens = sequencia_volta(id_carr, id_matriz)
        if not (itens["ID_Disciplina"].map(normalizar_id) == id_disc).any():
            return "A disciplina não pertence a esta volta do carrossel."
    else:
        if id_carr:
            carrosseis = carregar_carrosseis()
            carr = carrosseis[carrosseis["ID_Carrossel"].map(normalizar_id) == id_carr]
            if not carr.empty:
                id_matriz = normalizar_id(carr.iloc[0]["ID_Matriz"])
        if not id_matriz:
            id_matriz = normalizar_id(linha.get("ID_Matriz", ""))
    ofertas = carregar_ofertas()
    if not id_oferta:
        id_oferta = id_oferta_sugerido(id_tri, id_disc, ofertas["ID_Oferta"])
    nova = {
        "ID_Oferta": id_oferta,
        "ID_Carrossel": id_carr,
        "ID_Matriz": id_matriz,
        "ID_Disciplina": id_disc,
        "ID_Trimestre": id_tri,
        "Ano": ano,
        "Trimestre": trimestre,
        "Tipo": tipo,
        "Status": _status_lista(linha.get("Status"), STATUS_OFERTA, "Planejada"),
        "Data_Prevista_Inicio": _fmt_data(data_ini),
        "Data_Prevista_Fim": _fmt_data(data_fim),
        "Encontro_Presencial": _encontro(linha.get("Encontro_Presencial")),
        "Observacao": str(linha.get("Observacao", "")).strip(),
    }
    resto = ofertas[ofertas["ID_Oferta"].map(normalizar_id) != id_oferta]
    ofertas = pd.concat([resto, pd.DataFrame([nova])], ignore_index=True)
    ofertas["Data_Prevista_Inicio"] = ofertas["Data_Prevista_Inicio"].map(_fmt_data)
    ofertas["Data_Prevista_Fim"] = ofertas["Data_Prevista_Fim"].map(_fmt_data)

    vinculos = carregar_oferta_turmas()
    resto_v = vinculos[vinculos["ID_Oferta"].map(normalizar_id) != id_oferta]
    novos_v = pd.DataFrame(
        [
            {"ID_Oferta": id_oferta, "ID_Turma": normalizar_codigo_turma(t)}
            for t in turmas
            if normalizar_codigo_turma(t)
        ]
    )
    vinculos = pd.concat([resto_v, novos_v], ignore_index=True)

    _gravar("Ofertas", ofertas, COLUNAS_OFERTAS)
    _gravar("Oferta_Turmas", vinculos, COLUNAS_OFERTA_TURMAS)
    return None


def remover_oferta(id_oferta: str) -> str | None:
    id_limpo = normalizar_id(id_oferta)
    if not id_limpo:
        return "Oferta sem código."
    ofertas = carregar_ofertas()
    ofertas = ofertas[ofertas["ID_Oferta"].map(normalizar_id) != id_limpo]
    ofertas["Data_Prevista_Inicio"] = ofertas["Data_Prevista_Inicio"].map(_fmt_data)
    ofertas["Data_Prevista_Fim"] = ofertas["Data_Prevista_Fim"].map(_fmt_data)
    vinculos = carregar_oferta_turmas()
    vinculos = vinculos[vinculos["ID_Oferta"].map(normalizar_id) != id_limpo]
    excecoes = carregar_excecoes()
    excecoes = excecoes[excecoes["ID_Oferta"].map(normalizar_id) != id_limpo]
    _gravar("Ofertas", ofertas, COLUNAS_OFERTAS)
    _gravar("Oferta_Turmas", vinculos, COLUNAS_OFERTA_TURMAS)
    _gravar("Oferta_Excecoes", excecoes, COLUNAS_EXCECOES)
    return None


def salvar_excecao(linha: dict) -> str | None:
    id_oferta = normalizar_id(linha.get("ID_Oferta", ""))
    email = str(linha.get("Email_Aluno", "")).strip().lower()
    tipo = _status_lista(linha.get("Tipo"), TIPO_EXCECAO, "Desvincular")
    if not id_oferta or not email or "@" not in email:
        return "Informe a oferta e um e-mail válido."
    alunos = carregar_alunos_base()
    nome = str(linha.get("Nome_Aluno", "")).strip()
    if not nome and not alunos.empty:
        match = alunos[alunos["Email_Limpo"] == email]
        if not match.empty:
            nome = str(match.iloc[0]["Nome_Completo"]).strip()
    df = carregar_excecoes()
    mascara = (df["ID_Oferta"].map(normalizar_id) == id_oferta) & (df["Email_Aluno"] == email)
    df = df[~mascara]
    df = pd.concat(
        [
            df,
            pd.DataFrame(
                [
                    {
                        "ID_Oferta": id_oferta,
                        "Email_Aluno": email,
                        "Nome_Aluno": nome,
                        "Tipo": tipo,
                        "Motivo": str(linha.get("Motivo", "")).strip(),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    _gravar("Oferta_Excecoes", df, COLUNAS_EXCECOES)
    return None


def remover_excecao(id_oferta: str, email: str) -> None:
    id_limpo = normalizar_id(id_oferta)
    email_limpo = str(email).strip().lower()
    df = carregar_excecoes()
    df = df[
        ~((df["ID_Oferta"].map(normalizar_id) == id_limpo) & (df["Email_Aluno"] == email_limpo))
    ]
    _gravar("Oferta_Excecoes", df, COLUNAS_EXCECOES)


# --- Alunos / preview ---


def carregar_alunos_base() -> pd.DataFrame:
    try:
        df = ler_aba("Base_Alunos")
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    if "Email_Pessoal" not in out.columns or "Nome_Completo" not in out.columns:
        return pd.DataFrame()
    out["Email_Limpo"] = out["Email_Pessoal"].astype(str).str.strip().str.lower()
    out["Nome_Completo"] = out["Nome_Completo"].astype(str).str.strip()
    turma_col = "Turma_Ingresso" if "Turma_Ingresso" in out.columns else ""
    if not turma_col and "Turma" in out.columns:
        turma_col = "Turma"
    out["Turma_Norm"] = out[turma_col].map(normalizar_codigo_turma) if turma_col else ""
    if "Status_Geral" in out.columns:
        out["Status_Norm"] = out["Status_Geral"].astype(str).str.strip().str.lower()
    else:
        out["Status_Norm"] = "ativo"
    if "Perfil" in out.columns:
        perfil = out["Perfil"].astype(str).str.strip().str.lower()
        out = out[perfil.isin(["aluno", "aluna"])]
    out = out[out["Email_Limpo"].str.contains("@", na=False)]
    return out.reset_index(drop=True)


def alunos_ativos_da_turma(codigo_turma: str, alunos: pd.DataFrame | None = None) -> pd.DataFrame:
    if alunos is None:
        alunos = carregar_alunos_base()
    codigo = normalizar_codigo_turma(codigo_turma)
    if alunos.empty:
        return alunos
    return alunos[(alunos["Status_Norm"] == "ativo") & (alunos["Turma_Norm"] == codigo)].copy()


def resumo_participantes(id_oferta: str) -> dict:
    id_limpo = normalizar_id(id_oferta)
    alunos = carregar_alunos_base()
    turmas = turmas_da_oferta(id_limpo)
    excecoes = carregar_excecoes()
    excecoes = excecoes[excecoes["ID_Oferta"].map(normalizar_id) == id_limpo]
    excluir = set(excecoes[excecoes["Tipo"] == "Desvincular"]["Email_Aluno"])
    incluir = excecoes[excecoes["Tipo"] == "Incluir"]

    por_turma: dict[str, int] = {}
    linhas = []
    for codigo in turmas:
        grupo = alunos_ativos_da_turma(codigo, alunos)
        por_turma[codigo] = int(len(grupo))
        for _, row in grupo.iterrows():
            email = str(row["Email_Limpo"])
            if email in excluir:
                continue
            linhas.append(
                {
                    "Email_Aluno": email,
                    "Nome_Aluno": row["Nome_Completo"],
                    "Turma": codigo,
                    "Origem": f"Turma {codigo}",
                }
            )

    emails_ja = {l["Email_Aluno"] for l in linhas}
    for _, row in incluir.iterrows():
        email = str(row["Email_Aluno"]).strip().lower()
        if not email or email in emails_ja:
            continue
        nome = str(row["Nome_Aluno"]).strip()
        turma = ""
        match = alunos[alunos["Email_Limpo"] == email] if not alunos.empty else pd.DataFrame()
        if not match.empty:
            nome = nome or str(match.iloc[0]["Nome_Completo"]).strip()
            turma = str(match.iloc[0]["Turma_Norm"])
        linhas.append(
            {
                "Email_Aluno": email,
                "Nome_Aluno": nome,
                "Turma": turma,
                "Origem": "Inclusão pontual",
            }
        )
        emails_ja.add(email)

    df = pd.DataFrame(linhas)
    if not df.empty:
        df = df.sort_values(["Turma", "Nome_Aluno"], na_position="last").reset_index(drop=True)
    return {
        "total": len(df),
        "por_turma": por_turma,
        "incluidos": int(len(incluir)),
        "desvinculados": int(len(excluir)),
        "alunos": df,
        "excecoes": excecoes,
    }
