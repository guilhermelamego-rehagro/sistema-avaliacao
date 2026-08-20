"""Feriados nacionais, de Belo Horizonte e recessos cadastrados."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from data.sheets import garantir_aba_frequencia, ler_aba_frequencia, salvar_aba_frequencia
from utils.datas import parse_data_planilha, parse_data_planilha_series

COLUNAS_INSTITUCIONAL = ["Data", "Tipo", "Nome", "Origem", "Ativo"]
ABA_INSTITUCIONAL = "Calendario_Institucional"

TIPO_FERIADO = "Feriado"
TIPO_RECESSO = "Recesso"
ORIGEM_NACIONAL = "Nacional"
ORIGEM_BH = "BH"
ORIGEM_SINDICATO = "Sindicato"
ORIGEM_MANUAL = "Manual"


def _pascoa(ano: int) -> date:
    """Algoritmo de Meeus/Jones/Butcher (calendário gregoriano)."""
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def feriados_oficiais(ano: int) -> list[tuple[date, str, str]]:
    """(data, nome, origem) — nacionais + municipais de Belo Horizonte."""
    pascoa = _pascoa(ano)
    sexta_santa = pascoa - timedelta(days=2)
    corpus = pascoa + timedelta(days=60)
    itens: list[tuple[date, str, str]] = [
        (date(ano, 1, 1), "Confraternização Universal", ORIGEM_NACIONAL),
        (sexta_santa, "Sexta-feira Santa", ORIGEM_NACIONAL),
        (date(ano, 4, 21), "Tiradentes", ORIGEM_NACIONAL),
        (date(ano, 5, 1), "Dia do Trabalho", ORIGEM_NACIONAL),
        (corpus, "Corpus Christi", ORIGEM_NACIONAL),
        (date(ano, 9, 7), "Independência do Brasil", ORIGEM_NACIONAL),
        (date(ano, 10, 12), "Nossa Senhora Aparecida", ORIGEM_NACIONAL),
        (date(ano, 11, 2), "Finados", ORIGEM_NACIONAL),
        (date(ano, 11, 15), "Proclamação da República", ORIGEM_NACIONAL),
        (date(ano, 11, 20), "Dia da Consciência Negra", ORIGEM_NACIONAL),
        (date(ano, 12, 25), "Natal", ORIGEM_NACIONAL),
        (date(ano, 8, 15), "Nossa Senhora da Boa Viagem (BH)", ORIGEM_BH),
        (date(ano, 12, 8), "Imaculada Conceição (BH)", ORIGEM_BH),
    ]
    return itens


def _fmt(valor) -> str:
    parsed = parse_data_planilha(valor)
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).strftime("%d/%m/%Y")


def _ativo(valor) -> bool:
    return str(valor or "Sim").strip().lower() in {"sim", "s", "1", "true", "ativo"}


META_ORIGEM = "Sistema"
META_NOME = "lista_inicializada"


def _sem_meta(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    meta = (df["Origem"].astype(str).str.strip() == META_ORIGEM) & (
        df["Nome"].astype(str).str.strip() == META_NOME
    )
    return df.loc[~meta].copy()


def _com_meta(df: pd.DataFrame) -> pd.DataFrame:
    extra = pd.DataFrame(
        [
            {
                "Data": "01/01/2000",
                "Tipo": TIPO_FERIADO,
                "Nome": META_NOME,
                "Origem": META_ORIGEM,
                "Ativo": "Sim",
            }
        ]
    )
    visivel = _sem_meta(df) if df is not None else extra.iloc[0:0]
    return pd.concat([visivel, extra], ignore_index=True)


def carregar_institucional() -> pd.DataFrame:
    garantir_aba_frequencia(ABA_INSTITUCIONAL)
    try:
        df = ler_aba_frequencia(ABA_INSTITUCIONAL)
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        out = pd.DataFrame(columns=COLUNAS_INSTITUCIONAL)
    else:
        out = df.copy()
        out.columns = [str(c).strip() for c in out.columns]
        for col in COLUNAS_INSTITUCIONAL:
            if col not in out.columns:
                out[col] = ""
        out = out[COLUNAS_INSTITUCIONAL]
    out["Data"] = out["Data"].map(_fmt)
    out["Tipo"] = out["Tipo"].astype(str).str.strip()
    out["Nome"] = out["Nome"].astype(str).str.strip().replace("nan", "")
    out["Origem"] = out["Origem"].astype(str).str.strip().replace("nan", "")
    out["Ativo"] = out["Ativo"].map(lambda v: "Sim" if _ativo(v) else "Não")
    return out


def _ordenar(df: pd.DataFrame) -> pd.DataFrame:
    visivel = _sem_meta(df)
    if visivel.empty:
        return visivel
    parsed = parse_data_planilha_series(visivel["Data"])
    return visivel.assign(_ord=parsed).sort_values(["_ord", "Tipo", "Nome"], na_position="last").drop(
        columns=["_ord"]
    )


def lista_institucional() -> pd.DataFrame:
    """Linhas visíveis (sem o marcador interno), ordenadas por data."""
    return _ordenar(carregar_institucional()).reset_index(drop=True)


def garantir_lista_inicial(anos: list[int] | None = None) -> pd.DataFrame:
    """Se a lista nunca foi gravada, importa oficiais. Lista vazia depois de editar permanece vazia."""
    df = carregar_institucional()
    visivel = _sem_meta(df)
    ja_inicializada = (not visivel.empty) and (len(df) > len(visivel) if df is not None else False)
    if visivel is None:
        visivel = pd.DataFrame(columns=COLUNAS_INSTITUCIONAL)
    if visivel.empty and not ja_inicializada:
        hoje = date.today()
        anos = anos or [hoje.year - 1, hoje.year, hoje.year + 1]
        aplicar_importacao_oficial(anos)
    elif not ja_inicializada and visivel is not None and not visivel.empty:
        salvar_institucional(visivel)
    return lista_institucional()


FONTE_OFICIAL = (
    "As datas oficiais ficam no próprio sistema: feriados nacionais da legislação "
    "federal (incluindo Sexta-feira Santa e Corpus Christi, calculados pela Páscoa), "
    "Dia da Consciência Negra e os municipais de Belo Horizonte "
    "(15/08 Nossa Senhora da Boa Viagem e 08/12 Imaculada Conceição). "
    "Não há consulta à internet. A lista só muda se a lei mudar e atualizarmos o app."
)


def prever_importacao_oficial(anos: list[int]) -> dict:
    """Compara a lista gravada com as datas oficiais do período."""
    anos = sorted({int(a) for a in anos})
    lista = lista_institucional()
    existentes: dict[tuple[str, str], str] = {}
    if not lista.empty:
        feriados = lista[lista["Tipo"].astype(str).str.strip() == TIPO_FERIADO]
        for _, row in feriados.iterrows():
            origem = str(row.get("Origem", "")).strip()
            if origem not in {ORIGEM_NACIONAL, ORIGEM_BH}:
                continue
            existentes[(_fmt(row["Data"]), origem)] = str(row.get("Nome", "")).strip()

    incluir: list[dict] = []
    restaurar_nome: list[dict] = []
    iguais = 0
    oficiais: list[tuple[date, str, str]] = []
    for ano in anos:
        oficiais.extend(feriados_oficiais(ano))

    for dia, nome, origem in oficiais:
        chave = (_fmt(dia), origem)
        atual = existentes.get(chave)
        item = {"Data": chave[0], "Nome": nome, "Origem": origem}
        if atual is None:
            incluir.append(item)
        elif atual != nome:
            restaurar_nome.append({**item, "Nome_atual": atual})
        else:
            iguais += 1

    recessos = 0
    extras = 0
    if not lista.empty:
        anos_linha = parsed.map(lambda x: int(x.year) if pd.notna(x) else -1)
        no_periodo = lista[anos_linha.isin(anos)]
        recessos = int((no_periodo["Tipo"].astype(str).str.strip() == TIPO_RECESSO).sum())
        extras = int(
            (
                (no_periodo["Tipo"].astype(str).str.strip() == TIPO_FERIADO)
                & (~no_periodo["Origem"].astype(str).str.strip().isin([ORIGEM_NACIONAL, ORIGEM_BH]))
            ).sum()
        )

    return {
        "anos": anos,
        "incluir": incluir,
        "restaurar_nome": restaurar_nome,
        "iguais": iguais,
        "recessos": recessos,
        "extras": extras,
        "alterou_periodo": bool(incluir or restaurar_nome or recessos or extras),
        "sobrescreve": bool(incluir or restaurar_nome),
    }


def aplicar_importacao_oficial(anos: list[int], *, restaurar_nomes: bool = False) -> dict:
    """Inclui oficiais que faltam. Só reescreve nomes se restaurar_nomes=True."""
    preview = prever_importacao_oficial(anos)
    base = carregar_institucional()
    linhas_novas = []
    for item in preview["incluir"]:
        linhas_novas.append(
            {
                "Data": item["Data"],
                "Tipo": TIPO_FERIADO,
                "Nome": item["Nome"],
                "Origem": item["Origem"],
                "Ativo": "Sim",
            }
        )
    if linhas_novas:
        base = pd.concat([base, pd.DataFrame(linhas_novas)], ignore_index=True)
    if restaurar_nomes:
        for item in preview["restaurar_nome"]:
            mask = (
                (base["Data"] == item["Data"])
                & (base["Origem"].astype(str).str.strip() == item["Origem"])
                & (base["Tipo"] == TIPO_FERIADO)
            )
            base.loc[mask, "Nome"] = item["Nome"]
    visivel = _ordenar(base)
    salvar_aba_frequencia(ABA_INSTITUCIONAL, _com_meta(visivel), COLUNAS_INSTITUCIONAL)
    return {
        "incluidos": len(linhas_novas),
        "nomes": len(preview["restaurar_nome"]) if restaurar_nomes else 0,
    }


def salvar_institucional(df: pd.DataFrame) -> str | None:
    out = df.copy() if df is not None else pd.DataFrame(columns=COLUNAS_INSTITUCIONAL)
    for col in COLUNAS_INSTITUCIONAL:
        if col not in out.columns:
            out[col] = ""
    out["Data"] = out["Data"].map(_fmt)
    out["Tipo"] = out["Tipo"].astype(str).str.strip()
    out["Nome"] = out["Nome"].astype(str).str.strip()
    out["Origem"] = out["Origem"].astype(str).str.strip()
    out["Ativo"] = out["Ativo"].map(lambda v: "Sim" if _ativo(v) else "Não")
    out = out[out["Data"].ne("") | out["Nome"].ne("")]
    if out["Data"].eq("").any() or out["Nome"].eq("").any():
        return "Cada linha precisa de data e nome."
    tipos_ok = {TIPO_FERIADO.lower(), TIPO_RECESSO.lower()}
    if out["Tipo"].str.lower().map(lambda t: t not in tipos_ok).any():
        return "Tipo deve ser Feriado ou Recesso."
    out["Tipo"] = out["Tipo"].map(
        lambda t: TIPO_RECESSO if str(t).strip().lower() == TIPO_RECESSO.lower() else TIPO_FERIADO
    )
    out.loc[out["Origem"].eq(""), "Origem"] = ORIGEM_MANUAL
    visivel = _ordenar(out)
    salvar_aba_frequencia(ABA_INSTITUCIONAL, _com_meta(visivel), COLUNAS_INSTITUCIONAL)
    return None


def adicionar_institucional(
    dia: date,
    tipo: str,
    nome: str,
    origem: str = ORIGEM_MANUAL,
) -> str | None:
    if dia is None or not str(nome or "").strip():
        return "Informe data e nome."
    tipo_ok = TIPO_RECESSO if str(tipo).strip().lower() == TIPO_RECESSO.lower() else TIPO_FERIADO
    origem_ok = str(origem or ORIGEM_MANUAL).strip() or ORIGEM_MANUAL
    base = lista_institucional()
    nova = pd.DataFrame(
        [
            {
                "Data": _fmt(dia),
                "Tipo": tipo_ok,
                "Nome": str(nome).strip(),
                "Origem": origem_ok,
                "Ativo": "Sim",
            }
        ]
    )
    return salvar_institucional(pd.concat([base, nova], ignore_index=True))


def remover_institucional(data_txt: str, tipo: str, nome: str, origem: str) -> str | None:
    base = lista_institucional()
    if base.empty:
        return None
    mask = (
        (base["Data"].astype(str).str.strip() == str(data_txt).strip())
        & (base["Tipo"].astype(str).str.strip() == str(tipo).strip())
        & (base["Nome"].astype(str).str.strip() == str(nome).strip())
        & (base["Origem"].astype(str).str.strip() == str(origem).strip())
    )
    return salvar_institucional(base.loc[~mask].copy())


def datas_bloqueio(anos: list[int] | None = None) -> dict[date, list[tuple[str, str]]]:
    """Só o que está na lista gravada (feriado/recesso ativos). Excluir da lista tira do calendário."""
    if not anos:
        anos = [date.today().year]
    garantir_lista_inicial(anos)
    agrupado: dict[date, list[tuple[str, str]]] = {}
    df = lista_institucional()
    if df.empty:
        return agrupado
    ativos = df[df["Ativo"] == "Sim"]
    for _, row in ativos.iterrows():
        parsed = parse_data_planilha(row["Data"])
        if pd.isna(parsed):
            continue
        dia = pd.Timestamp(parsed).date()
        if dia.year not in anos:
            continue
        tipo = str(row["Tipo"]).strip() or TIPO_FERIADO
        nome = str(row["Nome"]).strip() or tipo
        lista = agrupado.setdefault(dia, [])
        if (tipo, nome) not in lista:
            lista.append((tipo, nome))
    return agrupado


def conjunto_datas_sem_aula(anos: list[int] | None = None) -> set[date]:
    return set(datas_bloqueio(anos).keys())


def eh_dia_util(dia: date, bloqueios: set[date] | None = None) -> bool:
    if dia.weekday() >= 5:
        return False
    return dia not in (bloqueios or set())


def dia_util_anterior(dia: date, bloqueios: set[date] | None = None) -> date:
    atual = dia - timedelta(days=1)
    trava = 0
    while not eh_dia_util(atual, bloqueios):
        atual -= timedelta(days=1)
        trava += 1
        if trava > 60:
            return atual
    return atual


def n_dias_uteis_depois(dia: date, n: int, bloqueios: set[date] | None = None) -> date:
    atual = dia
    feitos = 0
    trava = 0
    while feitos < max(int(n), 0):
        atual += timedelta(days=1)
        trava += 1
        if eh_dia_util(atual, bloqueios):
            feitos += 1
        if trava > 60:
            break
    return atual
