"""Agregações da avaliação do curso (métricas, didática, NPS e textos)."""

from __future__ import annotations

import io
import os
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from data.sheets import ler_aba
from utils.datas import parse_data_planilha_series


ITENS_METRICA = ("Auto Estudo", "Aulas ao Vivo", "Aplicabilidade", "Suporte")
ITEM_NPS = "NPS"
ITEM_DIDATICA = "Didática Professor"
ITENS_TEXTO = ("Que Bom", "Que Pena", "Que Tal")


def _texto(valor) -> str:
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    return str(valor).strip()


def _lista_filtro(valor: str | list[str] | None) -> list[str] | None:
    """Normaliza filtro: None / vazio / 'Todos'/'Todas' → sem filtro."""
    if valor is None:
        return None
    if isinstance(valor, str):
        txt = valor.strip()
        if not txt or txt in {"Todos", "Todas"}:
            return None
        return [txt]
    itens = [str(v).strip() for v in valor if str(v).strip() and str(v).strip() not in {"Todos", "Todas"}]
    return itens or None


def carregar_respostas_curso() -> pd.DataFrame:
    try:
        df = ler_aba("Respostas_Curso")
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    renomear = {}
    if "ID do Ciclo" in out.columns and "ID_Ciclo" not in out.columns:
        renomear["ID do Ciclo"] = "ID_Ciclo"
    if "Email do Aluno" in out.columns and "Email_Aluno" not in out.columns:
        renomear["Email do Aluno"] = "Email_Aluno"
    if "Nome do Aluno" in out.columns and "Nome_Aluno" not in out.columns:
        renomear["Nome do Aluno"] = "Nome_Aluno"
    if renomear:
        out = out.rename(columns=renomear)
    if "ID_Ciclo" in out.columns:
        out["ID_Ciclo"] = out["ID_Ciclo"].astype(str).str.strip()
    if "Email_Aluno" in out.columns:
        out["Email_Aluno"] = out["Email_Aluno"].astype(str).str.strip().str.lower()
    if "Item" in out.columns:
        out["Item"] = out["Item"].astype(str).str.strip()
    if "Professor" in out.columns:
        out["Professor"] = out["Professor"].astype(str).str.strip()
    if "Disciplina" in out.columns:
        out["Disciplina"] = out["Disciplina"].astype(str).str.strip()
    if "Ciclo" in out.columns:
        out["Ciclo"] = out["Ciclo"].astype(str).str.strip()
    if "Resposta" in out.columns:
        out["Resposta"] = out["Resposta"]
    return out


def filtrar_respostas(
    df: pd.DataFrame,
    *,
    id_ciclo: str | list[str] | None = None,
    disciplina: str | list[str] | None = None,
    sala: str | list[str] | None = None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    out = df
    ciclos = _lista_filtro(id_ciclo)
    discs = _lista_filtro(disciplina)
    salas = _lista_filtro(sala)
    if ciclos and "ID_Ciclo" in out.columns:
        out = out[out["ID_Ciclo"].isin(ciclos)]
    if discs and "Disciplina" in out.columns:
        out = out[out["Disciplina"].isin(discs)]
    if salas and "Sala" in out.columns:
        out = out[out["Sala"].isin(salas)]
    return out


def anexar_sala(df: pd.DataFrame, df_entrancia: pd.DataFrame | None) -> pd.DataFrame:
    """Sala vem da Entrância (e-mail × disciplina); Respostas_Curso não guarda sala."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if df_entrancia is None or df_entrancia.empty:
        out["Sala"] = ""
        return out
    ent = df_entrancia.copy()
    ent.columns = [str(c).strip() for c in ent.columns]
    col_email = next(
        (c for c in ("Email_Pessoal", "Email_Aluno", "Email") if c in ent.columns),
        None,
    )
    if not col_email or "Sala" not in ent.columns:
        out["Sala"] = ""
        return out
    por_chave: dict[tuple[str, str], str] = {}
    por_email: dict[str, str] = {}
    for _, row in ent.iterrows():
        email = _texto(row.get(col_email)).lower()
        if not email:
            continue
        sala = _texto(row.get("Sala"))
        if not sala:
            continue
        codigo = _texto(row.get("ID_Disciplina")).casefold()
        por_chave[(codigo, email)] = sala
        por_email.setdefault(email, sala)

    emails = out["Email_Aluno"].map(_texto).str.lower() if "Email_Aluno" in out.columns else pd.Series([""] * len(out))
    codigos = (
        out["Codigo_Disciplina"].map(_texto).str.casefold()
        if "Codigo_Disciplina" in out.columns
        else pd.Series([""] * len(out), index=out.index)
    )
    out["Sala"] = [
        por_chave.get((cod, mail)) or por_email.get(mail, "")
        for cod, mail in zip(codigos, emails)
    ]
    return out


def salas_disponiveis(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty or "Sala" not in df.columns:
        return []
    return sorted(
        {s for s in df["Sala"].map(_texto).tolist() if s},
        key=lambda x: (len(x), x),
    )


def _fmt_data_br(valor) -> str:
    if valor is None:
        return "—"
    try:
        if pd.isna(valor):
            return "—"
    except (TypeError, ValueError):
        pass
    try:
        return pd.Timestamp(valor).strftime("%d/%m/%Y")
    except Exception:
        txt = _texto(valor)
        return txt or "—"


def tabela_periodos_ciclos(
    df_ciclos: pd.DataFrame,
    ids_ciclo: list[str] | None = None,
) -> pd.DataFrame:
    """Início/fim acadêmicos (+ janela de pares) dos ciclos selecionados."""
    cols = [
        "ID_Ciclo",
        "Ciclo",
        "Disciplina_ID",
        "Inicio_ciclo",
        "Fim_ciclo",
        "Abertura_pares",
        "Encerramento_pares",
    ]
    if df_ciclos is None or df_ciclos.empty:
        return pd.DataFrame(columns=cols)
    df = df_ciclos.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for col in ("Data_Inicio_Ciclo", "Data_Apresentacao", "Data início", "Data fim"):
        if col in df.columns:
            df[col] = parse_data_planilha_series(df[col])
    if "ID_Ciclo" not in df.columns:
        return pd.DataFrame(columns=cols)
    df["ID_Ciclo"] = df["ID_Ciclo"].astype(str).str.strip()
    if ids_ciclo:
        alvo = {str(i).strip() for i in ids_ciclo}
        df = df[df["ID_Ciclo"].isin(alvo)]
    linhas = []
    for _, row in df.iterrows():
        linhas.append(
            {
                "ID_Ciclo": _texto(row.get("ID_Ciclo")),
                "Ciclo": _texto(row.get("Nome_Ciclo")) or _texto(row.get("ID_Ciclo")),
                "Disciplina_ID": _texto(row.get("ID_Disciplina")),
                "Inicio_ciclo": _fmt_data_br(row.get("Data_Inicio_Ciclo")),
                "Fim_ciclo": _fmt_data_br(row.get("Data_Apresentacao")),
                "Abertura_pares": _fmt_data_br(row.get("Data início")),
                "Encerramento_pares": _fmt_data_br(row.get("Data fim")),
            }
        )
    return pd.DataFrame(linhas, columns=cols)


@dataclass(frozen=True)
class ResumoNps:
    nps: float | None
    respondentes: int
    promotores: int
    neutros: int
    detratores: int
    pct_promotores: float
    pct_neutros: float
    pct_detratores: float


def calcular_nps(notas: list[float] | pd.Series) -> ResumoNps:
    """NPS clássico: % promotores (9–10) − % detratores (0–6). Neutros 7–8 no denominador."""
    serie = pd.to_numeric(pd.Series(notas), errors="coerce").dropna()
    total = int(len(serie))
    if total == 0:
        return ResumoNps(None, 0, 0, 0, 0, 0.0, 0.0, 0.0)
    prom = int(((serie >= 9) & (serie <= 10)).sum())
    det = int((serie <= 6).sum())
    neu = int(((serie >= 7) & (serie <= 8)).sum())
    nps = (prom - det) / total * 100.0
    return ResumoNps(
        nps=round(nps, 1),
        respondentes=total,
        promotores=prom,
        neutros=neu,
        detratores=det,
        pct_promotores=round(100.0 * prom / total, 1),
        pct_neutros=round(100.0 * neu / total, 1),
        pct_detratores=round(100.0 * det / total, 1),
    )


def nps_do_recorte(df: pd.DataFrame) -> ResumoNps:
    if df is None or df.empty or "Item" not in df.columns:
        return calcular_nps([])
    bloco = df[df["Item"] == ITEM_NPS]
    return calcular_nps(bloco["Resposta"] if "Resposta" in bloco.columns else [])


def media_itens_metricas(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Item", "Média", "N"])
    bloco = df[df["Item"].isin(ITENS_METRICA)].copy()
    if bloco.empty:
        return pd.DataFrame(columns=["Item", "Média", "N"])
    bloco["Resposta"] = pd.to_numeric(bloco["Resposta"], errors="coerce")
    agg = (
        bloco.groupby("Item", sort=False)["Resposta"]
        .agg(Média="mean", N="count")
        .reset_index()
    )
    agg["Média"] = agg["Média"].round(2)
    ordem = {nome: i for i, nome in enumerate(ITENS_METRICA)}
    agg["_ord"] = agg["Item"].map(ordem)
    return agg.sort_values("_ord").drop(columns=["_ord"])


def media_didatica_professores(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Professor", "Média", "N"])
    bloco = df[df["Item"] == ITEM_DIDATICA].copy()
    if bloco.empty:
        return pd.DataFrame(columns=["Professor", "Média", "N"])
    bloco["Resposta"] = pd.to_numeric(bloco["Resposta"], errors="coerce")
    bloco = bloco[bloco["Professor"].astype(str).str.strip().ne("")]
    agg = (
        bloco.groupby("Professor")["Resposta"]
        .agg(Média="mean", N="count")
        .reset_index()
        .sort_values("Professor", kind="stable")
    )
    agg["Média"] = agg["Média"].round(2)
    return agg


def textos_abertos(df: pd.DataFrame, item: str) -> pd.DataFrame:
    if df is None or df.empty or item not in ITENS_TEXTO:
        return pd.DataFrame(columns=["Aluno", "Texto"])
    bloco = df[df["Item"] == item].copy()
    if bloco.empty:
        return pd.DataFrame(columns=["Aluno", "Texto"])
    bloco["Texto"] = bloco["Resposta"].map(_texto)
    bloco = bloco[bloco["Texto"].ne("")]
    cols = []
    if "Nome_Aluno" in bloco.columns:
        bloco["Aluno"] = bloco["Nome_Aluno"].map(_texto)
        cols = ["Aluno", "Texto"]
    else:
        cols = ["Texto"]
    if "Ciclo" in bloco.columns:
        cols = ["Ciclo"] + cols
    return bloco[cols].reset_index(drop=True)


def contagem_respondentes(df: pd.DataFrame) -> int:
    if df is None or df.empty or "Email_Aluno" not in df.columns:
        return 0
    return int(df["Email_Aluno"].nunique())


def mapa_disciplina_codigo(df_disc: pd.DataFrame | None) -> dict[str, str]:
    """Nome_Disciplina → ID_Disciplina (código curto)."""
    if df_disc is None or df_disc.empty:
        return {}
    out: dict[str, str] = {}
    for _, row in df_disc.iterrows():
        nome = _texto(row.get("Nome_Disciplina"))
        codigo = _texto(row.get("ID_Disciplina"))
        if nome and codigo:
            out[nome] = codigo
    return out


def anexar_codigo_disciplina(df: pd.DataFrame, mapa: dict[str, str]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    if "Codigo_Disciplina" in out.columns:
        out["Codigo_Disciplina"] = out["Codigo_Disciplina"].map(_texto)
        return out
    if "Disciplina" not in out.columns:
        out["Codigo_Disciplina"] = ""
        return out
    out["Codigo_Disciplina"] = out["Disciplina"].map(_texto).map(lambda n: mapa.get(n, n[:12] if n else ""))
    return out


def _nome_ciclo_grupo(grupo: pd.DataFrame, id_c: str) -> str:
    if "Ciclo" in grupo.columns:
        nomes = [n for n in grupo["Ciclo"].map(_texto).tolist() if n]
        if nomes:
            return nomes[0]
    return str(id_c).strip()


def _disciplina_grupo(grupo: pd.DataFrame) -> str:
    if "Disciplina" not in grupo.columns:
        return ""
    nomes = [n for n in grupo["Disciplina"].map(_texto).tolist() if n]
    return nomes[0] if nomes else ""


def _codigo_grupo(grupo: pd.DataFrame) -> str:
    if "Codigo_Disciplina" in grupo.columns:
        codigos = [c for c in grupo["Codigo_Disciplina"].map(_texto).tolist() if c]
        if codigos:
            return codigos[0]
    return _disciplina_grupo(grupo)


def rotulo_ciclo_disciplina(ciclo: str, codigo_disciplina: str = "") -> str:
    """Rótulo curto: código da disciplina · ciclo (evita colunas largas e colisão de nomes)."""
    ciclo_t = _texto(ciclo) or "-"
    cod = _texto(codigo_disciplina)
    if cod:
        return f"{cod} · {ciclo_t}"
    return ciclo_t


def classificacao_nps(nota) -> str:
    try:
        n = float(nota)
    except (TypeError, ValueError):
        return ""
    if n >= 9:
        return "Promotor"
    if n <= 6:
        return "Detrator"
    if 7 <= n <= 8:
        return "Neutro"
    return ""


def nps_por_ciclo(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por ciclo (comparativo), com código da disciplina no rótulo."""
    cols = [
        "ID_Ciclo",
        "Codigo",
        "Disciplina",
        "Ciclo",
        "Rotulo",
        "NPS",
        "Respondentes",
        "Promotores",
        "Neutros",
        "Detratores",
    ]
    if df is None or df.empty or "ID_Ciclo" not in df.columns:
        return pd.DataFrame(columns=cols)
    linhas = []
    for id_c, grupo in df.groupby("ID_Ciclo", sort=False):
        resumo = nps_do_recorte(grupo)
        nome = _nome_ciclo_grupo(grupo, str(id_c))
        disc = _disciplina_grupo(grupo)
        codigo = _codigo_grupo(grupo)
        linhas.append(
            {
                "ID_Ciclo": str(id_c).strip(),
                "Codigo": codigo,
                "Disciplina": disc,
                "Ciclo": nome,
                "Rotulo": rotulo_ciclo_disciplina(nome, codigo),
                "NPS": resumo.nps,
                "Respondentes": resumo.respondentes,
                "Promotores": resumo.promotores,
                "Neutros": resumo.neutros,
                "Detratores": resumo.detratores,
            }
        )
    out = pd.DataFrame(linhas, columns=cols)
    return out.sort_values(["Codigo", "Ciclo"]).reset_index(drop=True)


def metricas_por_ciclo(df: pd.DataFrame) -> pd.DataFrame:
    """Métricas 0–5 por ciclo (formato longo), com código da disciplina no rótulo."""
    cols = ["ID_Ciclo", "Codigo", "Disciplina", "Ciclo", "Rotulo", "Item", "Média", "N"]
    if df is None or df.empty or "ID_Ciclo" not in df.columns:
        return pd.DataFrame(columns=cols)
    linhas = []
    for id_c, grupo in df.groupby("ID_Ciclo", sort=False):
        nome = _nome_ciclo_grupo(grupo, str(id_c))
        disc = _disciplina_grupo(grupo)
        codigo = _codigo_grupo(grupo)
        rotulo = rotulo_ciclo_disciplina(nome, codigo)
        met = media_itens_metricas(grupo)
        for _, row in met.iterrows():
            linhas.append(
                {
                    "ID_Ciclo": str(id_c).strip(),
                    "Codigo": codigo,
                    "Disciplina": disc,
                    "Ciclo": nome,
                    "Rotulo": rotulo,
                    "Item": row["Item"],
                    "Média": row["Média"],
                    "N": row["N"],
                }
            )
    out = pd.DataFrame(linhas, columns=cols)
    if out.empty:
        return out
    ordem = {nome: i for i, nome in enumerate(ITENS_METRICA)}
    out["_ord"] = out["Item"].map(ordem)
    return out.sort_values(["Codigo", "Ciclo", "_ord"]).drop(columns=["_ord"]).reset_index(drop=True)


def metricas_comparativo_tabela(df_metricas_ciclo: pd.DataFrame) -> pd.DataFrame:
    """Ciclo (código · nome) nas linhas; critérios nas colunas (número fixo); célula = 'média (N)'."""
    if df_metricas_ciclo is None or df_metricas_ciclo.empty:
        return pd.DataFrame(columns=["Ciclo", *ITENS_METRICA])
    base = df_metricas_ciclo.copy()
    if "Rotulo" not in base.columns:
        base["Rotulo"] = [
            rotulo_ciclo_disciplina(_texto(c), _texto(cod))
            for c, cod in zip(
                base["Ciclo"] if "Ciclo" in base.columns else [""] * len(base),
                base["Codigo"] if "Codigo" in base.columns else [""] * len(base),
            )
        ]
    if "Codigo" not in base.columns:
        base["Codigo"] = ""
    base["Celula"] = base.apply(
        lambda r: (
            f"{float(r['Média']):.2f} ({int(r['N'])})"
            if pd.notna(r.get("Média"))
            else "-"
        ),
        axis=1,
    )
    ordem_linhas = (
        base[["Rotulo", "Codigo", "Ciclo"]]
        .drop_duplicates()
        .sort_values(["Codigo", "Ciclo"])["Rotulo"]
        .tolist()
    )
    pivot = base.pivot_table(
        index="Rotulo", columns="Item", values="Celula", aggfunc="first"
    )
    for item in ITENS_METRICA:
        if item not in pivot.columns:
            pivot[item] = "-"
    pivot = pivot.reindex(index=ordem_linhas, columns=list(ITENS_METRICA))
    pivot = pivot.fillna("-").reset_index().rename(columns={"Rotulo": "Ciclo"})
    pivot.columns.name = None
    return pivot


def detalhe_avaliacao_por_aluno(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por aluno × ciclo: NPS, categoria e médias dos critérios."""
    cols = [
        "Aluno",
        "Email",
        "Codigo",
        "Disciplina",
        "Ciclo",
        "ID_Ciclo",
        "NPS",
        "Categoria",
        *ITENS_METRICA,
    ]
    if df is None or df.empty or "Email_Aluno" not in df.columns:
        return pd.DataFrame(columns=cols)

    base = df.copy()
    if "ID_Ciclo" not in base.columns:
        base["ID_Ciclo"] = ""
    base["Email_Aluno"] = base["Email_Aluno"].map(_texto).str.lower()
    linhas = []
    for (email, id_c), grupo in base.groupby(["Email_Aluno", "ID_Ciclo"], sort=False):
        if not email:
            continue
        nome = ""
        if "Nome_Aluno" in grupo.columns:
            nomes = [n for n in grupo["Nome_Aluno"].map(_texto).tolist() if n]
            nome = nomes[0] if nomes else email
        else:
            nome = email
        nps_bloco = grupo[grupo["Item"] == ITEM_NPS] if "Item" in grupo.columns else grupo.iloc[0:0]
        nota_nps = None
        if not nps_bloco.empty and "Resposta" in nps_bloco.columns:
            vals = pd.to_numeric(nps_bloco["Resposta"], errors="coerce").dropna()
            if not vals.empty:
                nota_nps = float(vals.iloc[0])
        linha = {
            "Aluno": nome,
            "Email": email,
            "Codigo": _codigo_grupo(grupo),
            "Disciplina": _disciplina_grupo(grupo),
            "Ciclo": _nome_ciclo_grupo(grupo, str(id_c)),
            "ID_Ciclo": str(id_c).strip(),
            "NPS": round(nota_nps, 1) if nota_nps is not None else None,
            "Categoria": classificacao_nps(nota_nps) if nota_nps is not None else "",
        }
        met = media_itens_metricas(grupo)
        medias = {r["Item"]: r["Média"] for _, r in met.iterrows()} if not met.empty else {}
        for item in ITENS_METRICA:
            linha[item] = medias.get(item)
        linhas.append(linha)

    out = pd.DataFrame(linhas, columns=cols)
    if out.empty:
        return out
    ordem_cat = {"Detrator": 0, "Neutro": 1, "Promotor": 2, "": 3}
    out["_ord"] = out["Categoria"].map(ordem_cat).fillna(3)
    return out.sort_values(["_ord", "NPS", "Aluno"], ascending=[True, True, True]).drop(columns=["_ord"]).reset_index(drop=True)


def didatica_por_ciclo(df: pd.DataFrame) -> pd.DataFrame:
    """Média de didática por professor, quebrada por ciclo."""
    cols = ["Codigo", "Ciclo", "Rotulo", "Professor", "Média", "N"]
    if df is None or df.empty or "Item" not in df.columns:
        return pd.DataFrame(columns=cols)
    base = df[df["Item"] == ITEM_DIDATICA].copy()
    if base.empty:
        return pd.DataFrame(columns=cols)
    if "ID_Ciclo" not in base.columns:
        base["ID_Ciclo"] = ""
    linhas = []
    for id_c, grupo in base.groupby("ID_Ciclo", sort=False):
        nome = _nome_ciclo_grupo(grupo, str(id_c))
        codigo = _codigo_grupo(grupo)
        rotulo = rotulo_ciclo_disciplina(nome, codigo)
        med = media_didatica_professores(grupo)
        for _, row in med.iterrows():
            linhas.append(
                {
                    "Codigo": codigo,
                    "Ciclo": nome,
                    "Rotulo": rotulo,
                    "Professor": row["Professor"],
                    "Média": row["Média"],
                    "N": row["N"],
                }
            )
    out = pd.DataFrame(linhas, columns=cols)
    if out.empty:
        return out
    return out.sort_values(
        ["Codigo", "Ciclo", "Professor"], kind="stable"
    ).reset_index(drop=True)


def dominio_eixo_nps(valores) -> list[float]:
    """0–100 se não houver NPS negativo; -100–100 só quando algum valor for < 0."""
    serie = pd.to_numeric(pd.Series(valores), errors="coerce").dropna()
    if not serie.empty and float(serie.min()) < 0:
        return [-100.0, 100.0]
    return [0.0, 100.0]


def metricas_tabela_acumulado(df_metricas: pd.DataFrame) -> pd.DataFrame:
    """Uma linha ('Acumulado') com os critérios nas colunas: 'média (N)'."""
    colunas = ["Recorte", *ITENS_METRICA]
    linha = {"Recorte": "Acumulado"}
    for item in ITENS_METRICA:
        linha[item] = "-"
    if df_metricas is None or df_metricas.empty:
        return pd.DataFrame([linha], columns=colunas)
    for _, row in df_metricas.iterrows():
        item = _texto(row.get("Item"))
        if item in ITENS_METRICA and pd.notna(row.get("Média")):
            linha[item] = f"{float(row['Média']):.2f} ({int(row.get('N') or 0)})"
    return pd.DataFrame([linha], columns=colunas)


def metricas_pivot_numerico(df_metricas_ciclo: pd.DataFrame) -> pd.DataFrame:
    """Pivot numérico Ciclo × Critério (para gráficos)."""
    if df_metricas_ciclo is None or df_metricas_ciclo.empty:
        return pd.DataFrame()
    base = df_metricas_ciclo.copy()
    if "Rotulo" not in base.columns:
        return pd.DataFrame()
    pivot = base.pivot_table(index="Rotulo", columns="Item", values="Média", aggfunc="mean")
    colunas = [c for c in ITENS_METRICA if c in pivot.columns]
    return pivot.reindex(columns=colunas)


def resumo_nps_tabela(nps: "ResumoNps", n_alunos: int) -> pd.DataFrame:
    """Linha única detalhando o NPS do recorte (espelha a tabela do comparativo)."""
    return pd.DataFrame(
        [
            {
                "Recorte": "Acumulado",
                "NPS": nps.nps,
                "Respondentes": n_alunos,
                "Respostas NPS": nps.respondentes,
                "Promotores": f"{nps.promotores} ({nps.pct_promotores}%)",
                "Neutros": f"{nps.neutros} ({nps.pct_neutros}%)",
                "Detratores": f"{nps.detratores} ({nps.pct_detratores}%)",
            }
        ]
    )


def composicao_nps(nps: "ResumoNps") -> pd.DataFrame:
    """Distribuição percentual do NPS (para o gráfico do modo acumulado)."""
    return pd.DataFrame(
        [
            {"Categoria": "Promotores", "Respostas": nps.promotores, "%": nps.pct_promotores},
            {"Categoria": "Neutros", "Respostas": nps.neutros, "%": nps.pct_neutros},
            {"Categoria": "Detratores", "Respostas": nps.detratores, "%": nps.pct_detratores},
        ]
    )


def blocos_comentarios(df: pd.DataFrame) -> list[dict]:
    """Comentários abertos agrupados por ciclo e categoria (uma página por bloco no PDF)."""
    if df is None or df.empty or "Item" not in df.columns:
        return []
    base = df.copy()
    if "ID_Ciclo" not in base.columns:
        base["ID_Ciclo"] = ""
    blocos: list[dict] = []
    for id_c, grupo in base.groupby("ID_Ciclo", sort=False):
        nome = _nome_ciclo_grupo(grupo, str(id_c))
        codigo = _codigo_grupo(grupo)
        rotulo = rotulo_ciclo_disciplina(nome, codigo)
        for item in ITENS_TEXTO:
            textos = textos_abertos(grupo, item)
            if textos.empty:
                continue
            cols = [c for c in ("Aluno", "Texto") if c in textos.columns]
            blocos.append(
                {
                    "id_ciclo": str(id_c).strip(),
                    "rotulo": rotulo,
                    "item": item,
                    "textos": textos[cols].reset_index(drop=True),
                }
            )
    blocos.sort(key=lambda b: (b["rotulo"], ITENS_TEXTO.index(b["item"])))
    return blocos


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _pdf_safe(texto: str, unicode_ok: bool) -> str:
    """Com fonte Unicode mantém o texto; no fallback Helvetica troca travessão/aspas."""
    s = _texto(texto)
    if unicode_ok:
        return s
    for origem, destino in (
        ("—", "-"),
        ("–", "-"),
        ("−", "-"),
        ("·", "-"),
        ("…", "..."),
        ("“", '"'),
        ("”", '"'),
        ("‘", "'"),
        ("’", "'"),
        ("×", "x"),
    ):
        s = s.replace(origem, destino)
    s = _sem_acento(s)
    return s.encode("latin-1", errors="replace").decode("latin-1")


_VERDE = (0, 77, 40)
_DOURADO = (179, 143, 54)
_CINZA = (242, 242, 242)
_CORES_NPS = {"Promotores": "#2E7D32", "Neutros": "#B38F36", "Detratores": "#B3261E"}


def _caminho_logo() -> str | None:
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for nome in ("logo.png", "logorehagro.jpg"):
        caminho = os.path.join(raiz, nome)
        if os.path.isfile(caminho):
            return caminho
    return None


def _fontes_unicode() -> list[tuple[str, str]]:
    candidatos: list[tuple[str, str]] = []
    try:  # o matplotlib distribui a DejaVu, que existe em qualquer ambiente do app
        import matplotlib

        ttf = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        candidatos.append(
            (os.path.join(ttf, "DejaVuSans.ttf"), os.path.join(ttf, "DejaVuSans-Bold.ttf"))
        )
    except Exception:
        pass
    candidatos += [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    return candidatos


def _resolver_fonte_pdf(pdf) -> tuple[str, bool]:
    """Retorna (nome_fonte, unicode). Tenta DejaVu/Arial; senão Helvetica ASCII."""
    for regular, bold in _fontes_unicode():
        if os.path.isfile(regular):
            try:
                pdf.add_font("DashFont", "", regular)
                if os.path.isfile(bold):
                    pdf.add_font("DashFont", "B", bold)
                else:
                    pdf.add_font("DashFont", "B", regular)
                return "DashFont", True
            except Exception:
                continue
    return "Helvetica", False


def _grafico_barras_png(
    rotulos: list[str],
    valores: list[float],
    *,
    titulo: str,
    formato: str = "{:.1f}",
    limites: tuple[float, float] | None = None,
    cores: list[str] | str = "#004D28",
) -> bytes | None:
    """Barras horizontais com rótulo de dados (None se matplotlib não estiver disponível)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    pares = [
        (str(r), float(v))
        for r, v in zip(rotulos, valores)
        if v is not None and pd.notna(v)
    ]
    if not pares:
        return None
    nomes = [p[0] for p in pares]
    vals = [p[1] for p in pares]
    altura = max(1.9, 0.42 * len(vals) + 0.9)
    fig, ax = plt.subplots(figsize=(9.2, altura), dpi=160)
    barras = ax.barh(nomes, vals, color=cores, height=0.6)
    ax.invert_yaxis()
    ax.set_title(titulo, fontsize=11, color="#004D28", loc="left", fontweight="bold")
    if limites:
        ax.set_xlim(*limites)
    elif min(vals) >= 0:
        ax.set_xlim(0, max(vals) * 1.25 or 1)
    else:
        margem = max(abs(min(vals)), abs(max(vals))) * 1.3 or 1
        ax.set_xlim(-margem, margem)
        ax.axvline(0, color="#999999", linewidth=0.8)
    ax.bar_label(barras, labels=[formato.format(v) for v in vals], padding=3, fontsize=9)
    ax.tick_params(labelsize=9)
    ax.grid(axis="x", color="#DDDDDD", linewidth=0.6)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _grafico_agrupado_png(pivot: pd.DataFrame, *, titulo: str) -> bytes | None:
    """Barras agrupadas: critérios no eixo X, um grupo por ciclo."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    if pivot is None or pivot.empty:
        return None

    criterios = [str(c) for c in pivot.columns]
    ciclos = [str(i) for i in pivot.index]
    n = max(len(ciclos), 1)
    largura = min(0.8 / n, 0.3)
    paleta = ["#004D28", "#B38F36", "#2E7D32", "#7A5C12", "#4C8C5A", "#C0A15A"]
    fig, ax = plt.subplots(figsize=(9.2, 3.4), dpi=160)
    posicoes = range(len(criterios))
    for idx, ciclo in enumerate(ciclos):
        valores = [
            None if pd.isna(v) else float(v) for v in pivot.loc[pivot.index[idx]].tolist()
        ]
        deslocado = [p + (idx - (n - 1) / 2) * largura for p in posicoes]
        barras = ax.bar(
            deslocado,
            [v or 0 for v in valores],
            width=largura,
            label=ciclo,
            color=paleta[idx % len(paleta)],
        )
        ax.bar_label(
            barras,
            labels=["-" if v is None else f"{v:.2f}" for v in valores],
            padding=2,
            fontsize=7,
        )
    ax.set_xticks(list(posicoes))
    ax.set_xticklabels(criterios, fontsize=9)
    ax.set_ylim(0, 5.6)
    ax.set_title(titulo, fontsize=11, color="#004D28", loc="left", fontweight="bold")
    ax.legend(fontsize=8, frameon=False, ncol=min(len(ciclos), 4))
    ax.grid(axis="y", color="#DDDDDD", linewidth=0.6)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _fmt_celula(valor) -> str:
    if valor is None:
        return "-"
    try:
        if pd.isna(valor):
            return "-"
    except (TypeError, ValueError):
        pass
    if isinstance(valor, float):
        texto = f"{valor:.2f}"
        return texto[:-1] if texto.endswith("0") else texto
    return _texto(valor) or "-"


SECOES_PDF = (
    ("periodos", "Período dos ciclos"),
    ("nps", "NPS"),
    ("metricas", "Métricas do ciclo"),
    ("didatica", "Didática dos professores"),
    ("detratores", "Detalhamento de detratores"),
    ("comentarios", "Comentários abertos"),
)


def gerar_pdf_recorte(
    *,
    disciplinas: list[str],
    ciclos_info: pd.DataFrame,
    nps: ResumoNps,
    n_alunos: int,
    metricas: pd.DataFrame,
    didatica: pd.DataFrame,
    modo_grafico: str,
    nps_ciclos: pd.DataFrame | None = None,
    metricas_tabela: pd.DataFrame | None = None,
    salas: list[str] | None = None,
    metricas_pivot: pd.DataFrame | None = None,
    didatica_ciclos: pd.DataFrame | None = None,
    detratores: pd.DataFrame | None = None,
    comentarios: list[dict] | None = None,
    secoes: dict[str, bool] | None = None,
) -> bytes:
    """Relatório do recorte: marca no cabeçalho, gráficos, tabelas e comentários por ciclo."""
    from fpdf import FPDF
    from fpdf.fonts import FontFace

    ativas = {chave: True for chave, _ in SECOES_PDF}
    if secoes:
        ativas.update({k: bool(v) for k, v in secoes.items() if k in ativas})

    agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    logo = _caminho_logo()

    class _Relatorio(FPDF):
        fonte_rel = "Helvetica"
        titulo_rel = ""
        subtitulo_rel = ""
        rodape_rel = ""

        def header(self):
            deslocamento = 0.0
            if logo:
                try:
                    info = self.image(logo, x=self.l_margin, y=8, h=12)
                    deslocamento = float(getattr(info, "rendered_width", 0) or 0)
                except Exception:
                    deslocamento = 0.0
            inicio = self.l_margin + (deslocamento + 8 if deslocamento else 0)
            self.set_xy(inicio, 9)
            self.set_font(self.fonte_rel, "B", 13)
            self.set_text_color(*_VERDE)
            self.cell(0, 6, self.titulo_rel, new_x="LMARGIN", new_y="NEXT")
            self.set_x(inicio)
            self.set_font(self.fonte_rel, "", 8)
            self.set_text_color(105, 105, 105)
            self.cell(0, 4, self.subtitulo_rel)
            self.set_draw_color(*_DOURADO)
            self.set_line_width(0.6)
            self.line(self.l_margin, 23.5, self.w - self.r_margin, 23.5)
            self.set_xy(self.l_margin, 28)
            self.set_text_color(0, 0, 0)

        def footer(self):
            self.set_y(-12)
            self.set_font(self.fonte_rel, "", 8)
            self.set_text_color(130, 130, 130)
            self.cell(0, 6, f"{self.rodape_rel} | pagina {self.page_no()}/{{nb}}", align="C")
            self.set_text_color(0, 0, 0)

    pdf = _Relatorio()
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_top_margin(28)
    fonte, unicode_ok = _resolver_fonte_pdf(pdf)

    def t(valor) -> str:
        return _pdf_safe(valor, unicode_ok)

    pdf.fonte_rel = fonte
    pdf.titulo_rel = t("Avaliação do curso — resultados")
    pdf.subtitulo_rel = t(f"Graduação em Gestão do Agronegócio · Gerado em {agora}")
    pdf.rodape_rel = t("Rehagro · Graduação em Gestão do Agronegócio")
    pdf.add_page()

    def titulo(txt: str, size: int = 12, espaco_antes: float = 3.0):
        if pdf.get_y() > pdf.t_margin:
            pdf.ln(espaco_antes)
        if pdf.will_page_break(26):  # evita título órfão no pé da página
            pdf.add_page()
        pdf.set_font(fonte, "B", size)
        pdf.set_text_color(*_VERDE)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 6.5, t(txt))
        pdf.set_text_color(0, 0, 0)
        pdf.ln(0.5)

    def corpo(txt: str, size: int = 9):
        pdf.set_font(fonte, "", size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 5, t(txt))

    def tabela(df: pd.DataFrame, *, larguras=None, tamanho: int = 8, alinhamento="LEFT"):
        if df is None or df.empty:
            return
        pdf.set_font(fonte, "", tamanho)
        cabecalho = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=_VERDE)
        with pdf.table(
            col_widths=larguras,
            headings_style=cabecalho,
            line_height=5.0,
            text_align=alinhamento,
            borders_layout="SINGLE_TOP_LINE",
            cell_fill_color=_CINZA,
            cell_fill_mode="ROWS",
            padding=(1.2, 1.6),
        ) as tbl:
            linha = tbl.row()
            for col in df.columns:
                linha.cell(t(col))
            for _, registro in df.iterrows():
                linha = tbl.row()
                for col in df.columns:
                    linha.cell(t(_fmt_celula(registro[col])))

    def grafico(png: bytes | None):
        if not png:
            return
        pdf.ln(1)
        try:
            pdf.image(io.BytesIO(png), x=pdf.l_margin, w=pdf.epw)
        except Exception:
            return
        pdf.ln(1)

    def cartoes(itens: list[tuple[str, str]]):
        largura = pdf.epw / len(itens)
        y = pdf.get_y()
        for idx, (rotulo, valor) in enumerate(itens):
            x = pdf.l_margin + idx * largura
            pdf.set_fill_color(245, 248, 246)
            pdf.set_draw_color(*_DOURADO)
            pdf.set_line_width(0.3)
            pdf.rect(x + 0.8, y, largura - 1.6, 15, style="DF")
            pdf.set_xy(x + 0.8, y + 1.5)
            pdf.set_font(fonte, "", 8)
            pdf.set_text_color(105, 105, 105)
            pdf.cell(largura - 1.6, 4.5, t(rotulo), align="C")
            pdf.set_xy(x + 0.8, y + 6.5)
            pdf.set_font(fonte, "B", 13)
            pdf.set_text_color(*_VERDE)
            pdf.cell(largura - 1.6, 7, t(valor), align="C")
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(pdf.l_margin, y + 17)

    # --- Filtros do recorte ---
    titulo("Recorte analisado", 12, espaco_antes=0)
    corpo("Curso: Graduação em Gestão do Agronegócio")
    corpo(f"Disciplina(s): {', '.join(disciplinas) if disciplinas else 'Todas'}")
    corpo(f"Sala(s): {', '.join(salas) if salas else 'Todas'}")
    corpo(f"Modo: {modo_grafico}")

    if ativas["periodos"] and ciclos_info is not None and not ciclos_info.empty:
        periodos = ciclos_info.rename(
            columns={
                "Disciplina_ID": "Disc.",
                "Inicio_ciclo": "Início",
                "Fim_ciclo": "Fim",
                "Abertura_pares": "Pares (abre)",
                "Encerramento_pares": "Pares (fecha)",
            }
        )
        cols = [c for c in ("Disc.", "Ciclo", "Início", "Fim", "Pares (abre)", "Pares (fecha)") if c in periodos.columns]
        titulo("Período dos ciclos", 11)
        tabela(periodos[cols])

    # --- NPS ---
    if ativas["nps"]:
        titulo("NPS do recorte", 12)
        cartoes(
            [
                ("Respondentes", str(n_alunos)),
                ("NPS", f"{nps.nps:.1f}" if nps.nps is not None else "-"),
                ("Promotores", f"{nps.promotores} ({nps.pct_promotores}%)"),
                ("Detratores", f"{nps.detratores} ({nps.pct_detratores}%)"),
            ]
        )
        corpo(
            f"Neutros (7-8): {nps.neutros} ({nps.pct_neutros}%) | "
            f"base NPS: {nps.respondentes} resposta(s) de {n_alunos} respondente(s)."
        )

        comparativo = nps_ciclos is not None and not nps_ciclos.empty
        if comparativo:
            vals_nps = [r.get("NPS") for _, r in nps_ciclos.iterrows()]
            lim_inf, lim_sup = dominio_eixo_nps(vals_nps)
            grafico(
                _grafico_barras_png(
                    [_texto(r.get("Rotulo")) or _texto(r.get("Ciclo")) for _, r in nps_ciclos.iterrows()],
                    vals_nps,
                    titulo="NPS por ciclo",
                    formato="{:.1f}",
                    limites=(lim_inf, lim_sup),
                )
            )
            cols_nps = [
                c
                for c in ("Codigo", "Ciclo", "NPS", "Respondentes", "Promotores", "Neutros", "Detratores")
                if c in nps_ciclos.columns
            ]
            tabela(nps_ciclos[cols_nps].rename(columns={"Codigo": "Disc."}))
        else:
            comp = composicao_nps(nps)
            grafico(
                _grafico_barras_png(
                    comp["Categoria"].tolist(),
                    comp["%"].tolist(),
                    titulo="Composição do NPS (% das respostas)",
                    formato="{:.1f}%",
                    limites=(0, 100),
                    cores=[_CORES_NPS[c] for c in comp["Categoria"]],
                )
            )
            tabela(resumo_nps_tabela(nps, n_alunos))

    # --- Métricas ---
    if ativas["metricas"]:
        titulo("Métricas do ciclo (0-5)", 12)
        if metricas_pivot is not None and not metricas_pivot.empty:
            grafico(_grafico_agrupado_png(metricas_pivot, titulo="Médias por critério"))
        elif metricas is not None and not metricas.empty:
            grafico(
                _grafico_barras_png(
                    metricas["Item"].tolist(),
                    metricas["Média"].tolist(),
                    titulo="Médias por critério",
                    formato="{:.2f}",
                    limites=(0, 5),
                )
            )
        if metricas_tabela is not None and not metricas_tabela.empty:
            tabela(metricas_tabela)
        elif metricas is not None and not metricas.empty:
            tabela(metricas_tabela_acumulado(metricas))

    # --- Didática ---
    if ativas["didatica"]:
        titulo("Didática dos professores (0-5)", 12)
        if didatica_ciclos is not None and not didatica_ciclos.empty:
            cols_did = [
                c for c in ("Codigo", "Ciclo", "Professor", "Média", "N") if c in didatica_ciclos.columns
            ]
            tabela(didatica_ciclos[cols_did].rename(columns={"Codigo": "Disc."}))
        elif didatica is not None and not didatica.empty:
            tabela(didatica)
        else:
            corpo("Sem avaliações de didática neste recorte.")

    # --- Detratores ---
    if ativas["detratores"] and detratores is not None and not detratores.empty:
        titulo("Detratores do recorte", 12)
        cols_det = [
            c for c in ("Aluno", "Codigo", "Ciclo", "NPS", *ITENS_METRICA) if c in detratores.columns
        ]
        tabela(detratores[cols_det].rename(columns={"Codigo": "Disc."}), tamanho=7)

    # --- Comentários abertos: uma página por ciclo e categoria ---
    if ativas["comentarios"]:
        for bloco in comentarios or []:
            textos = bloco.get("textos")
            if textos is None or textos.empty:
                continue
            pdf.add_page()
            titulo(f"{bloco.get('item')} — {bloco.get('rotulo')}", 13, espaco_antes=0)
            corpo(f"{len(textos)} comentário(s).")
            pdf.ln(1)
            larguras = (28, 72) if "Aluno" in textos.columns else None
            tabela(textos, larguras=larguras, tamanho=8)

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
