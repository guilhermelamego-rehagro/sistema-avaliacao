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
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    out = df
    ciclos = _lista_filtro(id_ciclo)
    discs = _lista_filtro(disciplina)
    if ciclos and "ID_Ciclo" in out.columns:
        out = out[out["ID_Ciclo"].isin(ciclos)]
    if discs and "Disciplina" in out.columns:
        out = out[out["Disciplina"].isin(discs)]
    return out


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
        .sort_values("Média", ascending=False)
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
    """Critério nas linhas, código·ciclo nas colunas; célula = 'média (N)'."""
    if df_metricas_ciclo is None or df_metricas_ciclo.empty:
        return pd.DataFrame(columns=["Critério"])
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
    ordem_cols = (
        base[["Rotulo", "Codigo", "Ciclo"]]
        .drop_duplicates()
        .sort_values(["Codigo", "Ciclo"])["Rotulo"]
        .tolist()
    )
    pivot = base.pivot_table(
        index="Item", columns="Rotulo", values="Celula", aggfunc="first"
    )
    pivot = pivot.reindex(columns=ordem_cols)
    pivot = pivot.reindex(index=list(ITENS_METRICA))
    pivot = pivot.fillna("-").reset_index().rename(columns={"Item": "Critério"})
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


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _pdf_safe(texto: str, unicode_ok: bool) -> str:
    """Helvetica no Cloud não aceita travessão/aspas tipográficas; sanitiza sempre."""
    s = _texto(texto)
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
    if not unicode_ok:
        s = _sem_acento(s)
        s = s.encode("latin-1", errors="replace").decode("latin-1")
    return s


def _resolver_fonte_pdf(pdf) -> tuple[str, bool]:
    """Retorna (nome_fonte, unicode). Tenta DejaVu/Arial; senão Helvetica ASCII."""
    candidatos = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    for regular, bold in candidatos:
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
) -> bytes:
    """PDF resumido do recorte filtrado (sem comentários longos)."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    fonte, unicode_ok = _resolver_fonte_pdf(pdf)

    def t(valor) -> str:
        return _pdf_safe(valor, unicode_ok)

    def titulo(txt: str, size: int = 14):
        pdf.set_font(fonte, "B", size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 8, t(txt))
        pdf.ln(1)

    def corpo(txt: str, size: int = 10):
        pdf.set_font(fonte, "", size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 6, t(txt))

    agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    titulo("Dashboard - avaliacao do curso")
    corpo(f"Gerado em {agora}")
    corpo(f"Modo de graficos: {modo_grafico}")
    discs = ", ".join(disciplinas) if disciplinas else "Todas"
    corpo(f"Disciplina(s): {discs}")
    pdf.ln(2)

    if ciclos_info is not None and not ciclos_info.empty:
        titulo("Ciclos do recorte", 12)
        for _, row in ciclos_info.iterrows():
            corpo(
                f"- {row.get('Ciclo')} ({row.get('ID_Ciclo')}): "
                f"{row.get('Inicio_ciclo')} a {row.get('Fim_ciclo')} "
                f"(pares: {row.get('Abertura_pares')} a {row.get('Encerramento_pares')})"
            )
        pdf.ln(2)

    titulo("NPS (acumulado do filtro)", 12)
    nps_txt = f"{nps.nps:.1f}" if nps.nps is not None else "-"
    corpo(
        f"NPS: {nps_txt} | Respondentes unicos: {n_alunos} | "
        f"Base NPS: {nps.respondentes} | "
        f"Promotores: {nps.promotores} ({nps.pct_promotores}%) | "
        f"Neutros: {nps.neutros} ({nps.pct_neutros}%) | "
        f"Detratores: {nps.detratores} ({nps.pct_detratores}%)"
    )
    pdf.ln(2)

    if nps_ciclos is not None and not nps_ciclos.empty:
        titulo("NPS por ciclo", 12)
        for _, row in nps_ciclos.iterrows():
            val = row.get("NPS")
            val_txt = f"{val:.1f}" if val is not None and pd.notna(val) else "-"
            rotulo = row.get("Rotulo") or row.get("Ciclo")
            corpo(f"- {rotulo}: NPS {val_txt} (n={int(row.get('Respondentes') or 0)})")
        pdf.ln(2)

    if metricas_tabela is not None and not metricas_tabela.empty:
        titulo("Metricas por ciclo (0-5)", 12)
        cols = [str(c) for c in metricas_tabela.columns]
        corpo(" | ".join(cols))
        for _, row in metricas_tabela.iterrows():
            corpo(" | ".join(_texto(row.get(c)) or "-" for c in cols))
        pdf.ln(2)
    elif metricas is not None and not metricas.empty:
        titulo("Metricas gerais (0-5)", 12)
        for _, row in metricas.iterrows():
            corpo(f"- {row.get('Item')}: media {row.get('Média')} (n={int(row.get('N') or 0)})")
        pdf.ln(2)

    if didatica is not None and not didatica.empty:
        titulo("Didatica dos professores (0-5)", 12)
        for _, row in didatica.iterrows():
            corpo(f"- {row.get('Professor')}: media {row.get('Média')} (n={int(row.get('N') or 0)})")

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
