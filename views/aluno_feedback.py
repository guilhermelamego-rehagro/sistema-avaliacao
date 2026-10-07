"""Tela do aluno: feedback do ciclo publicado pela orientadora."""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from domain.dossie_aluno import titulo_ciclos
from domain.feedback_aluno import ATENCAO, BOM, OTIMO
from navigation import ROTA_AVALIACAO_GRUPO_ALUNO, ROTA_RESULTADOS_PARES, ir_para

_COR_FAIXA = {ATENCAO: "#f6c89f", BOM: "#d3ebc8", OTIMO: "#86c47a"}
_COR_TEXTO = {ATENCAO: "#b45309", BOM: "#4d7c0f", OTIMO: "#15803d"}
_MARCADOR = "#0b4f2e"
_MARCADOR_ACUMULADO = "#7c9a8a"


def _posicao(valor: float, cortes: tuple[float, float], maximo: float) -> float:
    """Posição (0–100) numa régua de três faixas de mesma largura, interpolando dentro da faixa."""
    limites = (0.0, float(cortes[0]), float(cortes[1]), maximo)
    v = min(max(valor, 0.0), maximo)
    for i in range(3):
        ini, fim = limites[i], limites[i + 1]
        if v < fim or i == 2:
            frac = (v - ini) / (fim - ini) if fim > ini else 1.0
            return (i + frac) * 100 / 3
    return 100.0


def _marcador(m: dict, valor, *, destaque: bool) -> str:
    if valor is None:
        return ""
    pos = _posicao(float(valor), m["cortes"], float(m["maximo"]))
    if destaque:
        estilo = f"width:20px;height:20px;top:-4px;z-index:2;background:{_MARCADOR};opacity:1"
        meio = 10
    else:
        estilo = f"width:16px;height:16px;top:-2px;z-index:1;background:{_MARCADOR_ACUMULADO};opacity:0.75"
        meio = 8
    return (
        f"<div style='position:absolute;left:calc({pos:.2f}% - {meio}px);{estilo};border-radius:50%;"
        f"border:3px solid #fff;box-shadow:0 0 0 1px {_MARCADOR_ACUMULADO if not destaque else _MARCADOR}'></div>"
    )


def _rotulo(texto: str, faixa: str | None, vazio: str = "ainda sem nota") -> str:
    if not faixa:
        return f"<span style='color:#888'>{vazio}</span>"
    return f"{escape(texto)} · <b style='color:{_COR_TEXTO[faixa]}'>{faixa}</b>"


def _regua(m: dict) -> str:
    larguras = (100 / 3,) * 3
    faixa = m.get("faixa")
    tem_acumulado = "acumulado" in m
    rotulo = _rotulo(m["texto"], faixa, "sem nota neste ciclo" if m.get("faixa_acumulado") else "ainda sem nota")
    if tem_acumulado:
        rotulo += (
            "<br><span style='font-size:0.8rem;color:#6b7280'>na disciplina: "
            f"{_rotulo(m['texto_acumulado'], m.get('faixa_acumulado'))}</span>"
        )
    colorida = bool(faixa or m.get("faixa_acumulado"))
    segmentos = "".join(
        f"<div style='width:{w:.2f}%;background:{_COR_FAIXA[f] if colorida else '#e5e7eb'};"
        f"{'border-radius:7px 0 0 7px;' if i == 0 else ''}{'border-radius:0 7px 7px 0;' if i == 2 else ''}'></div>"
        for i, (w, f) in enumerate(zip(larguras, (ATENCAO, BOM, OTIMO)))
    )
    marcador = _marcador(m, m.get("acumulado"), destaque=False) + _marcador(m, m.get("valor"), destaque=True)
    un = "%" if m.get("chave", "").startswith("Pct_") else ""
    c1, c2 = (f"{float(c):g}".replace(".", ",") for c in m["cortes"])
    faixas_txt = (f"abaixo de {c1}{un}", f"{c1}–{c2}{un}", f"{c2}{un} ou mais")
    legendas = "".join(
        f"<span style='width:{w:.2f}%;text-align:center;line-height:1.2'>{f}<br>{t}</span>"
        for w, f, t in zip(larguras, (ATENCAO, BOM, OTIMO), faixas_txt)
    )
    return (
        "<div style='margin:4px 0 18px 0'>"
        f"<div style='display:flex;justify-content:space-between;gap:8px'><b>{escape(m['titulo'])}</b>"
        f"<span style='text-align:right;line-height:1.3'>{rotulo}</span></div>"
        f"<div style='position:relative;display:flex;height:12px;margin-top:8px'>{segmentos}{marcador}</div>"
        f"<div style='display:flex;font-size:0.75rem;color:#6b7280;margin-top:4px'>{legendas}</div>"
        "</div>"
    )


def render_painel(
    conteudo: dict, mensagem: str = "", autor: str = "", *, chave: str = "fb", atalhos: bool = True
) -> None:
    """Painel do aluno (também usado na pré-visualização da orientadora)."""
    metricas = conteudo.get("metricas", [])
    st.markdown("#### Seus indicadores")
    nome_ciclo = escape(str(conteudo.get("nome_ciclo") or "ciclo"))
    acumulados = conteudo.get("ciclos_acumulado") or []
    if acumulados:
        st.markdown(
            f"<div style='font-size:0.9rem;margin-bottom:10px'>"
            f"<span style='color:{_MARCADOR};font-size:1.3rem;vertical-align:-2px'>●</span> <b>{nome_ciclo}</b>"
            " &nbsp;&nbsp; "
            f"<span style='color:{_MARCADOR_ACUMULADO};opacity:0.75;font-size:1.1rem;vertical-align:-1px'>●</span> "
            f"Disciplina até agora ({escape(titulo_ciclos(acumulados))})</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='font-size:0.9rem;margin-bottom:10px'>Indicadores do <b>{nome_ciclo}</b>.</div>",
            unsafe_allow_html=True,
        )
    col_a, col_b = st.columns(2, gap="large")
    for i, m in enumerate(metricas):
        (col_a if i % 2 == 0 else col_b).markdown(_regua(m), unsafe_allow_html=True)
    st.caption(
        "As faixas usam as referências do curso (presença mínima de 75% na disciplina e nota de aprovação de 70%), "
        "não a comparação com colegas."
    )

    if conteudo.get("bem"):
        st.markdown("#### O que foi bem")
        st.success("\n".join(f"- {t}" for t in conteudo["bem"]))
    if conteudo.get("melhorar"):
        st.markdown("#### O que melhorar")
        st.warning("\n".join(f"- {t}" for t in conteudo["melhorar"]))
    st.markdown("#### Próximo passo")
    st.info(conteudo.get("proximo", ""))

    if str(mensagem or "").strip():
        st.markdown(f"#### Mensagem {'de ' + autor if autor else 'da orientadora'}")
        with st.container(border=True):
            st.markdown(mensagem)

    if not atalhos:
        return
    c1, c2 = st.columns(2)
    if c1.button("Ver comentários dos colegas", key=f"{chave}_pares", width="stretch"):
        ir_para(ROTA_RESULTADOS_PARES)
    if c2.button("Ver comentários da banca", key=f"{chave}_banca", width="stretch"):
        ir_para(ROTA_AVALIACAO_GRUPO_ALUNO)


def _fmt_publicado(valor) -> str:
    ts = pd.to_datetime(valor, utc=True, errors="coerce")
    return "" if pd.isna(ts) else ts.tz_convert("America/Sao_Paulo").strftime("%d/%m/%Y")


def render(usuario: dict) -> None:
    from data.supabase_feedback import listar_publicados_do_aluno

    st.header("Meu feedback")
    try:
        publicados = listar_publicados_do_aluno(usuario["email"])
    except Exception:
        st.warning("O feedback está indisponível no momento. Tente novamente mais tarde.")
        return
    if not publicados:
        st.info("Sua orientadora ainda não publicou o feedback de nenhum ciclo. Ele aparece aqui assim que for liberado.")
        return

    nomes = [p.get("nome_ciclo") or p["id_ciclo"] for p in publicados]
    escolha = st.selectbox("Ciclo", nomes, index=0, key="fb_aluno_ciclo") if len(publicados) > 1 else nomes[0]
    item = publicados[nomes.index(escolha)]
    publicado = _fmt_publicado(item.get("publicado_em"))
    st.caption(f"Feedback do **{escolha}**" + (f", publicado em {publicado}." if publicado else "."))
    render_painel(item.get("conteudo") or {}, item.get("mensagem", ""), item.get("autor_nome", ""), chave="fb_aluno")
