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


def _flag(nome: str, padrao: bool | None = None) -> bool:
    """Sem o secret, vale ``padrao``; sem padrão, ligada só no teste."""
    from auth.supabase_auth import ambiente_app

    try:
        valor = st.secrets.get(nome)
    except Exception:
        valor = None
    if valor is None:
        return ambiente_app() == "teste" if padrao is None else padrao
    return str(valor).strip().lower() in {"true", "1", "sim", "yes"}


def feedback_ativo_alunos() -> bool:
    """Alunos veem "Meu feedback" (``feedback_aluno_ativo``)."""
    return _flag("feedback_aluno_ativo")


def feedback_ativo_professores() -> bool:
    """Docentes preparam e publicam; ligado por padrão, desliga com ``feedback_prof_ativo = false``."""
    return _flag("feedback_prof_ativo", padrao=True) or feedback_ativo_alunos()


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


_REGRA_FREQUENCIA = "Abaixo de 75% de presença na disciplina há reprovação por frequência."

# Sujeito das frases de nota (todos femininos: "... subiu neste ciclo").
_SUJEITO_NOTA = {
    "Pares_Media": "A avaliação dos colegas",
    "Orientador": "A avaliação da orientadora",
    "Banca": "A nota do grupo na banca",
    "Atividades_Media": "Sua média nas atividades individuais",
}


@dataclass(frozen=True)
class _Disciplina:
    """Acumulado da disciplina até o ciclo atual (``linha`` é a de ``combinar_resumos``)."""

    linha: pd.Series
    ciclos: str  # ex.: "Ciclos 1 a 3"


def _aulas(linha) -> str:
    return _contagem(linha["Aulas_Presentes"], linha["Aulas_Total"])


def _frase_bem(chave: str, linha, texto: str) -> str:
    return {
        "Pct_Aulas": f"Presença nas aulas: você esteve em {_aulas(linha)} aulas do ciclo.",
        "Pct_Dailies": f"Participação nas dailies: {_contagem(linha['Dailies_Presentes'], linha['Dailies_Total'])} do ciclo.",
        "Pares_Media": f"Seus colegas avaliaram muito bem sua contribuição no grupo neste ciclo ({texto}).",
        "Orientador": f"Ótima avaliação da sua orientadora neste ciclo ({texto}).",
        "Banca": f"Seu grupo foi muito bem na banca deste ciclo ({texto}).",
        "Atividades_Media": f"Atividades individuais do ciclo com ótimo resultado ({texto}).",
    }[chave]


def _frase_melhorar(chave: str, linha, texto: str, disc: _Disciplina | None, texto_disc: str, faixa_disc) -> str:
    if chave == "Pct_Aulas":
        frase = f"Você esteve em {_aulas(linha)} aulas do ciclo ({texto})."
        if disc and faixa_disc == ATENCAO:
            frase += f" Somando os {disc.ciclos}, são {_aulas(disc.linha)} aulas na disciplina ({texto_disc})."
        elif disc and faixa_disc:
            frase += f" Na disciplina, somando os {disc.ciclos}, sua presença ainda está em {texto_disc} ({_aulas(disc.linha)})."
        return f"{frase} {_REGRA_FREQUENCIA}"
    if chave == "Pct_Dailies":
        frase = f"Você participou de {_contagem(linha['Dailies_Presentes'], linha['Dailies_Total'])} dailies do ciclo."
        if disc and faixa_disc == ATENCAO:
            frase += (
                f" Somando os {disc.ciclos}, foram "
                f"{_contagem(disc.linha['Dailies_Presentes'], disc.linha['Dailies_Total'])} ({texto_disc})."
            )
        return f"{frase} Elas são o momento de alinhar o trabalho com o grupo e com a orientadora."

    frase = {
        "Pares_Media": f"A avaliação dos colegas neste ciclo ficou em {texto}.",
        "Orientador": f"A avaliação da orientadora neste ciclo ficou em {texto}.",
        "Banca": f"O grupo ficou com {texto} na banca deste ciclo.",
        "Atividades_Media": f"Sua média nas atividades individuais do ciclo ficou em {texto}.",
    }[chave]
    if disc and faixa_disc == ATENCAO:
        frase += f" Na disciplina, a média também está em atenção ({texto_disc})."
    elif disc and faixa_disc:
        frase += f" Na disciplina, a média está em {texto_disc}: vale retomar o ritmo dos ciclos anteriores."
    if chave == "Pares_Media":
        frase += " Leia os comentários em Resultados de pares."
    elif chave == "Banca":
        frase += " Releia os comentários da banca com o grupo."
    elif chave == "Atividades_Media":
        sem_nota = int(linha.get("Atividades_Sem_Nota") or 0)
        if sem_nota:
            frase += f" Há {sem_nota} atividade(s) sem nota lançada."
    return frase


def _frase_aulas_disciplina(linha, valor, texto: str, disc: _Disciplina, valor_disc, texto_disc: str) -> str:
    """Ciclo sem atenção, mas a presença somada da disciplina está abaixo de 75%."""
    total_ciclo = int(linha.get("Aulas_Total") or 0)
    if not total_ciclo:
        inicio = f"Somando os {disc.ciclos}, você esteve"
    elif valor is not None and valor_disc is not None and valor > valor_disc:
        inicio = f"Sua presença melhorou no ciclo ({_aulas(linha)} aulas), mas, somando os {disc.ciclos}, você esteve"
    else:
        inicio = f"No ciclo você esteve em {_aulas(linha)} aulas ({texto}), mas, somando os {disc.ciclos}, você esteve"
    return f"{inicio} em {_aulas(disc.linha)} aulas da disciplina ({texto_disc}). {_REGRA_FREQUENCIA}"


def _proximo_passo(chave: str, final: bool, aulas_disciplina_atencao: bool = False) -> str:
    futuro = "nos próximos projetos" if final else "no próximo ciclo"
    if chave == "Pct_Aulas" and aulas_disciplina_atencao and not final:
        return "Priorize estar presente em todas as próximas aulas: sua presença na disciplina precisa ficar em 75% ou mais."
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
    disc = _Disciplina(acumulado, titulo_ciclos(ciclos_acumulado or [])) if acumulado is not None else None
    metricas, bem, melhorar, atencao_chaves = [], [], [], []
    aulas_disciplina_atencao = False
    for m in METRICAS:
        v, f = _valor_e_faixa(m, linha)
        texto = _texto_valor(m, v)
        item = {"chave": m.chave, "titulo": m.titulo, "valor": v, "maximo": m.maximo,
                "cortes": list(m.cortes), "faixa": f, "texto": texto}
        va, fa, texto_disc = None, None, ""
        if disc:
            va, fa = _valor_e_faixa(m, acumulado)
            texto_disc = _texto_valor(m, va)
            item.update({"acumulado": va, "faixa_acumulado": fa, "texto_acumulado": texto_disc})
        metricas.append(item)

        if f == ATENCAO:
            melhorar.append(_frase_melhorar(m.chave, linha, texto, disc, texto_disc, fa))
            atencao_chaves.append(m.chave)
            if m.chave == "Pct_Aulas":
                aulas_disciplina_atencao = fa == ATENCAO
        elif m.chave == "Pct_Aulas" and fa == ATENCAO:
            melhorar.append(_frase_aulas_disciplina(linha, v, texto, disc, va, texto_disc))
            atencao_chaves.append(m.chave)
            aulas_disciplina_atencao = True
        elif m.chave in _SUJEITO_NOTA and fa == ATENCAO and f in (BOM, OTIMO):
            bem.append(
                f"{_SUJEITO_NOTA[m.chave]} subiu neste ciclo ({texto}); na disciplina, a média está em "
                f"{texto_disc} e pode chegar ao Bom mantendo esse ritmo."
            )
        elif f == OTIMO:
            frase = _frase_bem(m.chave, linha, texto)
            if m.chave in _SUJEITO_NOTA and fa == OTIMO:
                frase += f" A média na disciplina também está no Ótimo ({texto_disc})."
            bem.append(frase)

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
        proximo = _proximo_passo(principal, final, aulas_disciplina_atencao)
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
                "Sua presença no ciclo está em dia. As notas do ciclo aparecem aqui quando forem lançadas."
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
