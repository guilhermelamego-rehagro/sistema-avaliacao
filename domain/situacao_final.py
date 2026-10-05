"""Situação final do aluno no fechamento da disciplina e os motivos que levaram a ela.

A situação de avaliação usa as mesmas regras e o mesmo boletim da Liberação de notas.
Segunda chamada é uma marca à parte: falta no encontro presencial ou pendência na matrícula.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from domain.dossie_aluno import _matrizes_presenca, _resumo_presenca, _vividas_no_periodo, fmt_num, fmt_pct
from utils.disciplina import normalizar_id

APROVADO = "Aprovado"
RECUPERACAO = "Recuperação"
REPROVADO_NOTA = "Reprovado por nota"
REPROVADO_FREQUENCIA = "Reprovado por frequência"
PENDENTE = "Pendente"
SEGUNDA_CHAMADA = "Segunda chamada"
SITUACOES = (APROVADO, RECUPERACAO, REPROVADO_NOTA, REPROVADO_FREQUENCIA, PENDENTE)

NOTA_APROVACAO = 70.0
NOTA_RECUPERACAO = 40.0
PRESENCA_MINIMA = 75.0

_DO_STATUS_ACADEMICO = {
    "Aprovado": APROVADO,
    "Recuperação": RECUPERACAO,
    "Reprovado": REPROVADO_NOTA,
    "Reprovado (presença)": REPROVADO_FREQUENCIA,
    "Pendente": PENDENTE,
}


@dataclass
class ResultadoFinal:
    email: str
    situacao: str
    nota_final: float | None
    presenca: dict
    componentes: pd.DataFrame
    segunda_chamada: list[str] = field(default_factory=list)
    motivos: list[str] = field(default_factory=list)


def fmt_peso(valor) -> str:
    v = float(valor)
    return fmt_num(v, 0) if v.is_integer() else fmt_num(v, 1)


def _fmt_data_br(ts) -> str:
    return pd.Timestamp(ts).strftime("%d/%m/%Y")


def periodos_ciclos(ciclos: pd.DataFrame) -> list[tuple[str, object, object]]:
    from domain.ciclos import preparar_ciclos
    from domain.dossie_aluno import _ts

    if ciclos is None or ciclos.empty:
        return []
    return [
        (str(c.get("Nome_Ciclo", "")).strip(), _ts(c.get("Data_Inicio_Ciclo")), _ts(c.get("Data_Apresentacao")))
        for _, c in preparar_ciclos(ciclos).iterrows()
    ]


def _faltas_encontro(id_disciplina: str) -> dict[str, list[str]]:
    from data.sheets import ler_aba
    from domain.encontro_presencial import datas_encontro_ativas, disciplina_tem_encontro_presencial
    from utils.datas import parse_data_planilha_series

    if not disciplina_tem_encontro_presencial(id_disciplina):
        return {}
    datas = {_fmt_data_br(d) for d in datas_encontro_ativas(id_disciplina)["_parsed"]}
    try:
        df = ler_aba("Presenca_Encontro")
    except Exception:
        return {}
    if df.empty or not datas:
        return {}
    df = df[df["ID_Disciplina"].map(normalizar_id) == normalizar_id(id_disciplina)].copy()
    df["_data"] = parse_data_planilha_series(df["Data"]).map(lambda d: "" if pd.isna(d) else _fmt_data_br(d))
    faltas = df[(df["Status"].astype(str).str.strip() == "Falta") & df["_data"].isin(datas)]
    saida: dict[str, list[str]] = {}
    for _, row in faltas.iterrows():
        saida.setdefault(str(row["Email_Aluno"]).strip().lower(), []).append(row["_data"][:5])
    return saida


def marcas_segunda_chamada(id_disciplina: str) -> dict[str, list[str]]:
    """Por aluno: por que ele está em segunda chamada (pode haver mais de um motivo)."""
    from domain.filtros_operacionais import info_academica_disciplina

    saida = {
        email: [f"Faltou ao encontro presencial ({', '.join(datas)})."]
        for email, datas in _faltas_encontro(id_disciplina).items()
    }
    for email, meta in (info_academica_disciplina(id_disciplina) or {}).items():
        if meta.get("pendencia") == "segunda_chamada":
            saida.setdefault(email, []).append("Pendência de segunda chamada marcada na matrícula.")
    return saida


def _janela_pares_encerrada(id_ciclo: str) -> bool:
    from data.sheets import ler_aba
    from domain.ciclos import hoje_normalizado, preparar_ciclos

    df = ler_aba("Ciclos")
    linha = df[df["ID_Ciclo"].astype(str).str.strip() == str(id_ciclo).strip()]
    if linha.empty:
        return False
    fim = preparar_ciclos(linha).iloc[0]["Data fim"]
    return pd.notna(fim) and hoje_normalizado() > fim


def _pares_nao_enviados(email: str, id_disciplina: str) -> set[str]:
    """Componentes cujo prazo de pares já acabou sem o aluno avaliar os colegas (pares contam ×1)."""
    from domain.componentes import carregar_componentes_disciplina
    from domain.encontro_presencial import resolver_id_ciclo_componente
    from domain.notas import _situacao_pares_ciclo

    nomes = set()
    for _, comp in carregar_componentes_disciplina(id_disciplina).iterrows():
        tipo = str(comp["Tipo"]).strip()
        if tipo not in ("Ciclo", "Entrega_Final"):
            continue
        id_ciclo, _ = resolver_id_ciclo_componente(tipo, str(comp.get("ID_Ciclo", "")).strip(), id_disciplina)
        if id_ciclo and _janela_pares_encerrada(id_ciclo) and not _situacao_pares_ciclo(email, id_ciclo)[1]:
            nomes.add(str(comp["Nome"]).strip())
    return nomes


def _tabela_componentes(boletim: pd.DataFrame, sem_pares: set[str]) -> pd.DataFrame:
    linhas = []
    for _, c in boletim.iterrows():
        peso = float(c["Peso (%)"])
        nota = None if pd.isna(c["Nota (0-100)"]) else float(c["Nota (0-100)"])
        contrib = None if pd.isna(c["Contribuição"]) else float(c["Contribuição"])
        detalhe = str(c.get("Detalhe") or "")
        if c["Componente"] in sem_pares:
            detalhe += " · não enviou a avaliação de pares (pares ×1)"
        linhas.append(
            {
                "Componente": c["Componente"],
                "Peso": peso,
                "Nota": nota,
                "Pontos": contrib,
                "Perdeu": peso - (contrib or 0.0),
                "Detalhe": detalhe,
            }
        )
    return pd.DataFrame(linhas)


def _faltas_por_ciclo(matriz: pd.DataFrame, email: str, ciclos: list[tuple[str, object, object]]) -> str:
    m = matriz[(matriz["Email_Limpo"] == email) & (matriz["Status_Aluno"] == "Falta")]
    partes = []
    for nome, inicio, fim in ciclos:
        if inicio is None or fim is None:
            continue
        n = int(((m["Data"] >= inicio) & (m["Data"] <= fim)).sum())
        partes.append(f"{nome}: {n}")
    return ", ".join(partes)


def _motivos(r: ResultadoFinal, faltas_ciclo: str) -> list[str]:
    p, comp, nota = r.presenca, r.componentes, r.nota_final
    motivos = []
    sem_nota = comp[comp["Nota"].isna()] if not comp.empty else comp

    if r.situacao == REPROVADO_FREQUENCIA:
        faltam = max(math.ceil(PRESENCA_MINIMA / 100 * p["total"] - p["presencas"]), 0)
        motivos.append(
            f"Presença de {fmt_pct(p['pct'])} no total da disciplina ({p['presencas']} de {p['total']} aulas, "
            f"{p['faltas']} faltas); o mínimo é {fmt_pct(PRESENCA_MINIMA)}. Faltaram {faltam} presença(s)."
        )
        if p["seq_max"] >= 2:
            motivos.append(f"Maior sequência: {p['seq_max']} faltas seguidas.")
        if faltas_ciclo:
            motivos.append(f"Faltas por ciclo — {faltas_ciclo}.")
        if nota is not None and nota < NOTA_APROVACAO:
            motivos.append(f"A nota final ({fmt_num(nota)}) também ficou abaixo de {fmt_num(NOTA_APROVACAO, 0)}.")

    elif r.situacao in (REPROVADO_NOTA, RECUPERACAO):
        texto = f"Nota final {fmt_num(nota)}: faltaram {fmt_num(NOTA_APROVACAO - nota)} pontos para a aprovação ({fmt_num(NOTA_APROVACAO, 0)})"
        if r.situacao == REPROVADO_NOTA:
            texto += f" e {fmt_num(NOTA_RECUPERACAO - nota)} para a recuperação ({fmt_num(NOTA_RECUPERACAO, 0)})"
        motivos.append(texto + ".")
        perdas = comp[comp["Perdeu"] >= 0.5].sort_values("Perdeu", ascending=False).head(3)
        for _, c in perdas.iterrows():
            if c["Nota"] is None or pd.isna(c["Nota"]):
                motivos.append(
                    f"{c['Componente']} (peso {fmt_peso(c['Peso'])}%): sem nota — contou como zero, "
                    f"perdeu {fmt_num(c['Perdeu'])} pontos."
                )
            else:
                motivos.append(
                    f"{c['Componente']} (peso {fmt_peso(c['Peso'])}%): nota {fmt_num(c['Nota'])}, "
                    f"perdeu {fmt_num(c['Perdeu'])} pontos. {c['Detalhe']}".strip()
                )
        if p["pct"] is not None and p["pct"] < 85:
            motivos.append(f"Presença de {fmt_pct(p['pct'])} — acima do mínimo, mas com {p['faltas']} faltas.")

    elif r.situacao == APROVADO:
        motivos.append(f"Nota final {fmt_num(nota)} (mínimo {fmt_num(NOTA_APROVACAO, 0)}) e presença de {fmt_pct(p['pct'])}.")
        fortes = comp[comp["Nota"].notna()].sort_values("Pontos", ascending=False).head(2) if not comp.empty else comp
        for _, c in fortes.iterrows():
            motivos.append(
                f"{c['Componente']} (peso {fmt_peso(c['Peso'])}%): nota {fmt_num(c['Nota'])}, "
                f"{fmt_num(c['Pontos'])} dos {fmt_peso(c['Peso'])} pontos possíveis."
            )

    elif r.situacao == PENDENTE:
        motivos.append("Ainda não há nota final calculada.")

    if not sem_nota.empty and r.situacao != PENDENTE:
        nomes = ", ".join(sem_nota["Componente"].tolist())
        motivos.append(f"Componentes sem nota lançada: {nomes}. A situação pode mudar quando forem lançados.")
    motivos.extend(r.segunda_chamada)
    return motivos


def calcular_resultados(
    id_disciplina: str,
    alunos: pd.DataFrame,
    ciclos: list[tuple[str, object, object]] | None = None,
    *,
    ao_avancar=None,
) -> dict[str, ResultadoFinal]:
    """Boletim, presença e situação de cada aluno (colunas Email, Sala, Grupo de ``resumo_alunos``)."""
    from domain.notas import calcular_boletim_aluno, nota_final_boletim, status_academico
    from utils.leitura_lote import leitura_em_lote

    id_d = normalizar_id(id_disciplina)
    todos = tuple(sorted(alunos["Email"]))
    aulas, _ = _matrizes_presenca(id_d, todos)
    aulas = _vividas_no_periodo(aulas, None, None)
    segunda = marcas_segunda_chamada(id_d)
    saida: dict[str, ResultadoFinal] = {}
    with leitura_em_lote():
        for i, (_, aluno) in enumerate(alunos.iterrows(), 1):
            email = aluno["Email"]
            boletim = calcular_boletim_aluno(email, id_d, aluno["Grupo"], aluno["Sala"])
            nota = nota_final_boletim(boletim)
            presenca = _resumo_presenca(aulas, email)
            situacao = _DO_STATUS_ACADEMICO.get(status_academico(presenca["pct"], nota), PENDENTE)
            r = ResultadoFinal(
                email=email,
                situacao=situacao,
                nota_final=nota,
                presenca=presenca,
                componentes=_tabela_componentes(boletim, _pares_nao_enviados(email, id_d)),
                segunda_chamada=segunda.get(email, []),
            )
            r.motivos = _motivos(r, _faltas_por_ciclo(aulas, email, ciclos or []))
            saida[email] = r
            if ao_avancar:
                ao_avancar(i, len(alunos))
    return saida
