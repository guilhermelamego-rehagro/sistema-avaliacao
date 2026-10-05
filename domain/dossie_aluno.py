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
from utils.ordenacao import chave_ordenacao_grupo, chave_ordenacao_texto

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
            linhas.append(
                {
                    "Email": email,
                    "Nome": aluno["Nome"],
                    "Sala": sala,
                    "Grupo": grupo,
                    "Pct_Aulas": aulas["pct"],
                    "Faltas_Aulas": aulas["faltas"],
                    "Pct_Dailies": dailies["pct"],
                    "Faltas_Dailies": dailies["faltas"],
                    "Pares_Media": float(notas_pares.mean()) if len(notas_pares) else None,
                    "Pares_N": len(notas_pares),
                    "Pares_Feitos": len(set(feitas["Email_Avaliado"]) & (set(membros["Email"]) - {email}))
                    if not feitas.empty
                    else 0,
                    "Pares_Esperados": max(len(membros) - 1, 0),
                    "Orientador": ctx.notas_orientador.get(email),
                    "Atividades_Media": float(notas_ativ.mean()) if len(notas_ativ) else None,
                    "Atividades_Sem_Nota": max(n_ativ - len(notas_ativ), 0),
                    "Dailies_Anotadas": len(cits),
                    "Dailies_Citado": sum(c["citacao"] == CITA_SIM for c in cits),
                    "Dailies_Ambiguas": sum(c["citacao"] == CITA_AMBIGUA for c in cits),
                }
            )
    linhas.sort(
        key=lambda r: (r["Sala"], chave_ordenacao_grupo(r["Grupo"]), chave_ordenacao_texto(r["Nome"]))
    )
    return pd.DataFrame(linhas)


# --- Dossiê individual ---


@dataclass
class Dossie:
    email: str
    nome: str
    primeiro_nome: str
    sala: str
    grupo: str
    indicadores: dict
    medias_grupo: dict
    medias_turma: dict
    aulas: dict
    dailies: dict
    linha_dailies: pd.DataFrame
    comentarios_pares: list[str]
    comentarios_ocultos: int
    liberacao_pares: str
    situacao_pares: str
    banca: dict | None
    atividades: pd.DataFrame
    destaques: list[str]
    atencao: list[str]
    lacunas: list[str]


_COLUNAS_MEDIA = ("Pct_Aulas", "Pct_Dailies", "Pares_Media", "Orientador", "Atividades_Media")


def _medias(df: pd.DataFrame) -> dict:
    return {c: _media(df[c].tolist()) for c in _COLUNAS_MEDIA} if not df.empty else {}


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


def _sinais(ctx: ContextoCiclo, d: Dossie) -> None:
    ind, grp = d.indicadores, d.medias_grupo
    aulas, dailies = d.aulas, d.dailies

    if aulas["pct"] is not None:
        if aulas["pct"] < LIMIAR_PRESENCA:
            d.atencao.append(f"Presença nas aulas de {fmt_pct(aulas['pct'])}, abaixo de {fmt_pct(LIMIAR_PRESENCA)}.")
        elif aulas["faltas"] == 0 and aulas["total"] >= 2:
            d.destaques.append(f"Não faltou a nenhuma das {aulas['total']} aulas do ciclo.")
    if dailies["seq_max"] >= 2:
        d.atencao.append(f"Faltou a {dailies['seq_max']} dailies seguidas.")
    elif dailies["total"] >= 2 and dailies["faltas"] == 0:
        d.destaques.append(f"Presente em todas as {dailies['total']} dailies do ciclo.")

    esperados, feitos = ind["Pares_Esperados"], ind["Pares_Feitos"]
    janela_passou = ctx.pares_fim is None or hoje_normalizado() > ctx.pares_fim
    if esperados and feitos < esperados and janela_passou:
        d.atencao.append(d.situacao_pares)

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

    linha = d.linha_dailies
    if not linha.empty:
        anotadas_presente = linha[(linha["Anotação do grupo"] == "Sim") & (linha["Presença"] == "Presente")]
        citou = anotadas_presente["Citado(a)"].isin([CITA_SIM.capitalize(), CITA_AMBIGUA.capitalize()]).sum()
        if len(anotadas_presente) >= 2 and citou == 0:
            d.atencao.append(
                f"Presente em {len(anotadas_presente)} dailies anotadas, mas não aparece citado(a) nas anotações."
            )
        elif ind["Dailies_Citado"] >= 2:
            d.destaques.append(f"Citado(a) em {ind['Dailies_Citado']} anotações de daily do ciclo.")

    if ind["Atividades_Sem_Nota"]:
        d.atencao.append(f"{ind['Atividades_Sem_Nota']} atividade(s) individual(is) do ciclo sem nota lançada.")


def montar_dossie(ctx: ContextoCiclo, resumo: pd.DataFrame, email: str) -> Dossie | None:
    email = str(email).strip().lower()
    linha = resumo[resumo["Email"] == email]
    if linha.empty:
        return None
    ind = linha.iloc[0].to_dict()
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
    nome = str(ind["Nome"])
    d = Dossie(
        email=email,
        nome=nome,
        primeiro_nome=nome.split()[0] if nome.split() else nome,
        sala=sala,
        grupo=grupo,
        indicadores=ind,
        medias_grupo=_medias(grupo_df),
        medias_turma=_medias(resumo),
        aulas=_resumo_presenca(ctx.aulas, email),
        dailies=_resumo_presenca(ctx.dailies, email),
        linha_dailies=_linha_dailies(ctx, email, citacoes),
        comentarios_pares=comentarios,
        comentarios_ocultos=ocultos,
        liberacao_pares=liberacao,
        situacao_pares="",
        banca=banca,
        atividades=tabela_ativ,
        destaques=[],
        atencao=[],
        lacunas=[],
    )
    d.situacao_pares = _situacao_pares(ctx, ind)
    _sinais(ctx, d)

    if ctx.inicio is None or ctx.fim is None:
        d.lacunas.append("Ciclo sem período acadêmico cadastrado: presença e atividades consideram a disciplina toda.")
    if not d.aulas["total"]:
        d.lacunas.append("Sem aulas apuradas no período.")
    if not d.dailies["total"]:
        d.lacunas.append("Sem dailies apuradas no período.")
    if not ind["Dailies_Anotadas"]:
        d.lacunas.append("Nenhuma anotação de daily do grupo neste ciclo.")
    if not ind["Pares_N"]:
        d.lacunas.append("Ainda não recebeu avaliações de pares neste ciclo.")
    if ind["Orientador"] is None:
        d.lacunas.append("Nota do orientador não lançada.")
    if not d.banca or not d.banca.get("oficial"):
        d.lacunas.append("Avaliação da banca não lançada para o grupo.")
    if tabela_ativ.empty:
        d.lacunas.append("Nenhuma atividade individual com prazo no ciclo.")
    return d


def _comparacao(d: Dossie, chave: str, fmt) -> str:
    partes = []
    for rotulo, medias in (("grupo", d.medias_grupo), ("turma", d.medias_turma)):
        valor = medias.get(chave)
        if valor is not None:
            partes.append(f"{rotulo} {fmt(valor)}")
    return f" | média: {', '.join(partes)}" if partes else ""


def dossie_em_texto(ctx: ContextoCiclo, d: Dossie) -> str:
    """Resumo em texto corrido, só com o primeiro nome e sem e-mails nem autores dos pares."""
    ind = d.indicadores
    periodo = f" ({_fmt_data(ctx.inicio)} a {_fmt_data(ctx.fim)})" if ctx.inicio is not None and ctx.fim is not None else ""
    sala = f", Sala {d.sala}" if d.sala else ""
    l = [f"Aluno(a): {d.primeiro_nome} — Grupo {d.grupo}{sala} — {ctx.nome_ciclo}{periodo}", ""]

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
            f"Avaliação recebida dos pares: média {fmt_num(ind['Pares_Media'])}/5 de {ind['Pares_N']} colega(s)"
            f"{_comparacao(d, 'Pares_Media', fmt_num)}"
        )
    l.append(f"Avaliação de pares feita: {d.situacao_pares} {d.liberacao_pares}".strip())
    if d.comentarios_pares:
        l.append("Feedbacks dos colegas (anônimos):")
        l.extend(f'- "{c}"' for c in d.comentarios_pares)

    if ind["Orientador"] is not None:
        l.append(f"Nota do orientador: {fmt_num(ind['Orientador'])}/10{_comparacao(d, 'Orientador', fmt_num)}")

    if d.banca:
        oficial = d.banca.get("oficial")
        if oficial:
            l.append(
                f"Banca (nota do grupo): total {fmt_num(oficial['nota_total'])} — apresentação "
                f"{fmt_num(oficial['nota_apresentacao'])}, conteúdo {fmt_num(oficial['nota_conteudo'])}"
            )
        if d.banca.get("comentarios"):
            l.append("Comentários da banca ao grupo:")
            for c in d.banca["comentarios"]:
                marca = f"(cita {d.primeiro_nome}) " if c["citacao"] != CITA_NAO else ""
                l.append(f'- {marca}"{c["texto"]}"')

    linha = d.linha_dailies
    if not linha.empty:
        anotadas = linha[linha["Anotação do grupo"] == "Sim"]
        citadas = anotadas[anotadas["Citado(a)"] != CITA_NAO.capitalize()]
        l.append(f"Anotações de daily do grupo no ciclo: {len(anotadas)}; cita {d.primeiro_nome} em {len(citadas)}.")
        for _, row in citadas.iterrows():
            obs = " (nome repetido no grupo, conferir)" if row["Citado(a)"] == CITA_AMBIGUA.capitalize() else ""
            l.append(f'- {row["Data"]}{obs}: "{row["Trecho"]}"')
        sem = anotadas[anotadas["Citado(a)"] == CITA_NAO.capitalize()]
        if not sem.empty:
            itens = ", ".join(f"{r['Data']} ({r['Presença'].lower()})" for _, r in sem.iterrows())
            l.append(f"Anotações que não citam {d.primeiro_nome}: {itens}")

    t = d.atividades
    if not t.empty:
        sem_nota = t[t["Nota"].isna()]["Atividade"].tolist()
        resumo_ativ = f"Atividades individuais do ciclo: média {fmt_num(ind['Atividades_Media'])}/100 em {t['Nota'].notna().sum()} de {len(t)}"
        resumo_ativ += _comparacao(d, "Atividades_Media", fmt_num)
        l.append(resumo_ativ)
        if sem_nota:
            l.append(f"Sem nota lançada: {'; '.join(sem_nota)}")

    if d.destaques:
        l += ["", "Destaques (automáticos):"] + [f"- {s}" for s in d.destaques]
    if d.atencao:
        l += ["", "Pontos de atenção (automáticos):"] + [f"- {s}" for s in d.atencao]
    if d.lacunas:
        l += ["", "Dados ausentes:"] + [f"- {s}" for s in d.lacunas]
    return "\n".join(l)
