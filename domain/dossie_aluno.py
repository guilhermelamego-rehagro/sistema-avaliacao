"""Dossiê individual do aluno por ciclo — base para as conversas de feedback.

Junta presença, pares, orientador, banca, dailies e atividades, sem IA.
Uso interno docente: traz anotações de daily, que nunca são expostas ao aluno.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.ciclos import hoje_normalizado, preparar_ciclos
from utils.datas import parse_data_planilha_series
from utils.disciplina import normalizar_id
from utils.ordenacao import chave_ordenacao_grupo, chave_ordenacao_texto, ordenar_grupos_lista

LIMIAR_PRESENCA = 75.0

CITA_SIM = "sim"
CITA_AMBIGUA = "ambígua"
CITA_NAO = "não"

_RE_COMENTARIO_AUTOMATICO = re.compile(r"(lancamento|conferencia) coordenador")

_PARTICULAS = {
    "de", "da", "do", "das", "dos", "e", "di", "du", "del", "della", "van", "von",
    "jr", "junior", "filho", "filha", "neto", "neta", "sobrinho",
}


# --- Citação do aluno nas anotações de daily (feitas por grupo) ---


def _sem_acento(texto) -> str:
    base = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in base if not unicodedata.combining(c)).lower()


def _tokens_nome(nome) -> list[str]:
    return [
        t for t in re.findall(r"[a-z]+", _sem_acento(nome)) if len(t) >= 3 and t not in _PARTICULAS
    ]


def tokens_identificadores(nomes: dict[str, str]) -> dict[str, tuple[set[str], str]]:
    """Por aluno do grupo: partes do nome que só ele tem no grupo, e o primeiro nome."""
    tokens = {email: _tokens_nome(nome) for email, nome in nomes.items()}
    contagem = Counter(t for lista in tokens.values() for t in set(lista))
    return {
        email: ({t for t in lista if contagem[t] == 1}, lista[0] if lista else "")
        for email, lista in tokens.items()
    }


def _contem(texto_norm: str, token: str) -> bool:
    return bool(token) and re.search(rf"\b{re.escape(token)}\b", texto_norm) is not None


def citacao(texto, identificadores: tuple[set[str], str]) -> str:
    """Primeiro nome repetido no grupo, sem outra parte do nome, conta como ambígua."""
    unicos, primeiro = identificadores
    norm = _sem_acento(texto)
    if any(_contem(norm, t) for t in unicos):
        return CITA_SIM
    if _contem(norm, primeiro):
        return CITA_AMBIGUA
    return CITA_NAO


def trechos_citacao(texto, identificadores: tuple[set[str], str], limite: int = 300) -> list[str]:
    unicos, primeiro = identificadores
    alvos = unicos | ({primeiro} if primeiro else set())
    saida = []
    for frase in re.split(r"(?<=[.!?;])\s+|\n+", str(texto or "")):
        frase = frase.strip()
        if frase and any(_contem(_sem_acento(frase), t) for t in alvos):
            saida.append(frase if len(frase) <= limite else frase[:limite].rstrip() + "…")
    return saida


# --- Formatação ---


def fmt_num(valor, casas: int = 1) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    return f"{float(valor):.{casas}f}".replace(".", ",")


def fmt_pct(valor) -> str:
    return "—" if valor is None else f"{fmt_num(valor, 0)}%"


def _fmt_data(ts) -> str:
    return "" if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime("%d/%m")


def _media(valores) -> float | None:
    nums = [float(v) for v in valores if v is not None and not pd.isna(v)]
    return sum(nums) / len(nums) if nums else None


def _ts(valor) -> pd.Timestamp | None:
    return None if valor is None or pd.isna(valor) else pd.Timestamp(valor).normalize()


# --- Contexto do ciclo (carregado uma vez por tela) ---


@dataclass
class ContextoCiclo:
    id_disciplina: str
    id_ciclo: str
    nome_ciclo: str
    inicio: pd.Timestamp | None
    fim: pd.Timestamp | None
    pares_inicio: pd.Timestamp | None
    pares_fim: pd.Timestamp | None
    alunos: pd.DataFrame
    aulas: pd.DataFrame
    dailies: pd.DataFrame
    pares: pd.DataFrame
    liberacoes: pd.DataFrame
    notas_orientador: dict[str, float]
    anotacoes: pd.DataFrame
    atividades: pd.DataFrame
    banca: dict[tuple[str, str], dict] = field(default_factory=dict)


def _alunos_disciplina(id_disciplina: str) -> pd.DataFrame:
    from domain.filtros_operacionais import filtrar_entrancia_operacional

    df = ler_aba("Entrancia_Turma")
    if df.empty:
        return pd.DataFrame(columns=["Email", "Nome", "Sala", "Grupo"])
    df = df[df["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disciplina)]
    df = filtrar_entrancia_operacional(df, id_disciplina, exigir_grupo=True)
    out = pd.DataFrame(
        {
            "Email": df["Email_Pessoal"].astype(str).str.strip().str.lower(),
            "Nome": df["Nome_Completo"].astype(str).str.strip(),
            "Sala": df["Sala"].astype(str).str.strip(),
            "Grupo": df["Grupo"].astype(str).str.strip(),
        }
    )
    vazio = {"", "nan", "none", "—", "–", "-"}
    out = out[out["Email"].ne("") & ~out["Grupo"].str.lower().isin(vazio)]
    out["Sala"] = out["Sala"].where(~out["Sala"].str.lower().isin(vazio), "")
    return out.drop_duplicates("Email").sort_values("Nome").reset_index(drop=True)


@st.cache_data(ttl=900, show_spinner=False)
def _matrizes_presenca(id_disciplina: str, emails: tuple[str, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    from domain.presenca import carregar_base_presenca, matriz_dailies_turma, matriz_frequencia_turma

    alunos = pd.DataFrame({"Email_Pessoal": list(emails)})
    cache = carregar_base_presenca()
    colunas = ["Email_Limpo", "Data", "Status_Tecnico", "Status_Aluno"]

    def _enxuta(m: pd.DataFrame) -> pd.DataFrame:
        if m is None or m.empty:
            return pd.DataFrame(columns=colunas)
        return m[colunas].copy()

    return (
        _enxuta(matriz_frequencia_turma(id_disciplina, alunos, cache)),
        _enxuta(matriz_dailies_turma(id_disciplina, alunos, cache)),
    )


def _no_periodo(datas: pd.Series, inicio, fim) -> pd.Series:
    mask = datas.notna()
    if inicio is not None:
        mask &= datas >= inicio
    if fim is not None:
        mask &= datas <= fim
    return mask


def _vividas_no_periodo(matriz: pd.DataFrame, inicio, fim) -> pd.DataFrame:
    if matriz.empty:
        return matriz
    m = matriz.copy()
    m["Data"] = pd.to_datetime(m["Data"], errors="coerce").dt.normalize()
    m = m[~m["Status_Tecnico"].isin(["Futuro", "Erro"])]
    return m[_no_periodo(m["Data"], inicio, fim)].sort_values("Data")


def carregar_contexto(id_disciplina: str, ciclo: pd.Series, *, usuario: dict) -> ContextoCiclo:
    from domain.anotacoes_daily import carregar_anotacoes
    from domain.atividades_notas import notas_efetivas
    from domain.avaliacoes import carregar_mapa_notas_orientador
    from domain.liberacoes_pares import carregar_liberacoes
    from domain.pares import carregar_avaliacoes_pares

    id_d = normalizar_id(id_disciplina)
    linha = preparar_ciclos(ciclo.to_frame().T).iloc[0]
    id_c = normalizar_id(linha.get("ID_Ciclo"))
    inicio = _ts(linha.get("Data_Inicio_Ciclo"))
    fim = _ts(linha.get("Data_Apresentacao"))
    if inicio is not None and fim is not None and inicio > fim:
        inicio, fim = fim, inicio

    alunos = _alunos_disciplina(id_d)
    aulas, dailies = _matrizes_presenca(id_d, tuple(alunos["Email"]))

    pares = carregar_avaliacoes_pares()
    if not pares.empty:
        pares = pares[pares["ID_Ciclo"].map(normalizar_id) == id_c]

    liberacoes = carregar_liberacoes()
    if not liberacoes.empty:
        liberacoes = liberacoes[liberacoes["ID_Ciclo"] == id_c]

    notas_or = {
        email: nota
        for (email, ciclo_id), nota in carregar_mapa_notas_orientador(id_d).items()
        if normalizar_id(ciclo_id) == id_c
    }

    anot = carregar_anotacoes(usuario=usuario)
    if not anot.empty:
        anot = anot[anot["ID_Disciplina"] == id_d].copy()
        anot["_data"] = parse_data_planilha_series(anot["Data"]).dt.normalize()
        do_ciclo = anot["ID_Ciclo"] == id_c
        if inicio is not None or fim is not None:
            do_ciclo |= _no_periodo(anot["_data"], inicio, fim)
        anot = anot[do_ciclo].sort_values("_data")

    ativ = notas_efetivas(id_d)
    if not ativ.empty:
        ativ = ativ.copy()
        ativ["_prazo"] = pd.to_datetime(ativ["Prazo"], format="%d/%m/%Y", errors="coerce")
        if inicio is not None or fim is not None:
            ativ = ativ[_no_periodo(ativ["_prazo"], inicio, fim)]

    ctx = ContextoCiclo(
        id_disciplina=id_d,
        id_ciclo=id_c,
        nome_ciclo=str(linha.get("Nome_Ciclo", "")).strip() or id_c,
        inicio=inicio,
        fim=fim,
        pares_inicio=_ts(linha.get("Data início")),
        pares_fim=_ts(linha.get("Data fim")),
        alunos=alunos,
        aulas=_vividas_no_periodo(aulas, inicio, fim),
        dailies=_vividas_no_periodo(dailies, inicio, fim),
        pares=pares,
        liberacoes=liberacoes,
        notas_orientador=notas_or,
        anotacoes=anot,
        atividades=ativ,
    )
    ctx.banca = _carregar_banca(ctx)
    return ctx


def _carregar_banca(ctx: ContextoCiclo) -> dict[tuple[str, str], dict]:
    from domain.avaliacoes import listar_comentarios_banca_grupo, obter_media_avaliacao_grupo

    saida: dict[tuple[str, str], dict] = {}
    for (sala, grupo), _ in ctx.alunos.groupby(["Sala", "Grupo"], sort=False):
        oficial = obter_media_avaliacao_grupo(ctx.id_ciclo, grupo, id_disciplina=ctx.id_disciplina)
        comentarios = [
            {"avaliador": c["nome_avaliador"], "texto": c["comentario"]}
            for c in listar_comentarios_banca_grupo(ctx.id_disciplina, grupo, sala)
            if normalizar_id(c["id_ciclo"]) == ctx.id_ciclo
            and c["comentario"]
            and not _RE_COMENTARIO_AUTOMATICO.match(_sem_acento(c["comentario"]))
        ]
        if oficial or comentarios:
            saida[(sala, grupo)] = {"oficial": oficial, "comentarios": comentarios}
    return saida


# --- Indicadores por aluno ---


def _membros(ctx: ContextoCiclo, sala: str, grupo: str) -> pd.DataFrame:
    a = ctx.alunos
    return a[(a["Sala"] == sala) & (a["Grupo"] == grupo)]


def _anotacoes_grupo(ctx: ContextoCiclo, sala: str, grupo: str) -> pd.DataFrame:
    a = ctx.anotacoes
    if a.empty:
        return a
    return a[(a["Grupo"] == grupo) & (a["Sala"].isin([sala, ""]))]


def _resumo_presenca(matriz: pd.DataFrame, email: str) -> dict:
    from domain.presenca import sequencia_faltas

    m = matriz[matriz["Email_Limpo"] == email] if not matriz.empty else matriz
    total = len(m)
    if not total:
        return {"total": 0, "presencas": 0, "faltas": 0, "pct": None, "seq_max": 0, "datas_falta": []}
    presencas = int((m["Status_Aluno"] == "Presente").sum())
    falta = m["Status_Aluno"] == "Falta"
    return {
        "total": total,
        "presencas": presencas,
        "faltas": int(falta.sum()),
        "pct": presencas / total * 100,
        "seq_max": sequencia_faltas(m["Status_Aluno"])[1],
        "datas_falta": [_fmt_data(d) for d in m.loc[falta, "Data"]],
    }


def _citacoes_grupo(ctx: ContextoCiclo, sala: str, grupo: str) -> dict[str, list[dict]]:
    """Por aluno do grupo: uma entrada por anotação do ciclo, com citação e trechos."""
    membros = _membros(ctx, sala, grupo)
    ids = tokens_identificadores(dict(zip(membros["Email"], membros["Nome"])))
    saida: dict[str, list[dict]] = {email: [] for email in ids}
    for _, anot in _anotacoes_grupo(ctx, sala, grupo).iterrows():
        for email, ident in ids.items():
            saida[email].append(
                {
                    "data": anot["_data"],
                    "texto": anot["Texto"],
                    "autor": anot.get("Nome_Orientador") or anot.get("Email_Orientador") or "",
                    "citacao": citacao(anot["Texto"], ident),
                    "trechos": trechos_citacao(anot["Texto"], ident),
                }
            )
    return saida


def resumo_alunos(ctx: ContextoCiclo) -> pd.DataFrame:
    """Uma linha por aluno com os indicadores do ciclo (base das médias de grupo/turma)."""
    pares = ctx.pares
    ativ = ctx.atividades
    linhas = []
    for (sala, grupo), membros in ctx.alunos.groupby(["Sala", "Grupo"], sort=False):
        citacoes = _citacoes_grupo(ctx, sala, grupo)
        for _, aluno in membros.iterrows():
            email = aluno["Email"]
            aulas = _resumo_presenca(ctx.aulas, email)
            dailies = _resumo_presenca(ctx.dailies, email)
            recebidas = pares[pares["Email_Avaliado"] == email] if not pares.empty else pares
            feitas = pares[pares["Email_Avaliador"] == email] if not pares.empty else pares
            notas_pares = pd.to_numeric(recebidas["Nota"], errors="coerce").dropna() if not recebidas.empty else []
            minhas = ativ[ativ["Email_Aluno"] == email] if not ativ.empty else ativ
            notas_ativ = minhas["Nota"].dropna() if not minhas.empty else []
            n_ativ = ativ["ID_Atividade"].nunique() if not ativ.empty else 0
            cits = citacoes.get(email, [])
            oficial = (ctx.banca.get((sala, grupo)) or {}).get("oficial")
            linhas.append(
                {
                    "Email": email,
                    "Nome": aluno["Nome"],
                    "Sala": sala,
                    "Grupo": grupo,
                    "Pct_Aulas": aulas["pct"],
                    "Aulas_Total": aulas["total"],
                    "Aulas_Presentes": aulas["presencas"],
                    "Faltas_Aulas": aulas["faltas"],
                    "Pct_Dailies": dailies["pct"],
                    "Dailies_Total": dailies["total"],
                    "Dailies_Presentes": dailies["presencas"],
                    "Faltas_Dailies": dailies["faltas"],
                    "Pares_Media": float(notas_pares.mean()) if len(notas_pares) else None,
                    "Pares_N": len(notas_pares),
                    "Pares_Feitos": len(set(feitas["Email_Avaliado"]) & (set(membros["Email"]) - {email}))
                    if not feitas.empty
                    else 0,
                    "Pares_Esperados": max(len(membros) - 1, 0),
                    "Orientador": ctx.notas_orientador.get(email),
                    "Banca": oficial["nota_total"] if oficial else None,
                    "Atividades_Media": float(notas_ativ.mean()) if len(notas_ativ) else None,
                    "Atividades_N": len(notas_ativ),
                    "Atividades_Sem_Nota": max(n_ativ - len(notas_ativ), 0),
                    "Dailies_Anotadas": len(cits),
                    "Dailies_Citado": sum(c["citacao"] == CITA_SIM for c in cits),
                    "Dailies_Ambiguas": sum(c["citacao"] == CITA_AMBIGUA for c in cits),
                }
            )
    return _ordenar_resumo(linhas)


def _ordenar_resumo(linhas: list[dict]) -> pd.DataFrame:
    linhas.sort(
        key=lambda r: (r["Sala"], chave_ordenacao_grupo(r["Grupo"]), chave_ordenacao_texto(r["Nome"]))
    )
    return pd.DataFrame(linhas)


def _media_ponderada(g: pd.DataFrame, col: str, peso: str) -> float | None:
    m = g[col].notna() & (g[peso] > 0)
    return float((g.loc[m, col] * g.loc[m, peso]).sum() / g.loc[m, peso].sum()) if m.any() else None


def combinar_resumos(resumos: list[pd.DataFrame]) -> pd.DataFrame:
    """Vários ciclos: presença sobre o total de encontros, pares e atividades ponderados, notas pela média."""
    validos = [r for r in resumos if not r.empty]
    if len(validos) <= 1:
        return validos[0] if validos else pd.DataFrame()
    todos = pd.concat(validos, ignore_index=True)
    somas = (
        "Aulas_Total", "Aulas_Presentes", "Faltas_Aulas", "Dailies_Total", "Dailies_Presentes",
        "Faltas_Dailies", "Pares_N", "Pares_Feitos", "Pares_Esperados", "Atividades_N",
        "Atividades_Sem_Nota", "Dailies_Anotadas", "Dailies_Citado", "Dailies_Ambiguas",
    )
    linhas = []
    for email, g in todos.groupby("Email", sort=False):
        ultimo = g.iloc[-1]
        linha = {"Email": email, "Nome": ultimo["Nome"], "Sala": ultimo["Sala"], "Grupo": ultimo["Grupo"]}
        linha.update({c: int(g[c].sum()) for c in somas})
        linha["Pct_Aulas"] = (
            linha["Aulas_Presentes"] / linha["Aulas_Total"] * 100 if linha["Aulas_Total"] else None
        )
        linha["Pct_Dailies"] = (
            linha["Dailies_Presentes"] / linha["Dailies_Total"] * 100 if linha["Dailies_Total"] else None
        )
        linha["Pares_Media"] = _media_ponderada(g, "Pares_Media", "Pares_N")
        linha["Orientador"] = _media(g["Orientador"])
        linha["Banca"] = _media(g["Banca"])
        linha["Atividades_Media"] = _media_ponderada(g, "Atividades_Media", "Atividades_N")
        linhas.append(linha)
    return _ordenar_resumo(linhas)


_RE_SALA_FORA = re.compile(r"teste|inativ|sem grupo|trancad|desist|cancel|evadid")


def salas_comparacao_padrao(resumo: pd.DataFrame) -> list[str]:
    """Salas de alunos ativos: ao menos 5 alunos e nome sem cara de teste/inativos."""
    if resumo.empty:
        return []
    contagem = resumo.loc[resumo["Sala"] != "", "Sala"].value_counts()
    ativas = [s for s, n in contagem.items() if n >= 5 and not _RE_SALA_FORA.search(_sem_acento(s))]
    return ordenar_grupos_lista(ativas or contagem.index.tolist())


_RE_CICLO_4 = re.compile(r"^ciclo\s*0?4$")


def ciclo_entrega_final(nome_ciclo: str) -> bool:
    """O Ciclo 4 costuma ser o da entrega final do projeto."""
    from domain.encontro_presencial import nome_parece_entrega_final

    nome = str(nome_ciclo or "").strip()
    return bool(_RE_CICLO_4.match(_sem_acento(nome))) or nome_parece_entrega_final(nome)


def titulo_ciclos(nomes: list[str]) -> str:
    nomes = [str(n).strip() for n in nomes if str(n).strip()]
    if len(nomes) <= 1:
        return nomes[0] if nomes else ""
    numeros = [re.fullmatch(r"(?i)ciclo\s*(\S+)", n) for n in nomes]
    if all(numeros):
        itens = [m.group(1) for m in numeros]
        return f"Ciclos {', '.join(itens[:-1])} e {itens[-1]}"
    return f"{', '.join(nomes[:-1])} e {nomes[-1]}"


# --- Dossiê individual ---


@dataclass
class DossieCiclo:
    nome: str
    periodo: str
    final: bool
    indicadores: dict
    medias_grupo: dict
    aulas: dict
    dailies: dict
    linha_dailies: pd.DataFrame
    comentarios_pares: list[str]
    comentarios_ocultos: int
    liberacao_pares: str
    situacao_pares: str
    pares_janela_encerrada: bool
    pares_pendente: bool
    banca: dict | None
    atividades: pd.DataFrame
    lacunas: list[str]


@dataclass
class Dossie:
    email: str
    nome: str
    primeiro_nome: str
    sala: str
    grupo: str
    titulo: str
    indicadores: dict
    medias_grupo: dict
    referencia: str
    referencia_curta: str
    n_referencia: int
    estatisticas: dict
    aulas: dict
    dailies: dict
    ciclos: list[DossieCiclo]
    destaques: list[str] = field(default_factory=list)
    atencao: list[str] = field(default_factory=list)
    lacunas: list[str] = field(default_factory=list)

    @property
    def varios_ciclos(self) -> bool:
        return len(self.ciclos) > 1

    @property
    def ciclos_finais(self) -> list[str]:
        return [c.nome for c in self.ciclos if c.final]

    def prefixo(self, c: DossieCiclo) -> str:
        return f"{c.nome}: " if self.varios_ciclos else ""


INDICADORES = (
    ("Pct_Aulas", "Presença nas aulas", fmt_pct),
    ("Pct_Dailies", "Presença nas dailies", fmt_pct),
    ("Pares_Media", "Pares recebida (0–5)", fmt_num),
    ("Orientador", "Orientador (0–10)", fmt_num),
    ("Banca", "Banca do grupo (0–10)", fmt_num),
    ("Atividades_Media", "Atividades (0–100)", fmt_num),
)
_COLUNAS_MEDIA = tuple(c for c, _, _ in INDICADORES)


def _sem_nan(d: dict) -> dict:
    return {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in d.items()}


def _medias(df: pd.DataFrame) -> dict:
    return {c: _media(df[c].tolist()) for c in _COLUNAS_MEDIA} if not df.empty else {}


def estatisticas_referencia(valores, valor) -> dict | None:
    """Média, quartis e posição do aluno; percentil conta empates pela metade."""
    nums = sorted(float(v) for v in valores if v is not None and not pd.isna(v))
    if not nums:
        return None
    serie = pd.Series(nums)
    est = {
        "n": len(nums),
        "media": float(serie.mean()),
        "q1": float(serie.quantile(0.25)),
        "mediana": float(serie.median()),
        "q3": float(serie.quantile(0.75)),
        "percentil": None,
        "posicao": "",
    }
    if valor is None or pd.isna(valor) or len(nums) < 4:
        return est
    v = float(valor)
    abaixo = sum(x < v for x in nums)
    iguais = sum(x == v for x in nums)
    est["percentil"] = (abaixo + iguais / 2) / len(nums) * 100
    if v == nums[-1] and v >= est["q3"]:
        est["posicao"] = "no topo" if iguais == 1 else "no topo (empatado)"
    elif v == nums[0] and v <= est["q1"]:
        est["posicao"] = "na base" if iguais == 1 else "na base (empatado)"
    elif v > est["q3"]:
        est["posicao"] = "quartil superior"
    elif v < est["q1"]:
        est["posicao"] = "quartil inferior"
    else:
        est["posicao"] = "faixa central"
    return est


def _linha_dailies(ctx: ContextoCiclo, email: str, citacoes: list[dict]) -> pd.DataFrame:
    d = ctx.dailies
    presenca = {}
    if not d.empty:
        for _, row in d[d["Email_Limpo"] == email].iterrows():
            presenca[row["Data"]] = "Presente" if row["Status_Aluno"] == "Presente" else "Faltou"
    por_data = {c["data"]: c for c in citacoes if c["data"] is not None and not pd.isna(c["data"])}
    linhas = []
    for data in sorted(set(presenca) | set(por_data)):
        cit = por_data.get(data)
        linhas.append(
            {
                "Data": _fmt_data(data),
                "Presença": presenca.get(data, "—"),
                "Anotação do grupo": "Sim" if cit else "Não",
                "Citado(a)": cit["citacao"].capitalize() if cit else "—",
                "Trecho": " … ".join(cit["trechos"]) if cit else "",
                "Anotação completa": cit["texto"] if cit else "",
                "Orientador(a)": cit["autor"] if cit else "",
            }
        )
    return pd.DataFrame(linhas)


def _situacao_pares(ctx: ContextoCiclo, ind: dict) -> str:
    feitos, esperados = ind["Pares_Feitos"], ind["Pares_Esperados"]
    hoje = hoje_normalizado()
    if ctx.pares_inicio is not None and hoje < ctx.pares_inicio:
        return f"Janela de pares ainda não abriu (abre em {_fmt_data(ctx.pares_inicio)})."
    aberta = ctx.pares_fim is not None and hoje <= ctx.pares_fim
    if esperados and feitos >= esperados:
        return f"Avaliou os {esperados} colegas do grupo."
    if feitos:
        base = f"Avaliou {feitos} de {esperados} colegas"
    else:
        base = "Ainda não enviou a avaliação de pares" if aberta else "Não enviou a avaliação de pares"
    return f"{base} (janela até {_fmt_data(ctx.pares_fim)})." if aberta else f"{base}."


def _dossie_ciclo(ctx: ContextoCiclo, resumo: pd.DataFrame, email: str) -> DossieCiclo | None:
    linha = resumo[resumo["Email"] == email] if not resumo.empty else resumo
    if linha.empty:
        return None
    ind = _sem_nan(linha.iloc[0].to_dict())
    sala, grupo = ind["Sala"], ind["Grupo"]
    grupo_df = resumo[(resumo["Sala"] == sala) & (resumo["Grupo"] == grupo) & (resumo["Email"] != email)]

    recebidas = ctx.pares[ctx.pares["Email_Avaliado"] == email] if not ctx.pares.empty else ctx.pares
    comentarios, ocultos = [], 0
    if not recebidas.empty:
        com_texto = recebidas[recebidas["Comentário"].astype(str).str.strip() != ""]
        ignorar = com_texto["Moderação"].astype(str).str.strip().str.lower() == "ignorar"
        comentarios = com_texto.loc[~ignorar, "Comentário"].astype(str).str.strip().tolist()
        ocultos = int(ignorar.sum())

    liberacao = ""
    lib = ctx.liberacoes
    if not lib.empty:
        usada = lib[(lib["Email_Aluno"] == email) & (lib["Usado_Em"].astype(str).str.strip() != "")]
        if not usada.empty:
            liberacao = f"Enviou com liberação excepcional em {str(usada.iloc[-1]['Usado_Em']).strip()[:10]}."

    ativ = ctx.atividades
    tabela_ativ = pd.DataFrame(columns=["Atividade", "Prazo", "Nota", "Editada"])
    if not ativ.empty:
        catalogo = ativ.drop_duplicates("ID_Atividade")[["ID_Atividade", "Atividade", "Prazo", "_prazo"]]
        minhas = ativ[ativ["Email_Aluno"] == email][["ID_Atividade", "Nota", "Editada"]]
        tabela_ativ = (
            catalogo.merge(minhas, on="ID_Atividade", how="left")
            .sort_values("_prazo")
            .drop(columns=["ID_Atividade", "_prazo"])
            .reset_index(drop=True)
        )
        tabela_ativ["Editada"] = tabela_ativ["Editada"].eq(True)

    citacoes = _citacoes_grupo(ctx, sala, grupo).get(email, [])
    membros = _membros(ctx, sala, grupo)
    ident = tokens_identificadores(dict(zip(membros["Email"], membros["Nome"]))).get(email, (set(), ""))
    banca = ctx.banca.get((sala, grupo))
    if banca:
        banca = {
            **banca,
            "comentarios": [{**c, "citacao": citacao(c["texto"], ident)} for c in banca["comentarios"]],
        }

    esperados, feitos = ind["Pares_Esperados"], ind["Pares_Feitos"]
    janela_passou = ctx.pares_fim is None or hoje_normalizado() > ctx.pares_fim
    periodo = (
        f"{_fmt_data(ctx.inicio)} a {_fmt_data(ctx.fim)}" if ctx.inicio is not None and ctx.fim is not None else ""
    )
    c = DossieCiclo(
        nome=ctx.nome_ciclo,
        periodo=periodo,
        final=ciclo_entrega_final(ctx.nome_ciclo),
        indicadores=ind,
        medias_grupo=_medias(grupo_df),
        aulas=_resumo_presenca(ctx.aulas, email),
        dailies=_resumo_presenca(ctx.dailies, email),
        linha_dailies=_linha_dailies(ctx, email, citacoes),
        comentarios_pares=comentarios,
        comentarios_ocultos=ocultos,
        liberacao_pares=liberacao,
        situacao_pares=_situacao_pares(ctx, ind),
        pares_janela_encerrada=janela_passou,
        pares_pendente=bool(esperados and feitos < esperados and janela_passou),
        banca=banca,
        atividades=tabela_ativ,
        lacunas=[],
    )

    if not periodo:
        c.lacunas.append("Ciclo sem período acadêmico cadastrado: presença e atividades consideram a disciplina toda.")
    if not c.aulas["total"]:
        c.lacunas.append("Sem aulas apuradas no período.")
    if not c.dailies["total"]:
        c.lacunas.append("Sem dailies apuradas no período.")
    if not ind["Dailies_Anotadas"]:
        c.lacunas.append("Nenhuma anotação de daily do grupo neste ciclo.")
    if not ind["Pares_N"]:
        c.lacunas.append("Ainda não recebeu avaliações de pares neste ciclo.")
    if ind["Orientador"] is None:
        c.lacunas.append("Nota do orientador não lançada.")
    if not banca or not banca.get("oficial"):
        c.lacunas.append("Avaliação da banca não lançada para o grupo.")
    if tabela_ativ.empty:
        c.lacunas.append("Nenhuma atividade individual com prazo no ciclo.")
    return c


def _juntar_presenca(matrizes: list[pd.DataFrame]) -> pd.DataFrame:
    validas = [m for m in matrizes if not m.empty]
    if not validas:
        return matrizes[0] if matrizes else pd.DataFrame()
    return pd.concat(validas).drop_duplicates(["Email_Limpo", "Data"]).sort_values("Data")


def _referencia(total: pd.DataFrame, sala: str, salas_ref: list[str] | None) -> tuple[pd.DataFrame, str, str]:
    salas = ordenar_grupos_lista([s for s in (salas_ref or []) if s in set(total["Sala"])])
    if salas:
        ref = total[total["Sala"].isin(salas)]
        if len(salas) == 1:
            return ref, f"sala {salas[0]}", "sala"
        return ref, f"salas {', '.join(salas[:-1])} e {salas[-1]}", "salas"
    if sala:
        return total[total["Sala"] == sala], f"sala {sala}", "sala"
    return total, "turma", "turma"


def _sinais(d: Dossie) -> None:
    ind, grp = d.indicadores, d.medias_grupo
    aulas, dailies = d.aulas, d.dailies
    escopo = "dos ciclos selecionados" if d.varios_ciclos else "do ciclo"

    if aulas["pct"] is not None:
        if aulas["pct"] < LIMIAR_PRESENCA:
            d.atencao.append(f"Presença nas aulas de {fmt_pct(aulas['pct'])}, abaixo de {fmt_pct(LIMIAR_PRESENCA)}.")
        elif aulas["faltas"] == 0 and aulas["total"] >= 2:
            d.destaques.append(f"Não faltou a nenhuma das {aulas['total']} aulas {escopo}.")
    if dailies["seq_max"] >= 2:
        d.atencao.append(f"Faltou a {dailies['seq_max']} dailies seguidas.")
    elif dailies["total"] >= 2 and dailies["faltas"] == 0:
        d.destaques.append(f"Presente em todas as {dailies['total']} dailies {escopo}.")

    for c in d.ciclos:
        if c.pares_pendente:
            d.atencao.append(d.prefixo(c) + c.situacao_pares)

    media, media_g = ind["Pares_Media"], grp.get("Pares_Media")
    if media is not None and media_g is not None and ind["Pares_N"] >= 2:
        if media >= media_g + 0.3:
            d.destaques.append(f"Nota recebida dos pares ({fmt_num(media)}/5) acima da média do grupo ({fmt_num(media_g)}).")
        elif media <= media_g - 0.3:
            d.atencao.append(f"Nota recebida dos pares ({fmt_num(media)}/5) abaixo da média do grupo ({fmt_num(media_g)}).")

    nota, nota_g = ind["Orientador"], grp.get("Orientador")
    if nota is not None and nota_g is not None:
        if nota >= nota_g + 0.5:
            d.destaques.append(f"Nota do orientador ({fmt_num(nota)}) acima da média do grupo ({fmt_num(nota_g)}).")
        elif nota <= nota_g - 0.5:
            d.atencao.append(f"Nota do orientador ({fmt_num(nota)}) abaixo da média do grupo ({fmt_num(nota_g)}).")

    linhas = [c.linha_dailies for c in d.ciclos if not c.linha_dailies.empty]
    if linhas:
        linha = pd.concat(linhas, ignore_index=True)
        anotadas_presente = linha[(linha["Anotação do grupo"] == "Sim") & (linha["Presença"] == "Presente")]
        citou = anotadas_presente["Citado(a)"].isin([CITA_SIM.capitalize(), CITA_AMBIGUA.capitalize()]).sum()
        if len(anotadas_presente) >= 2 and citou == 0:
            d.atencao.append(
                f"Presente em {len(anotadas_presente)} dailies anotadas, mas não aparece citado(a) nas anotações."
            )
        elif ind["Dailies_Citado"] >= 2:
            d.destaques.append(f"Citado(a) em {ind['Dailies_Citado']} anotações de daily {escopo}.")

    if ind["Atividades_Sem_Nota"]:
        d.atencao.append(f"{ind['Atividades_Sem_Nota']} atividade(s) individual(is) {escopo} sem nota lançada.")


def montar_dossie(
    ctxs: list[ContextoCiclo],
    resumos: list[pd.DataFrame],
    email: str,
    salas_ref: list[str] | None = None,
) -> Dossie | None:
    """Dossiê de um ou mais ciclos; indicadores somados e comparados com as salas de referência."""
    email = str(email).strip().lower()
    total = combinar_resumos(resumos)
    linha = total[total["Email"] == email] if not total.empty else total
    if linha.empty:
        return None
    ind = _sem_nan(linha.iloc[0].to_dict())
    sala, grupo = ind["Sala"], ind["Grupo"]
    grupo_df = total[(total["Sala"] == sala) & (total["Grupo"] == grupo) & (total["Email"] != email)]
    ref_df, referencia, curta = _referencia(total, sala, salas_ref)
    ciclos = [c for c in (_dossie_ciclo(ctx, r, email) for ctx, r in zip(ctxs, resumos)) if c]

    nome = str(ind["Nome"])
    d = Dossie(
        email=email,
        nome=nome,
        primeiro_nome=nome.split()[0] if nome.split() else nome,
        sala=sala,
        grupo=grupo,
        titulo=titulo_ciclos([c.nome for c in ciclos]),
        indicadores=ind,
        medias_grupo=_medias(grupo_df),
        referencia=referencia,
        referencia_curta=curta,
        n_referencia=len(ref_df),
        estatisticas={
            col: estatisticas_referencia(ref_df[col].tolist(), ind[col]) for col in _COLUNAS_MEDIA
        },
        aulas=_resumo_presenca(_juntar_presenca([ctx.aulas for ctx in ctxs]), email),
        dailies=_resumo_presenca(_juntar_presenca([ctx.dailies for ctx in ctxs]), email),
        ciclos=ciclos,
    )
    _sinais(d)
    d.lacunas = [d.prefixo(c) + item for c in ciclos for item in c.lacunas]
    return d


def _comparacao(d: Dossie, chave: str, fmt) -> str:
    partes = []
    media_g = d.medias_grupo.get(chave)
    if media_g is not None:
        partes.append(f"grupo {fmt(media_g)}")
    est = d.estatisticas.get(chave)
    if est:
        ref = (
            f"{d.referencia_curta}: média {fmt(est['media'])}, mediana {fmt(est['mediana'])}, "
            f"Q1–Q3 {fmt(est['q1'])} a {fmt(est['q3'])}"
        )
        if est["percentil"] is not None:
            ref += f", percentil {fmt_num(est['percentil'], 0)} — {est['posicao']}"
        partes.append(ref)
    return f" | {'; '.join(partes)}" if partes else ""


def _texto_ciclo(d: Dossie, c: DossieCiclo) -> list[str]:
    l = [f"Avaliação de pares feita: {c.situacao_pares} {c.liberacao_pares}".strip()]
    if c.comentarios_pares:
        l.append("Feedbacks dos colegas (anônimos):")
        l.extend(f'- "{t}"' for t in c.comentarios_pares)

    if c.banca:
        oficial = c.banca.get("oficial")
        if oficial:
            l.append(
                f"Banca (nota do grupo): total {fmt_num(oficial['nota_total'])} — apresentação "
                f"{fmt_num(oficial['nota_apresentacao'])}, conteúdo {fmt_num(oficial['nota_conteudo'])}"
            )
        if c.banca.get("comentarios"):
            l.append("Comentários da banca ao grupo:")
            for com in c.banca["comentarios"]:
                marca = f"(cita {d.primeiro_nome}) " if com["citacao"] != CITA_NAO else ""
                l.append(f'- {marca}"{com["texto"]}"')

    linha = c.linha_dailies
    anotadas = linha[linha["Anotação do grupo"] == "Sim"] if not linha.empty else linha
    if not anotadas.empty:
        citadas = anotadas[anotadas["Citado(a)"] != CITA_NAO.capitalize()]
        l.append(f"Anotações de daily do grupo: {len(anotadas)}; cita {d.primeiro_nome} em {len(citadas)}.")
        for _, row in citadas.iterrows():
            obs = " (nome repetido no grupo, conferir)" if row["Citado(a)"] == CITA_AMBIGUA.capitalize() else ""
            l.append(f'- {row["Data"]}{obs}: "{row["Trecho"]}"')
        sem = anotadas[anotadas["Citado(a)"] == CITA_NAO.capitalize()]
        if not sem.empty:
            itens = ", ".join(f"{r['Data']} ({r['Presença'].lower()})" for _, r in sem.iterrows())
            l.append(f"Anotações que não citam {d.primeiro_nome}: {itens}")

    t = c.atividades
    if not t.empty:
        ind = c.indicadores
        l.append(
            f"Atividades individuais: média {fmt_num(ind['Atividades_Media'])}/100 "
            f"em {t['Nota'].notna().sum()} de {len(t)}"
        )
        sem_nota = t[t["Nota"].isna()]["Atividade"].tolist()
        if sem_nota:
            l.append(f"Sem nota lançada: {'; '.join(sem_nota)}")
    return l


def _evolucao_ciclo(c: DossieCiclo) -> str:
    ind = c.indicadores
    partes = [
        f"aulas {fmt_pct(ind['Pct_Aulas'])}",
        f"dailies {fmt_pct(ind['Pct_Dailies'])}",
        f"pares {fmt_num(ind['Pares_Media'])}",
        f"orientador {fmt_num(ind['Orientador'])}",
        f"banca {fmt_num(ind['Banca'])}",
        f"atividades {fmt_num(ind['Atividades_Media'])}",
    ]
    return ", ".join(partes)


def _rotulo_ciclo(c: DossieCiclo) -> str:
    periodo = f" ({c.periodo})" if c.periodo else ""
    final = " — entrega final" if c.final else ""
    return f"{c.nome}{periodo}{final}"


def dossie_em_texto(d: Dossie) -> str:
    """Resumo em texto corrido, só com o primeiro nome e sem e-mails nem autores dos pares."""
    ind = d.indicadores
    sala = f", Sala {d.sala}" if d.sala else ""
    cabecalho = _rotulo_ciclo(d.ciclos[0]) if len(d.ciclos) == 1 else d.titulo
    l = [
        f"Aluno(a): {d.primeiro_nome} — Grupo {d.grupo}{sala} — {cabecalho}",
        f"Comparações: “grupo” = média dos demais integrantes do grupo; “{d.referencia_curta}” = "
        f"{d.referencia} ({d.n_referencia} alunos).",
        "",
    ]
    if d.varios_ciclos:
        l.append("Visão consolidada dos ciclos selecionados:")

    a = d.aulas
    if a["total"]:
        faltas = f"; faltas em {', '.join(a['datas_falta'])}" if a["datas_falta"] else ""
        l.append(f"Presença nas aulas: {fmt_pct(a['pct'])} ({a['presencas']} de {a['total']}{faltas}){_comparacao(d, 'Pct_Aulas', fmt_pct)}")
    dl = d.dailies
    if dl["total"]:
        faltas = f"; faltas em {', '.join(dl['datas_falta'])}" if dl["datas_falta"] else ""
        l.append(f"Presença nas dailies: {fmt_pct(dl['pct'])} ({dl['presencas']} de {dl['total']}{faltas}){_comparacao(d, 'Pct_Dailies', fmt_pct)}")
    if ind["Pares_N"]:
        l.append(
            f"Avaliação recebida dos pares: média {fmt_num(ind['Pares_Media'])}/5 de {ind['Pares_N']} avaliação(ões)"
            f"{_comparacao(d, 'Pares_Media', fmt_num)}"
        )
    if d.varios_ciclos:
        encerrados = [c for c in d.ciclos if c.pares_janela_encerrada and c.indicadores["Pares_Esperados"]]
        if encerrados:
            completos = sum(not c.pares_pendente for c in encerrados)
            l.append(
                f"Avaliação de pares feita: completa em {completos} de {len(encerrados)} ciclo(s) com janela encerrada."
            )
    media_ciclos = " (média dos ciclos)" if d.varios_ciclos else ""
    if ind["Orientador"] is not None:
        l.append(f"Nota do orientador{media_ciclos}: {fmt_num(ind['Orientador'])}/10{_comparacao(d, 'Orientador', fmt_num)}")
    if ind["Banca"] is not None:
        l.append(f"Banca do grupo{media_ciclos}: {fmt_num(ind['Banca'])}/10{_comparacao(d, 'Banca', fmt_num)}")
    if ind["Atividades_N"] or ind["Atividades_Sem_Nota"]:
        l.append(
            f"Atividades individuais: média {fmt_num(ind['Atividades_Media'])}/100 em {ind['Atividades_N']} "
            f"com nota{_comparacao(d, 'Atividades_Media', fmt_num)}"
        )

    if d.varios_ciclos:
        l += ["", "Evolução por ciclo:"]
        l += [f"- {_rotulo_ciclo(c)}: {_evolucao_ciclo(c)}" for c in d.ciclos]
    for c in d.ciclos:
        if d.varios_ciclos:
            l += ["", f"== {_rotulo_ciclo(c)} =="]
        l += _texto_ciclo(d, c)

    if d.destaques:
        l += ["", "Destaques (automáticos):"] + [f"- {s}" for s in d.destaques]
    if d.atencao:
        l += ["", "Pontos de atenção (automáticos):"] + [f"- {s}" for s in d.atencao]
    if d.lacunas:
        l += ["", "Dados ausentes:"] + [f"- {s}" for s in d.lacunas]
    return "\n".join(l)


_CONTEXTO_CURSO = (
    "No curso, os alunos trabalham em grupos fixos num projeto para um cliente real, com aulas, dailies "
    "(encontros curtos do grupo com a orientadora), avaliação entre colegas (pares) e apresentação para uma "
    "banca ao fim de cada ciclo, realizando uma entrega de valor para o cliente."
)


def _sobre(d: Dossie) -> str:
    if d.varios_ciclos:
        return f"os {d.titulo}" if d.titulo.startswith("Ciclos") else f"os ciclos {d.titulo}"
    return f"o {d.titulo}" if d.titulo.lower().startswith("ciclo") else f"o ciclo {d.titulo}"


def prompt_feedback(d: Dossie) -> str:
    """Instruções para a IA + dossiê em texto, prontos para colar no Gemini."""
    nome = d.primeiro_nome
    finais = d.ciclos_finais
    intro = (
        f"Você vai ajudar uma orientadora da graduação em Gestão do Agronegócio do Rehagro a preparar uma "
        f"conversa individual de feedback com {nome} sobre {_sobre(d)}. {_CONTEXTO_CURSO}"
    )
    if finais:
        intro += (
            f" O {titulo_ciclos(finais)} corresponde à entrega final do projeto: não há próximo ciclo, "
            "então as orientações devem mirar os próximos projetos."
        )
    if d.varios_ciclos:
        visao = "2 a 4 frases sobre o desempenho no conjunto dos ciclos, incluindo a evolução entre eles."
    else:
        visao = "2 a 3 frases sobre o desempenho no ciclo."
    if finais:
        futuro = (
            "Orientações para os próximos projetos — 2 ou 3 recomendações práticas para levar aos próximos "
            "projetos e à vida profissional."
        )
    else:
        futuro = "Sugestões para o próximo ciclo — 2 ou 3 ações práticas e específicas."
    regras = [
        "Use só as informações do dossiê. Não invente fatos, números nem situações.",
        "Dado ausente não é falha do aluno: pode ser que não tenha sido registrado. Coloque na seção 6.",
        f"Comentários da banca e anotações de daily são sobre o grupo; só atribua algo a {nome} quando o trecho o citar.",
        "Não ser citado numa anotação de daily não significa participação ruim; trate como algo a confirmar.",
        "Escalas: pares de 0 a 5, orientador e banca de 0 a 10, atividades de 0 a 100. Diferenças pequenas "
        "(até 0,3 nos pares ou 0,5 no orientador) não são relevantes.",
        "“grupo” é a média dos demais integrantes do grupo; a outra comparação é com as salas indicadas no "
        "dossiê. Use a posição e os quartis informados; não exagere diferenças.",
        "Os feedbacks dos colegas são anônimos: não tente identificar autores e cite-os de forma resumida.",
        "“Destaques” e “Pontos de atenção” foram gerados por regras automáticas simples; use como pistas, "
        "confirmando nos dados.",
    ]
    if d.varios_ciclos:
        regras.append(
            "O dossiê traz uma visão consolidada e o detalhe de cada ciclo. Compare os ciclos: aponte melhoras, "
            "quedas e padrões que se repetem."
        )
    limite = 600 if d.varios_ciclos else 450
    regras.append(
        f"Tom acolhedor, direto e respeitoso, tratando {nome} pelo primeiro nome. Português do Brasil. "
        f"No máximo {limite} palavras no total."
    )
    secoes = [
        f"Visão geral — {visao}",
        "Pontos fortes — cada um apoiado em um dado ou trecho concreto do dossiê.",
        "Pontos de desenvolvimento — formulados de forma construtiva, também com a evidência.",
        futuro,
        f"Perguntas para abrir a conversa — 3 perguntas abertas que convidem {nome} a refletir.",
        "Pontos para a orientadora confirmar antes da conversa — dados ausentes, ambíguos ou que podem ter "
        "outra explicação.",
        f"Mensagem curta — até 5 frases que a orientadora possa enviar por escrito a {nome}, se quiser.",
    ]
    partes = [
        intro,
        "",
        f"Abaixo está o dossiê de {nome}, gerado pelo sistema de avaliação. Escreva um rascunho de feedback com estas seções:",
        "",
        *[f"{i}. {s}" for i, s in enumerate(secoes, 1)],
        "",
        "Regras:",
        *[f"- {r}" for r in regras],
        "",
        "--- DOSSIÊ ---",
        dossie_em_texto(d),
    ]
    return "\n".join(partes)
