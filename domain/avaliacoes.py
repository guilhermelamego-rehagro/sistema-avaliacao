"""Persistência de avaliações de grupo e orientador."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from config import ABAS_AVALIACAO
from data.sheets import ler_aba, limpar_cache_planilhas, planilha

_COLUNAS_GRUPO = ABAS_AVALIACAO["Avaliacao_Grupo"]


def _agora() -> str:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")


def _normalizar_df_grupo(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out.columns = out.columns.astype(str).str.strip()
    return out


def _sala_vazia(serie: pd.Series) -> pd.Series:
    return serie.astype(str).str.strip().isin(["", "nan", "none", "NaN", "None"])


def _garantir_header_avaliacao_grupo(ws) -> list[str]:
    headers = [str(h).strip() for h in ws.row_values(1) if str(h).strip()]
    if not headers:
        ws.append_row(_COLUNAS_GRUPO)
        return list(_COLUNAS_GRUPO)
    if "Sala" not in headers and "ID_Disciplina" in headers:
        idx = headers.index("ID_Disciplina") + 1
        headers.insert(idx, "Sala")
        ws.update(range_name="A1", values=[headers])
    return headers


def filtrar_avaliacoes_grupo(
    df: pd.DataFrame,
    id_disciplina: str | None = None,
    id_ciclo: str | None = None,
    grupo: str | None = None,
    sala: str | None = None,
) -> pd.DataFrame:
    filtro = _normalizar_df_grupo(df)
    if filtro.empty:
        return filtro

    if id_disciplina is not None:
        filtro = filtro[
            filtro["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip()
        ]
    if id_ciclo is not None:
        filtro = filtro[
            filtro["ID_Ciclo"].astype(str).str.strip() == str(id_ciclo).strip()
        ]
    if grupo is not None:
        filtro = filtro[
            filtro["Grupo"].astype(str).str.strip() == str(grupo).strip()
        ]
    if sala and "Sala" in filtro.columns:
        com_sala = filtro[filtro["Sala"].astype(str).str.strip() == str(sala).strip()]
        legado = filtro[_sala_vazia(filtro["Sala"])]
        if not com_sala.empty:
            filtro = com_sala
        elif not legado.empty:
            filtro = legado
        else:
            filtro = com_sala
    return filtro


def parse_nota_entrega(valor) -> float | None:
    if valor is None or str(valor).strip() == "":
        return None
    try:
        nota = round(float_nota_planilha(valor), 1)
    except (ValueError, TypeError):
        return None
    if 0 <= nota <= 5:
        return nota
    return None


def float_nota_planilha(valor) -> float:
    """Converte nota da planilha (aceita 0,5 ou 0.5)."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto:
        return 0.0
    if "," in texto:
        if "." in texto:
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", ".")
    return float(texto)


def formatar_nota_entrega(nota: float) -> str:
    """Exibe nota com vírgula decimal (padrão BR)."""
    return f"{float(nota):.1f}".replace(".", ",")


TIPO_AVALIACAO_CONFERENCIA = "Conferencia"


def _eh_override_conferencia(row) -> bool:
    """Lançamento da conferência do coordenador (substitui a média da banca)."""
    tipo = str(row.get("Tipo", "") or "").strip().lower()
    if tipo in {"conferencia", "conferência", "override", "override_coord"}:
        return True
    comentario = str(row.get("Comentario", "") or "").strip().lower()
    return comentario.startswith("lançamento coordenador") or comentario.startswith(
        "lancamento coordenador"
    ) or comentario.startswith("conferência coordenador") or comentario.startswith(
        "conferencia coordenador"
    )


def salvar_avaliacao_grupo(
    id_ciclo: str,
    nome_ciclo: str,
    id_disciplina: str,
    sala: str,
    grupo: str,
    nota_apresentacao: float,
    nota_conteudo: float,
    comentario: str,
    email_avaliador: str,
    nome_avaliador: str,
    tipo: str = "Ciclo",
):
    nota_total = round(float(nota_apresentacao) + float(nota_conteudo), 1)
    ws = planilha.worksheet("Avaliacao_Grupo")
    headers = _garantir_header_avaliacao_grupo(ws)
    dados = {
        "Data": _agora(),
        "ID_Ciclo": id_ciclo,
        "Nome_Ciclo": nome_ciclo,
        "ID_Disciplina": id_disciplina,
        "Sala": sala,
        "Grupo": grupo,
        "Nota_Apresentacao": nota_apresentacao,
        "Nota_Conteudo": nota_conteudo,
        "Nota_Total": nota_total,
        "Comentario": comentario,
        "Email_Avaliador": email_avaliador,
        "Nome_Avaliador": nome_avaliador,
        "Tipo": tipo,
    }
    linha = [dados.get(col, "") for col in headers]
    ws.append_row(linha)
    limpar_cache_planilhas()
    return nota_total


def salvar_avaliacao_orientador(
    id_ciclo: str,
    nome_ciclo: str,
    id_disciplina: str,
    email_aluno: str,
    nome_aluno: str,
    grupo: str,
    nota: float,
    email_orientador: str,
    tipo: str = "Ciclo",
):
    ws = planilha.worksheet("Avaliacao_Orientador")
    ws.append_row(
        [
            _agora(),
            id_ciclo,
            nome_ciclo,
            id_disciplina,
            email_aluno,
            nome_aluno,
            grupo,
            email_orientador,
            nota,
            tipo,
        ]
    )
    limpar_cache_planilhas()


def obter_avaliacao_grupo(
    id_ciclo: str,
    grupo: str,
    sala: str = "",
    id_disciplina: str | None = None,
    email_avaliador: str | None = None,
) -> dict | None:
    """Última avaliação do grupo. Com email_avaliador, só a desse professor."""
    try:
        df = ler_aba("Avaliacao_Grupo")
    except Exception:
        return None
    if df.empty:
        return None

    filtro = filtrar_avaliacoes_grupo(df, id_disciplina, id_ciclo, grupo, sala or None)
    if filtro.empty:
        return None
    if email_avaliador is not None:
        email = str(email_avaliador).strip().lower()
        if not email or email in {"nan", "none"}:
            return None
        if "Email_Avaliador" not in filtro.columns:
            return None
        filtro = filtro[
            filtro["Email_Avaliador"].astype(str).str.lower().str.strip() == email
        ]
        if filtro.empty:
            return None
    if "Data" in filtro.columns:
        filtro = filtro.copy()
        filtro["_ordem"] = pd.to_datetime(filtro["Data"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
        filtro = filtro.sort_values("_ordem", na_position="last")
    row = filtro.iloc[-1]
    return {
        "nota_apresentacao": float_nota_planilha(row.get("Nota_Apresentacao", 0)),
        "nota_conteudo": float_nota_planilha(row.get("Nota_Conteudo", 0)),
        "nota_total": float_nota_planilha(row.get("Nota_Total", 0)),
        "comentario": str(row.get("Comentario", "")),
        "email_avaliador": str(row.get("Email_Avaliador", "")).strip().lower(),
        "nome_avaliador": str(row.get("Nome_Avaliador", "")).strip(),
    }


def obter_media_avaliacao_grupo(
    id_ciclo: str,
    grupo: str,
    sala: str = "",
    id_disciplina: str | None = None,
) -> dict | None:
    """Nota oficial do grupo: override da conferência, senão média por professor."""
    try:
        df = ler_aba("Avaliacao_Grupo")
    except Exception:
        return None
    if df.empty:
        return None

    filtro = filtrar_avaliacoes_grupo(df, id_disciplina, id_ciclo, grupo, sala or None)
    if filtro.empty:
        return None

    filtro = filtro.copy()
    if "Email_Avaliador" not in filtro.columns:
        filtro["Email_Avaliador"] = ""
    if "Tipo" not in filtro.columns:
        filtro["Tipo"] = ""
    if "Comentario" not in filtro.columns:
        filtro["Comentario"] = ""
    if "Data" in filtro.columns:
        filtro["_ordem"] = pd.to_datetime(
            filtro["Data"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
        )
        filtro = filtro.sort_values("_ordem", na_position="last")

    overrides = filtro[filtro.apply(_eh_override_conferencia, axis=1)]
    if not overrides.empty:
        row = overrides.iloc[-1]
        return {
            "nota_apresentacao": float_nota_planilha(row.get("Nota_Apresentacao", 0)),
            "nota_conteudo": float_nota_planilha(row.get("Nota_Conteudo", 0)),
            "nota_total": float_nota_planilha(row.get("Nota_Total", 0)),
            "n_avaliadores": 1,
            "origem": "conferencia",
            "comentario": str(row.get("Comentario", "")),
            "nome_avaliador": str(row.get("Nome_Avaliador", "")).strip(),
        }

    banca = filtro[~filtro.apply(_eh_override_conferencia, axis=1)]
    if banca.empty:
        return None

    banca["_avaliador"] = banca["Email_Avaliador"].astype(str).str.lower().str.strip()
    ultimas = banca.groupby("_avaliador", sort=False).tail(1)
    if ultimas.empty:
        return None

    aps = [float_nota_planilha(v) for v in ultimas["Nota_Apresentacao"].tolist()]
    cts = [float_nota_planilha(v) for v in ultimas["Nota_Conteudo"].tolist()]
    tots = [float_nota_planilha(v) for v in ultimas["Nota_Total"].tolist()]
    n = len(ultimas)
    return {
        "nota_apresentacao": round(sum(aps) / n, 2),
        "nota_conteudo": round(sum(cts) / n, 2),
        "nota_total": round(sum(tots) / n, 2),
        "n_avaliadores": n,
        "origem": "media_banca",
        "comentario": "",
    }


def obter_media_avaliacao_grupo_aluno(
    id_ciclo: str,
    grupo: str,
    sala: str = "",
    id_disciplina: str | None = None,
) -> dict | None:
    """Nota do grupo liberada ao aluno (mesma regra da tela Avaliação do grupo).

    Libera se houver conferência do coordenador, ou 2+ avaliações da banca,
    ou o ciclo já estiver inativo (fora da janela Data início/Data fim das pares).
    """
    from domain.ciclos import ciclo_inativo

    oficial = obter_media_avaliacao_grupo(id_ciclo, grupo, sala, id_disciplina)
    if not oficial:
        return None
    if oficial.get("origem") == "conferencia":
        return oficial
    n = int(oficial.get("n_avaliadores") or 0)
    if n >= 2 or ciclo_inativo(id_ciclo):
        return oficial
    return None


def obter_nota_orientador(id_ciclo: str, email_aluno: str) -> float | None:
    try:
        df = ler_aba("Avaliacao_Orientador")
    except Exception:
        return None
    if df.empty:
        return None

    filtro = df[
        (df["ID_Ciclo"].astype(str).str.strip() == str(id_ciclo).strip())
        & (df["Email_Aluno"].astype(str).str.lower().str.strip() == str(email_aluno).lower().strip())
    ]
    if filtro.empty:
        return None
    if "Data" in filtro.columns:
        filtro = filtro.copy()
        filtro["_ordem"] = pd.to_datetime(filtro["Data"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
        filtro = filtro.sort_values("_ordem", na_position="last")
    return float_nota_planilha(filtro.iloc[-1]["Nota"])


def carregar_mapa_notas_orientador(id_disciplina: str) -> dict[tuple[str, str], float]:
    """Retorna {(email, id_ciclo): nota} com a última nota lançada por aluno/ciclo."""
    try:
        df = ler_aba("Avaliacao_Orientador")
    except Exception:
        return {}
    if df.empty:
        return {}

    df = df[df["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip()]
    if "Data" in df.columns:
        df = df.copy()
        df["_ordem"] = pd.to_datetime(df["Data"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
        df = df.sort_values("_ordem", na_position="last")
    mapa: dict[tuple[str, str], float] = {}
    for (email, id_ciclo), grupo in df.groupby(
        [df["Email_Aluno"].astype(str).str.lower().str.strip(), df["ID_Ciclo"].astype(str).str.strip()]
    ):
        mapa[(email, id_ciclo)] = float_nota_planilha(grupo.iloc[-1]["Nota"])
    return mapa


def carregar_mapa_avaliacoes_grupo(
    id_disciplina: str,
    email_avaliador: str | None = None,
    *,
    media: bool = False,
    somente_conferencia: bool = False,
) -> dict[tuple[str, str, str], dict]:
    """Retorna {(grupo, sala, id_ciclo): avaliação}.

    - email_avaliador: última nota desse professor
    - media=True: nota oficial (override da conferência ou média da banca)
    - somente_conferencia: só lançamentos da conferência do coordenador
    - padrão: última nota de qualquer avaliador (legado)
    """
    try:
        df = ler_aba("Avaliacao_Grupo")
    except Exception:
        return {}
    if df.empty:
        return {}

    df = filtrar_avaliacoes_grupo(df, id_disciplina=id_disciplina)
    if df.empty:
        return {}

    if "Sala" not in df.columns:
        df = df.copy()
        df["Sala"] = ""
    if "Email_Avaliador" not in df.columns:
        df = df.copy()
        df["Email_Avaliador"] = ""
    if "Tipo" not in df.columns:
        df = df.copy()
        df["Tipo"] = ""
    if "Comentario" not in df.columns:
        df = df.copy()
        df["Comentario"] = ""

    if somente_conferencia:
        df = df[df.apply(_eh_override_conferencia, axis=1)]
        if df.empty:
            return {}

    if email_avaliador:
        email = str(email_avaliador).strip().lower()
        df = df[df["Email_Avaliador"].astype(str).str.lower().str.strip() == email]
        if df.empty:
            return {}

    if "Data" in df.columns:
        df = df.copy()
        df["_ordem"] = pd.to_datetime(df["Data"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
        df = df.sort_values("_ordem", na_position="last")

    mapa: dict[tuple[str, str, str], dict] = {}
    chaves = [
        df["Grupo"].astype(str).str.strip(),
        df["Sala"].astype(str).str.strip(),
        df["ID_Ciclo"].astype(str).str.strip(),
    ]
    if media and not email_avaliador:
        df = df.copy()
        if "Tipo" not in df.columns:
            df["Tipo"] = ""
        if "Comentario" not in df.columns:
            df["Comentario"] = ""
        df["_avaliador"] = df["Email_Avaliador"].astype(str).str.lower().str.strip()
        for (grupo, sala, id_ciclo), grupo_df in df.groupby(
            [
                df["Grupo"].astype(str).str.strip(),
                df["Sala"].astype(str).str.strip(),
                df["ID_Ciclo"].astype(str).str.strip(),
            ]
        ):
            overrides = grupo_df[grupo_df.apply(_eh_override_conferencia, axis=1)]
            if not overrides.empty:
                row = overrides.iloc[-1]
                mapa[(grupo, sala, id_ciclo)] = {
                    "nota_apresentacao": float_nota_planilha(row.get("Nota_Apresentacao", 0)),
                    "nota_conteudo": float_nota_planilha(row.get("Nota_Conteudo", 0)),
                    "nota_total": float_nota_planilha(row.get("Nota_Total", 0)),
                    "n_avaliadores": 1,
                    "origem": "conferencia",
                }
                continue
            banca = grupo_df[~grupo_df.apply(_eh_override_conferencia, axis=1)]
            if banca.empty:
                continue
            ultimas = banca.groupby("_avaliador", sort=False).tail(1)
            if ultimas.empty:
                continue
            n = len(ultimas)
            ap = sum(float_nota_planilha(v) for v in ultimas["Nota_Apresentacao"].tolist()) / n
            ct = sum(float_nota_planilha(v) for v in ultimas["Nota_Conteudo"].tolist()) / n
            tot = sum(float_nota_planilha(v) for v in ultimas["Nota_Total"].tolist()) / n
            mapa[(grupo, sala, id_ciclo)] = {
                "nota_apresentacao": round(ap, 2),
                "nota_conteudo": round(ct, 2),
                "nota_total": round(tot, 2),
                "n_avaliadores": n,
                "origem": "media_banca",
            }
        return mapa

    for (grupo, sala, id_ciclo), grupo_df in df.groupby(chaves):
        row = grupo_df.iloc[-1]
        mapa[(grupo, sala, id_ciclo)] = {
            "nota_apresentacao": float_nota_planilha(row.get("Nota_Apresentacao", 0)),
            "nota_conteudo": float_nota_planilha(row.get("Nota_Conteudo", 0)),
            "nota_total": float_nota_planilha(row.get("Nota_Total", 0)),
        }
    return mapa


def carregar_painel_conferencia(
    id_disciplina: str,
) -> dict[tuple[str, str, str], dict]:
    """Painel da conferência: nota oficial + detalhe por avaliador.

    Retorna {(grupo, sala, id_ciclo): {
        oficial: {nota_apresentacao, nota_conteudo, nota_total, origem, n_avaliadores},
        avaliadores: [{nome, email, notas..., eh_conferencia}],
    }}
    """
    try:
        df = ler_aba("Avaliacao_Grupo")
    except Exception:
        return {}
    if df.empty:
        return {}

    df = filtrar_avaliacoes_grupo(df, id_disciplina=id_disciplina)
    if df.empty:
        return {}

    df = df.copy()
    if "Sala" not in df.columns:
        df["Sala"] = ""
    if "Email_Avaliador" not in df.columns:
        df["Email_Avaliador"] = ""
    if "Nome_Avaliador" not in df.columns:
        df["Nome_Avaliador"] = ""
    if "Tipo" not in df.columns:
        df["Tipo"] = ""
    if "Comentario" not in df.columns:
        df["Comentario"] = ""
    if "Data" in df.columns:
        df["_ordem"] = pd.to_datetime(df["Data"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
        df = df.sort_values("_ordem", na_position="last")

    df["_avaliador"] = df["Email_Avaliador"].astype(str).str.lower().str.strip()
    df["_conferencia"] = df.apply(_eh_override_conferencia, axis=1)

    painel: dict[tuple[str, str, str], dict] = {}
    for (grupo, sala, id_ciclo), grupo_df in df.groupby(
        [
            df["Grupo"].astype(str).str.strip(),
            df["Sala"].astype(str).str.strip(),
            df["ID_Ciclo"].astype(str).str.strip(),
        ]
    ):
        avaliadores = []
        for _, bloco in grupo_df.groupby("_avaliador", sort=False):
            row = bloco.iloc[-1]
            nome = str(row.get("Nome_Avaliador", "")).strip() or str(
                row.get("Email_Avaliador", "")
            ).strip()
            avaliadores.append(
                {
                    "nome": nome,
                    "email": str(row.get("Email_Avaliador", "")).strip().lower(),
                    "nota_apresentacao": float_nota_planilha(row.get("Nota_Apresentacao", 0)),
                    "nota_conteudo": float_nota_planilha(row.get("Nota_Conteudo", 0)),
                    "nota_total": float_nota_planilha(row.get("Nota_Total", 0)),
                    "eh_conferencia": bool(row.get("_conferencia")),
                }
            )

        overrides = grupo_df[grupo_df["_conferencia"]]
        if not overrides.empty:
            row = overrides.iloc[-1]
            oficial = {
                "nota_apresentacao": float_nota_planilha(row.get("Nota_Apresentacao", 0)),
                "nota_conteudo": float_nota_planilha(row.get("Nota_Conteudo", 0)),
                "nota_total": float_nota_planilha(row.get("Nota_Total", 0)),
                "n_avaliadores": 1,
                "origem": "conferencia",
            }
        else:
            banca = grupo_df[~grupo_df["_conferencia"]]
            if banca.empty:
                continue
            ultimas = banca.groupby("_avaliador", sort=False).tail(1)
            n = len(ultimas)
            oficial = {
                "nota_apresentacao": round(
                    sum(float_nota_planilha(v) for v in ultimas["Nota_Apresentacao"]) / n, 2
                ),
                "nota_conteudo": round(
                    sum(float_nota_planilha(v) for v in ultimas["Nota_Conteudo"]) / n, 2
                ),
                "nota_total": round(
                    sum(float_nota_planilha(v) for v in ultimas["Nota_Total"]) / n, 2
                ),
                "n_avaliadores": n,
                "origem": "media_banca",
            }

        painel[(grupo, sala, id_ciclo)] = {
            "oficial": oficial,
            "avaliadores": sorted(avaliadores, key=lambda a: a["nome"].lower()),
        }
    return painel


def listar_comentarios_banca_grupo(
    id_disciplina: str,
    grupo: str,
    sala: str = "",
) -> list[dict]:
    """Último lançamento de cada professor, por ciclo, para o grupo do aluno."""
    try:
        df = ler_aba("Avaliacao_Grupo")
    except Exception:
        return []
    if df.empty:
        return []

    filtro = filtrar_avaliacoes_grupo(
        df, id_disciplina=id_disciplina, grupo=grupo, sala=sala or None
    )
    if filtro.empty:
        return []

    filtro = filtro.copy()
    if "Sala" not in filtro.columns:
        filtro["Sala"] = ""
    if "Nome_Avaliador" not in filtro.columns:
        filtro["Nome_Avaliador"] = ""
    if "Email_Avaliador" not in filtro.columns:
        filtro["Email_Avaliador"] = ""
    if "Comentario" not in filtro.columns:
        filtro["Comentario"] = ""
    if "Nome_Ciclo" not in filtro.columns:
        filtro["Nome_Ciclo"] = ""
    if "Tipo" not in filtro.columns:
        filtro["Tipo"] = ""

    if "Data" in filtro.columns:
        filtro["_ordem"] = pd.to_datetime(
            filtro["Data"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
        )
        filtro = filtro.sort_values("_ordem", na_position="last")

    filtro["_ciclo"] = filtro["ID_Ciclo"].astype(str).str.strip()
    filtro["_avaliador"] = filtro["Email_Avaliador"].astype(str).str.lower().str.strip()
    filtro["_conferencia"] = filtro.apply(_eh_override_conferencia, axis=1)

    registros: list[dict] = []
    for _, bloco in filtro.groupby(["_ciclo", "_avaliador"], sort=False):
        row = bloco.iloc[-1]
        comentario = str(row.get("Comentario", "") or "").strip()
        eh_conf = bool(row.get("_conferencia"))
        registros.append(
            {
                "id_ciclo": str(row.get("ID_Ciclo", "")).strip(),
                "nome_ciclo": str(row.get("Nome_Ciclo", "")).strip(),
                "nome_avaliador": str(row.get("Nome_Avaliador", "")).strip()
                or str(row.get("Email_Avaliador", "")).strip(),
                "email_avaliador": str(row.get("Email_Avaliador", "")).strip().lower(),
                "comentario": comentario,
                "nota_apresentacao": float_nota_planilha(row.get("Nota_Apresentacao", 0)),
                "nota_conteudo": float_nota_planilha(row.get("Nota_Conteudo", 0)),
                "nota_total": float_nota_planilha(row.get("Nota_Total", 0)),
                "data": str(row.get("Data", "")).strip(),
                "eh_conferencia": eh_conf,
            }
        )
    return registros


def buscar_avaliacao_grupo_mapa(
    mapa: dict[tuple[str, str, str], dict],
    grupo: str,
    sala: str,
    id_ciclo: str,
) -> dict | None:
    grupo = str(grupo).strip()
    sala = str(sala).strip()
    id_ciclo = str(id_ciclo).strip()
    return mapa.get((grupo, sala, id_ciclo)) or mapa.get((grupo, "", id_ciclo))


def formatar_nota_grid(nota: float) -> str:
    """Exibe nota com uma casa decimal (evita 9.9 virar 99)."""
    return f"{float(nota):.1f}"


def parse_nota_orientador(valor) -> float | None:
    if valor is None:
        return None
    texto = str(valor).strip().replace(",", ".")
    if not texto:
        return None
    try:
        nota = round(float(texto), 1)
    except ValueError:
        return None
    if 0 <= nota <= 10:
        return nota
    return None


def importar_atividades_canvas(df_import: pd.DataFrame, id_disciplina: str) -> int:
    ws = planilha.worksheet("Atividades_Individuais")
    agora = _agora()
    linhas = []
    for _, row in df_import.iterrows():
        linhas.append(
            [
                id_disciplina,
                str(row.get("Semana", "")),
                str(row.get("Atividade", "")),
                str(row.get("Email_Aluno", "")).strip().lower(),
                str(row.get("Nome_Aluno", "")),
                float(row.get("Nota", 0)),
                "Canvas",
                agora,
            ]
        )
    if linhas:
        ws.append_rows(linhas)
        limpar_cache_planilhas()
    return len(linhas)
