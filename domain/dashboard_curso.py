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
    passivos: int
    detratores: int
    pct_promotores: float
    pct_passivos: float
    pct_detratores: float


def calcular_nps(notas: list[float] | pd.Series) -> ResumoNps:
    """NPS clássico: % promotores (9–10) − % detratores (0–6). Neutros 7–8 no denominador."""
    serie = pd.to_numeric(pd.Series(notas), errors="coerce").dropna()
    total = int(len(serie))
    if total == 0:
        return ResumoNps(None, 0, 0, 0, 0, 0.0, 0.0, 0.0)
    prom = int(((serie >= 9) & (serie <= 10)).sum())
    det = int((serie <= 6).sum())
    pas = int(((serie >= 7) & (serie <= 8)).sum())
    nps = (prom - det) / total * 100.0
    return ResumoNps(
        nps=round(nps, 1),
        respondentes=total,
        promotores=prom,
        passivos=pas,
        detratores=det,
        pct_promotores=round(100.0 * prom / total, 1),
        pct_passivos=round(100.0 * pas / total, 1),
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


def nps_por_ciclo(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por ciclo (comparativo)."""
    cols = ["ID_Ciclo", "Ciclo", "NPS", "Respondentes", "Promotores", "Passivos", "Detratores"]
    if df is None or df.empty or "ID_Ciclo" not in df.columns:
        return pd.DataFrame(columns=cols)
    linhas = []
    for id_c, grupo in df.groupby("ID_Ciclo", sort=False):
        resumo = nps_do_recorte(grupo)
        nome = ""
        if "Ciclo" in grupo.columns:
            nomes = [n for n in grupo["Ciclo"].map(_texto).tolist() if n]
            nome = nomes[0] if nomes else str(id_c)
        linhas.append(
            {
                "ID_Ciclo": str(id_c).strip(),
                "Ciclo": nome or str(id_c).strip(),
                "NPS": resumo.nps,
                "Respondentes": resumo.respondentes,
                "Promotores": resumo.promotores,
                "Passivos": resumo.passivos,
                "Detratores": resumo.detratores,
            }
        )
    out = pd.DataFrame(linhas, columns=cols)
    return out.sort_values("Ciclo").reset_index(drop=True)


def metricas_por_ciclo(df: pd.DataFrame) -> pd.DataFrame:
    """Métricas 0–5 por ciclo (formato longo: Ciclo, Item, Média, N)."""
    cols = ["ID_Ciclo", "Ciclo", "Item", "Média", "N"]
    if df is None or df.empty or "ID_Ciclo" not in df.columns:
        return pd.DataFrame(columns=cols)
    linhas = []
    for id_c, grupo in df.groupby("ID_Ciclo", sort=False):
        nome = ""
        if "Ciclo" in grupo.columns:
            nomes = [n for n in grupo["Ciclo"].map(_texto).tolist() if n]
            nome = nomes[0] if nomes else str(id_c)
        met = media_itens_metricas(grupo)
        for _, row in met.iterrows():
            linhas.append(
                {
                    "ID_Ciclo": str(id_c).strip(),
                    "Ciclo": nome or str(id_c).strip(),
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
    return out.sort_values(["Ciclo", "_ord"]).drop(columns=["_ord"]).reset_index(drop=True)


def metricas_comparativo_largura(df_metricas_ciclo: pd.DataFrame) -> pd.DataFrame:
    """Pivot Ciclo × Item para st.bar_chart / visualização lado a lado."""
    if df_metricas_ciclo is None or df_metricas_ciclo.empty:
        return pd.DataFrame()
    pivot = df_metricas_ciclo.pivot_table(
        index="Ciclo", columns="Item", values="Média", aggfunc="mean"
    )
    for item in ITENS_METRICA:
        if item not in pivot.columns:
            pivot[item] = pd.NA
    return pivot.reindex(columns=list(ITENS_METRICA))


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _resolver_fonte_pdf(pdf) -> tuple[str, bool]:
    """Retorna (nome_fonte, unicode). Tenta DejaVu/Arial; senão Helvetica ASCII."""
    candidatos = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
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
) -> bytes:
    """PDF resumido do recorte filtrado (sem comentários longos)."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    fonte, unicode_ok = _resolver_fonte_pdf(pdf)

    def t(valor) -> str:
        s = _texto(valor)
        return s if unicode_ok else _sem_acento(s)

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
    titulo("Dashboard — avaliação do curso")
    corpo(f"Gerado em {agora}")
    corpo(f"Modo de gráficos: {modo_grafico}")
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
    nps_txt = f"{nps.nps:.1f}" if nps.nps is not None else "—"
    corpo(
        f"NPS: {nps_txt} | Respondentes únicos: {n_alunos} | "
        f"Base NPS: {nps.respondentes} | "
        f"Promotores: {nps.promotores} ({nps.pct_promotores}%) | "
        f"Passivos: {nps.passivos} ({nps.pct_passivos}%) | "
        f"Detratores: {nps.detratores} ({nps.pct_detratores}%)"
    )
    pdf.ln(2)

    if nps_ciclos is not None and not nps_ciclos.empty:
        titulo("NPS por ciclo", 12)
        for _, row in nps_ciclos.iterrows():
            val = row.get("NPS")
            val_txt = f"{val:.1f}" if val is not None and pd.notna(val) else "—"
            corpo(f"- {row.get('Ciclo')}: NPS {val_txt} (n={int(row.get('Respondentes') or 0)})")
        pdf.ln(2)

    if metricas is not None and not metricas.empty:
        titulo("Métricas gerais (0–5)", 12)
        for _, row in metricas.iterrows():
            corpo(f"- {row.get('Item')}: média {row.get('Média')} (n={int(row.get('N') or 0)})")
        pdf.ln(2)

    if didatica is not None and not didatica.empty:
        titulo("Didática dos professores (0–5)", 12)
        for _, row in didatica.iterrows():
            corpo(f"- {row.get('Professor')}: média {row.get('Média')} (n={int(row.get('N') or 0)})")

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
