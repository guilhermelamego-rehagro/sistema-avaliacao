"""Helpers de UI para seleção de disciplina."""

import re

import pandas as pd

_CODIGO_COM_PERIODO = re.compile(r"^(\d{4})(\d)([A-Za-z].+)$")


def normalizar_id(valor) -> str:
    """Evita '1' != 1 e '1.0' != '1' ao cruzar planilhas."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = str(valor).strip()
    if texto.lower() in {"", "nan", "none"}:
        return ""
    if texto.endswith(".0"):
        base = texto[:-2]
        if base.isdigit():
            return base
    return texto


def indice_disciplina_ativa(df_disc: pd.DataFrame, lista_nomes: list[str]) -> int:
    if df_disc.empty or not lista_nomes:
        return 0
    ativas = df_disc[
        df_disc["Status"].astype(str).str.strip().str.lower().isin(["ativo", "ativa", "sim", "s"])
    ]
    if not ativas.empty:
        nome = ativas.iloc[0]["Nome_Disciplina"]
        if nome in lista_nomes:
            return lista_nomes.index(nome)
    return 0


def id_disciplina_por_nome(df_disc: pd.DataFrame, nome: str) -> str:
    return str(df_disc[df_disc["Nome_Disciplina"] == nome].iloc[0]["ID_Disciplina"]).strip()


def _nome_chave(valor) -> str:
    return re.sub(r"\s+", " ", str(valor or "").strip().lower())


def mapa_codigo_disciplina_legado(
    ids_atuais: dict[str, str],
    amostras: list[tuple[str, str]],
) -> dict[str, str]:
    """Mapeia código antigo (ex.: 20263TRI) para o atual (TRIB) por nome ou padrão ano+trimestre."""
    atuais = {normalizar_id(i): str(nome or "").strip() for i, nome in ids_atuais.items() if normalizar_id(i)}
    atuais_set = set(atuais)
    nome_para_id: dict[str, str] = {}
    for codigo, nome in atuais.items():
        chave = _nome_chave(nome)
        if chave:
            nome_para_id.setdefault(chave, codigo)

    mapa: dict[str, str] = {}
    for cru, nome in amostras:
        velho = normalizar_id(cru)
        if not velho or velho in atuais_set or velho in mapa:
            continue
        chave = _nome_chave(nome)
        if chave and chave in nome_para_id:
            mapa[velho] = nome_para_id[chave]
            continue
        match = _CODIGO_COM_PERIODO.match(velho)
        if not match:
            continue
        raiz = match.group(3).upper()
        cands = [a for a in atuais_set if a.upper() == raiz or a.upper().startswith(raiz)]
        if len(cands) == 1:
            mapa[velho] = cands[0]
        elif cands:
            mapa[velho] = max(cands, key=len)
    return mapa
