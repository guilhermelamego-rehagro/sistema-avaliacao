"""Feedback do ciclo para o aluno: faixas por métrica e frases automáticas.

O conteúdo é montado a partir do resumo do Dossiê (``resumo_alunos``) e gravado como
retrato no momento em que a orientadora publica; o aluno só lê esse retrato.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from domain.dossie_aluno import ciclo_entrega_final, fmt_num, titulo_ciclos

ATENCAO = "Atenção"
BOM = "Bom"
OTIMO = "Ótimo"
FAIXAS = (ATENCAO, BOM, OTIMO)


@dataclass(frozen=True)
class Metrica:
    chave: str
    titulo: str
    maximo: float
    cortes: tuple[float, float]  # abaixo do 1º: Atenção; a partir do 2º: Ótimo
    unidade: str = ""


# Presença: abaixo de 75% reprova. Notas: 70% do máximo é a nota de aprovação.
METRICAS: tuple[Metrica, ...] = (
    Metrica("Pct_Aulas", "Presença nas aulas", 100, (75, 90), "%"),
    Metrica("Pct_Dailies", "Presença nas dailies", 100, (75, 90), "%"),
    Metrica("Pares_Media", "Avaliação dos colegas", 5, (3.5, 4.25)),
    Metrica("Orientador", "Avaliação da orientadora", 10, (7, 8.5)),
    Metrica("Banca", "Banca do grupo", 10, (7, 8.5)),
    Metrica("Atividades_Media", "Atividades individuais", 100, (70, 85)),
)
_POR_CHAVE = {m.chave: m for m in METRICAS}

# A partir do 2º ciclo, a régua mostra também o acumulado desde o 1º.
CICLO_MIN_ACUMULADO = 2

# Ordem em que um ponto de atenção vira o "próximo passo".
_PRIORIDADE = ("Pct_Aulas", "pares_nao_enviada", "Atividades_Media", "Pct_Dailies", "Pares_Media", "Orientador", "Banca")


def _flag(nome: str) -> bool:
    """Ligada no teste; em produção só com ``<nome> = true`` nos secrets."""
    from auth.supabase_auth import ambiente_app

    try:
        valor = st.secrets.get(nome)
    except Exception:
        valor = None
    if valor is None:
        return ambiente_app() == "teste"
    return str(valor).strip().lower() in {"true", "1", "sim", "yes"}


def feedback_ativo_alunos() -> bool:
    """Alunos veem "Meu feedback" (``feedback_aluno_ativo``)."""
    return _flag("feedback_aluno_ativo")


def feedback_ativo_professores() -> bool:
    """Docentes preparam e publicam (``feedback_prof_ativo``); ligado também quando os alunos já veem."""
    return _flag("feedback_prof_ativo") or feedback_ativo_alunos()


def _valor(linha, chave):
    v = linha.get(chave)
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)


def faixa(metrica: Metrica, valor: float | None) -> str | None:
    if valor is None:
        return None
    if valor < metrica.cortes[0]:
        return ATENCAO
    return OTIMO if valor >= metrica.cortes[1] else BOM


def _texto_valor(m: Metrica, valor: float | None) -> str:
    if valor is None:
        return "ainda sem nota"
    if m.unidade == "%":
        return f"{fmt_num(valor, 0)}%"
    return f"{fmt_num(valor)} de {fmt_num(m.maximo, 0)}"


def _contagem(presentes, total) -> str:
    return f"{int(presentes)} de {int(total)}"


def _frase_bem(chave: str, linha, texto: str) -> str:
    return {
        "Pct_Aulas": f"Presença nas aulas: você participou de {_contagem(linha['Aulas_Presentes'], linha['Aulas_Total'])}.",
        "Pct_Dailies": f"Participação nas dailies: {_contagem(linha['Dailies_Presentes'], linha['Dailies_Total'])}.",
        "Pares_Media": f"Seus colegas avaliaram muito bem sua contribuição no grupo ({texto}).",
        "Orientador": f"Ótima avaliação da sua orientadora ({texto}).",
        "Banca": f"Seu grupo foi muito bem na banca ({texto}).",
        "Atividades_Media": f"Atividades individuais com ótimo resultado ({texto}).",
    }[chave]


def _frase_melhorar(chave: str, linha, texto: str) -> str:
    if chave == "Pct_Aulas":
        return (
            f"Você esteve em {_contagem(linha['Aulas_Presentes'], linha['Aulas_Total'])} aulas ({texto}). "
            "Abaixo de 75% de presença há reprovação por frequência."
        )
    if chave == "Pct_Dailies":
        return (
            f"Você participou de {_contagem(linha['Dailies_Presentes'], linha['Dailies_Total'])} dailies. "
            "Elas são o momento de alinhar o trabalho com o grupo e com a orientadora."
        )
    if chave == "Pares_Media":
        return f"A avaliação dos colegas ficou em {texto}. Leia os comentários em Resultados de pares."
    if chave == "Orientador":
        return f"A avaliação da orientadora ficou em {texto}."
    if chave == "Banca":
        return f"O grupo ficou com {texto} na banca. Releia os comentários da banca com o grupo."
    sem_nota = int(linha.get("Atividades_Sem_Nota") or 0)
    extra = f" Há {sem_nota} atividade(s) sem nota lançada." if sem_nota else ""
    return f"Sua média nas atividades individuais ficou em {texto}.{extra}"


def _proximo_passo(chave: str, final: bool) -> str:
    futuro = "nos próximos projetos" if final else "no próximo ciclo"
    return {
        "Pct_Aulas": f"Priorize estar presente em todas as aulas {futuro}.",
        "pares_nao_enviada": "Envie a avaliação de pares em todo ciclo: ela também compõe a sua nota.",
        "Atividades_Media": f"Organize uma rotina para as atividades individuais e confira os prazos {futuro}.",
        "Pct_Dailies": f"Participe das dailies {futuro}: combine com o grupo um horário fixo.",
        "Pares_Media": f"Converse com o grupo sobre como você pode contribuir mais {futuro}.",
        "Orientador": "Procure sua orientadora para combinar o que priorizar.",
        "Banca": f"Use os comentários da banca para planejar, com o grupo, a entrega {'do próximo projeto' if final else 'do próximo ciclo'}.",
    }[chave]


@dataclass
class FeedbackAluno:
    email: str
    conteudo: dict
    atencoes: int
    sugestao_1x1: str


def _valor_e_faixa(m: Metrica, linha) -> tuple[float | None, str | None]:
    v = _valor(linha, m.chave)
    if m.chave not in ("Pct_Aulas", "Pct_Dailies"):
        return v, faixa(m, v)
    prefixo = m.chave.replace("Pct_", "")
    total = int(linha.get(f"{prefixo}_Total") or 0)
    if not total:
        return None, None
    f = faixa(m, v)
    # Com poucos encontros, uma única falta não deve virar ponto de atenção.
    if f == ATENCAO and total - int(linha.get(f"{prefixo}_Presentes") or 0) <= 1:
        f = BOM
    return v, f


def montar_feedback(
    linha: pd.Series,
    nome_ciclo: str,
    pares_encerrada: bool,
    acumulado: pd.Series | None = None,
    ciclos_acumulado: list[str] | None = None,
) -> FeedbackAluno:
    """Retrato do feedback de um aluno a partir da linha do resumo do Dossiê.

    ``acumulado`` é a linha de ``combinar_resumos`` dos ciclos em ``ciclos_acumulado`` (até o atual):
    vira o segundo ponto da régua e alerta de frequência acumulada.
    """
    final = ciclo_entrega_final(nome_ciclo)
    metricas, bem, melhorar, atencao_chaves = [], [], [], []
    for m in METRICAS:
        v, f = _valor_e_faixa(m, linha)
        texto = _texto_valor(m, v)
        item = {"chave": m.chave, "titulo": m.titulo, "valor": v, "maximo": m.maximo,
                "cortes": list(m.cortes), "faixa": f, "texto": texto}
        if acumulado is not None:
            va, fa = _valor_e_faixa(m, acumulado)
            item.update({"acumulado": va, "faixa_acumulado": fa, "texto_acumulado": _texto_valor(m, va)})
        metricas.append(item)
        if f == OTIMO:
            bem.append(_frase_bem(m.chave, linha, texto))
        elif f == ATENCAO:
            melhorar.append(_frase_melhorar(m.chave, linha, texto))
            atencao_chaves.append(m.chave)

    if acumulado is not None and "Pct_Aulas" not in atencao_chaves:
        va, fa = _valor_e_faixa(_POR_CHAVE["Pct_Aulas"], acumulado)
        if fa == ATENCAO:
            melhorar.append(
                f"Somando os {titulo_ciclos(ciclos_acumulado or []).lower()}, você esteve em "
                f"{_contagem(acumulado['Aulas_Presentes'], acumulado['Aulas_Total'])} aulas ({fmt_num(va, 0)}%). "
                "A reprovação por frequência considera a presença abaixo de 75% no total."
            )
            atencao_chaves.append("Pct_Aulas")

    esperados = int(linha.get("Pares_Esperados") or 0)
    feitos = int(linha.get("Pares_Feitos") or 0)
    pares_enviada = feitos >= esperados if esperados else None
    if pares_encerrada and pares_enviada is False:
        melhorar.append("Você não enviou a avaliação de pares deste ciclo.")
        atencao_chaves.append("pares_nao_enviada")
    elif pares_enviada:
        bem.append("Você enviou a avaliação de pares do ciclo.")

    principal = next((c for c in _PRIORIDADE if c in atencao_chaves), None)
    if principal:
        proximo = _proximo_passo(principal, final)
    else:
        boas = [(mm["valor"] / mm["maximo"], mm["titulo"]) for mm in metricas if mm["faixa"] == BOM]
        if boas:
            alvo = min(boas)[1].lower()
            proximo = (
                f"Leve para os próximos projetos o que funcionou neste e escolha {alvo} como ponto para chegar ao Ótimo."
                if final
                else f"Mantenha o ritmo e escolha {alvo} como ponto para chegar ao Ótimo no próximo ciclo."
            )
        elif not any(mm["faixa"] for mm in metricas if not mm["chave"].startswith("Pct_")):
            proximo = (
                "Sua presença está em dia. As notas do ciclo aparecem aqui quando forem lançadas."
                if any(mm["faixa"] for mm in metricas)
                else "Ainda não há dados suficientes deste ciclo."
            )
        else:
            proximo = (
                "Excelente projeto! Leve esse jeito de trabalhar para os próximos desafios."
                if final
                else "Excelente ciclo! Continue assim e ajude o grupo a manter o nível."
            )

    n_atencao = len(atencao_chaves)
    n_metricas_atencao = sum(1 for c in atencao_chaves if c in _POR_CHAVE)
    if "Pct_Aulas" in atencao_chaves:
        sugestao = "Presença nas aulas em atenção"
    elif n_metricas_atencao >= 2:
        sugestao = f"{n_metricas_atencao} indicadores em atenção"
    else:
        sugestao = ""

    conteudo = {
        "nome_ciclo": nome_ciclo,
        "ciclos_acumulado": list(ciclos_acumulado or []) if acumulado is not None else [],
        "final": final,
        "metricas": metricas,
        "bem": bem,
        "melhorar": melhorar,
        "proximo": proximo,
        "gerado_em": datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M"),
    }
    return FeedbackAluno(str(linha["Email"]), conteudo, n_atencao, sugestao)
