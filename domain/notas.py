"""Motor de cálculo de notas da disciplina."""

from __future__ import annotations

import pandas as pd

from config import PESO_ORIENTADOR, PESO_PARES
from data.sheets import ler_aba
from domain.avaliacoes import formatar_nota_entrega, obter_avaliacao_grupo, obter_nota_orientador
from domain.ciclos import ciclo_inativo
from domain.componentes import carregar_componentes_disciplina
from domain.encontro_presencial import resolver_id_ciclo_componente
from domain.presenca import calcular_matriz_dailies


def calcular_nota_pares(media_0_5: float, realizou_avaliacao: bool) -> float:
    multiplicador = 2 if realizou_avaliacao else 1
    return float(media_0_5) * multiplicador


def calcular_nota_ciclo(
    nota_orientador_0_10: float,
    nota_pares_0_10: float,
    nota_grupo_0_10: float,
) -> float:
    componente = (nota_orientador_0_10 * PESO_ORIENTADOR) + (nota_pares_0_10 * PESO_PARES)
    return round(componente * float(nota_grupo_0_10), 2)


def _situacao_pares_ciclo(email: str, id_ciclo: str) -> tuple[float | None, bool]:
    """Retorna (nota de pares 0-10 ou None, se o aluno já enviou a avaliação)."""
    try:
        df = ler_aba("Avaliacoes")
    except Exception:
        return None, False

    if df.empty:
        return None, False

    id_c = str(id_ciclo).strip()
    email_l = email.lower().strip()
    df_c = df[df["ID_Ciclo"].astype(str).str.strip() == id_c]

    realizou = not df_c[df_c["Email_Avaliador"].astype(str).str.lower().str.strip() == email_l].empty
    recebidas = df_c[df_c["Email_Avaliado"].astype(str).str.lower().str.strip() == email_l]
    if recebidas.empty:
        return None, realizou

    media = pd.to_numeric(recebidas["Nota"], errors="coerce").mean()
    if pd.isna(media):
        return None, realizou
    return calcular_nota_pares(media, realizou), realizou


def _nota_pares_ciclo(email: str, id_ciclo: str) -> float | None:
    nota, _ = _situacao_pares_ciclo(email, id_ciclo)
    return nota


def _nota_grupo_ciclo(grupo: str, id_ciclo: str, sala: str = "") -> float | None:
    aval = obter_avaliacao_grupo(id_ciclo, grupo, sala)
    if not aval:
        return None
    return float(aval["nota_total"])


def _montar_detalhe_ciclo(
    nota_grupo: float | None,
    nota_pares: float | None,
    nota_orientador: float | None,
) -> str:
    """Sempre reserva Grupo, Pares e Orientador; usa — se a nota ainda não saiu."""

    def _fmt(nota: float | None) -> str:
        return formatar_nota_entrega(nota) if nota is not None else "—"

    return (
        f"Grupo {_fmt(nota_grupo)} | "
        f"Pares {_fmt(nota_pares)} | "
        f"Orientador {_fmt(nota_orientador)}"
    )


def _resolver_nota_pares_ciclo(
    email: str,
    id_ciclo: str,
    nota_orientador: float | None,
    nota_grupo: float | None,
) -> float | None:
    """Pares só aparece depois que o aluno avalia, ou quando o ciclo já encerrou."""
    nota_pares, realizou = _situacao_pares_ciclo(email, id_ciclo)
    ciclo_encerrado = ciclo_inativo(id_ciclo)

    if not ciclo_encerrado and not realizou:
        return None

    if (
        nota_pares is None
        and nota_orientador is not None
        and nota_grupo is not None
        and ciclo_encerrado
    ):
        return 0.0
    return nota_pares


def _nota_atividades(email: str, id_disciplina: str) -> tuple[float | None, str]:
    try:
        df = ler_aba("Atividades_Individuais")
    except Exception:
        return None, "Sem atividades importadas"

    if df.empty:
        return None, "Sem atividades importadas"

    filtro = df[
        (df["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip())
        & (df["Email_Aluno"].astype(str).str.lower().str.strip() == email.lower().strip())
    ]
    if filtro.empty:
        return None, "Sem notas de atividades"

    media = pd.to_numeric(filtro["Nota"], errors="coerce").mean()
    return round(float(media), 1), f"Média de {len(filtro)} atividade(s)"


def _nota_dailies(email: str) -> tuple[float | None, str]:
    df = calcular_matriz_dailies(email)
    if df.empty:
        return None, "Sem calendário de dailies"

    vivido = df[df["Status_Tecnico"] != "Futuro"]
    if vivido.empty:
        return None, "Nenhuma daily realizada ainda"

    pres = len(vivido[vivido["Status_Aluno"] == "Presente"])
    pct = pres / len(vivido) * 100
    return round(pct, 1), f"{pres}/{len(vivido)} reuniões"


def calcular_boletim_aluno(email: str, id_disciplina: str, grupo: str, sala: str = "") -> pd.DataFrame:
    componentes = carregar_componentes_disciplina(id_disciplina)
    linhas = []

    for _, comp in componentes.iterrows():
        tipo = str(comp["Tipo"]).strip()
        nome = str(comp["Nome"]).strip()
        peso = float(comp["Peso"])
        id_ciclo_cfg = str(comp.get("ID_Ciclo", "")).strip()
        id_ciclo, origem_ciclo = resolver_id_ciclo_componente(tipo, id_ciclo_cfg, id_disciplina)

        nota: float | None = None
        detalhe = ""

        if tipo in ("Ciclo", "Entrega_Final") and id_ciclo:
            nota_ori = obter_nota_orientador(id_ciclo, email)
            nota_grp = _nota_grupo_ciclo(grupo, id_ciclo, sala)
            nota_par = _resolver_nota_pares_ciclo(email, id_ciclo, nota_ori, nota_grp)
            detalhe = _montar_detalhe_ciclo(nota_grp, nota_par, nota_ori)
            if origem_ciclo:
                detalhe += f" · iguais a {origem_ciclo}"

            if nota_ori is not None and nota_par is not None and nota_grp is not None:
                nota = calcular_nota_ciclo(nota_ori, nota_par, nota_grp)

        elif tipo == "Reuniao_Diaria":
            nota, detalhe = _nota_dailies(email)

        elif tipo == "Atividade_Individual":
            nota, detalhe = _nota_atividades(email, id_disciplina)

        contribuicao = (nota * peso / 100) if nota is not None else None

        linhas.append(
            {
                "Componente": nome,
                "Peso (%)": peso,
                "Nota (0-100)": nota,
                "Contribuição": contribuicao,
                "Detalhe": detalhe,
            }
        )

    df = pd.DataFrame(linhas)
    return df


def nota_final_boletim(df_boletim: pd.DataFrame) -> float | None:
    if df_boletim.empty or df_boletim["Contribuição"].isna().any():
        contrib = df_boletim["Contribuição"].dropna()
        if contrib.empty:
            return None
        return round(float(contrib.sum()), 2)
    return round(float(df_boletim["Contribuição"].sum()), 2)
