"""Conferência de avaliações de entregas — matriz grupos × ciclos (somente coordenador)."""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.avaliacoes import (
    TIPO_AVALIACAO_CONFERENCIA,
    carregar_painel_conferencia,
    formatar_nota_entrega,
    parse_nota_entrega,
    salvar_avaliacao_grupo,
)
from domain.ciclos import ordenar_ciclos
from domain.encontro_presencial import ciclos_visiveis_avaliacao
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.logs import registrar_log
from utils.preferencias_sala import selectbox_sala
from utils.ordenacao import ordenar_df_grupos, ordenar_grupos_lista

_LARGURA_SALA_REM = 6.75
_LARGURA_GRUPO_REM = 2.5
_LARGURA_CAMPO_REM = 2.5
_LARGURA_TOTAL_REM = 2.3
_ALTURA_CAMPO_REM = 1.6
_GAP_REM = 0.06

# Streamlit trocou o data-testid das colunas de "column" para "stColumn" em
# versões recentes. Mantemos as duas variantes para funcionar independente
# da versão instalada.
_TESTIDS_COLUNA = ("stColumn", "column")


def _sel_coluna(nth: str) -> str:
    seletores = [
        f'.st-key-coord_ent_matriz [data-testid="stHorizontalBlock"] '
        f'> [data-testid="{testid}"]:nth-child({nth})'
        for testid in _TESTIDS_COLUNA
    ]
    return ",\n".join(seletores)


def _css_matriz(n_ciclos: int) -> str:
    min_largura = (
        _LARGURA_SALA_REM
        + _LARGURA_GRUPO_REM
        + n_ciclos * (2 * _LARGURA_CAMPO_REM + _LARGURA_TOTAL_REM)
    )
    left_grupo = _LARGURA_SALA_REM + _GAP_REM
    return f"""
<style>
.st-key-coord_ent_matriz {{
    overflow-x: auto;
    width: 100%;
    padding-bottom: 0.5rem;
}}
.st-key-coord_ent_matriz [data-testid="stVerticalBlock"] {{
    gap: {_GAP_REM}rem !important;
}}
.st-key-coord_ent_matriz [data-testid="stElementContainer"],
.st-key-coord_ent_matriz [data-testid="stHorizontalBlock"] {{
    margin-top: 0 !important;
    margin-bottom: 0 !important;
}}
.st-key-coord_ent_matriz [data-testid="stHorizontalBlock"] {{
    width: max-content !important;
    min-width: {min_largura}rem;
    flex-wrap: nowrap !important;
    gap: {_GAP_REM}rem !important;
}}
{_sel_coluna("1")},
{_sel_coluna("1")} > div {{
    background-color: #ffffff !important;
}}
{_sel_coluna("2")},
{_sel_coluna("2")} > div {{
    background-color: #ffffff !important;
}}
{_sel_coluna("1")} {{
    flex: 0 0 {_LARGURA_SALA_REM}rem !important;
    width: {_LARGURA_SALA_REM}rem !important;
    max-width: {_LARGURA_SALA_REM}rem !important;
    position: sticky !important;
    left: 0 !important;
    z-index: 5 !important;
    box-shadow: 1px 0 0 #e0e0e0;
}}
{_sel_coluna("2")} {{
    flex: 0 0 {_LARGURA_GRUPO_REM}rem !important;
    width: {_LARGURA_GRUPO_REM}rem !important;
    max-width: {_LARGURA_GRUPO_REM}rem !important;
    position: sticky !important;
    left: {left_grupo}rem !important;
    z-index: 5 !important;
    box-shadow: 2px 0 6px rgba(0, 0, 0, 0.08);
}}
{_sel_coluna("3n+3")} {{
    flex: 0 0 {_LARGURA_CAMPO_REM}rem !important;
    width: {_LARGURA_CAMPO_REM}rem !important;
    max-width: {_LARGURA_CAMPO_REM}rem !important;
    z-index: 1 !important;
}}
{_sel_coluna("3n+4")} {{
    flex: 0 0 {_LARGURA_CAMPO_REM}rem !important;
    width: {_LARGURA_CAMPO_REM}rem !important;
    max-width: {_LARGURA_CAMPO_REM}rem !important;
    z-index: 1 !important;
}}
{_sel_coluna("3n+5")} {{
    flex: 0 0 {_LARGURA_TOTAL_REM}rem !important;
    width: {_LARGURA_TOTAL_REM}rem !important;
    max-width: {_LARGURA_TOTAL_REM}rem !important;
    z-index: 1 !important;
}}
.st-key-coord_ent_matriz [data-testid="stWidgetLabel"] {{
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}}
.st-key-coord_ent_matriz [data-testid="stTextInput"] {{
    margin: 0 !important;
}}
.st-key-coord_ent_matriz [data-testid="stTextInput"] > div {{
    margin: 0 !important;
    min-height: 0 !important;
}}
.st-key-coord_ent_matriz [data-testid="stTextInput"] div[data-baseweb="input"] {{
    height: {_ALTURA_CAMPO_REM}rem !important;
    min-height: {_ALTURA_CAMPO_REM}rem !important;
    box-sizing: border-box !important;
}}
.st-key-coord_ent_matriz [data-testid="stTextInput"] div[data-baseweb="base-input"] {{
    height: 100% !important;
    padding: 0 0.2rem !important;
    box-sizing: border-box !important;
}}
.st-key-coord_ent_matriz [data-testid="stTextInput"] input {{
    height: 100% !important;
    padding: 0 !important;
    font-size: 0.82rem !important;
    box-sizing: border-box !important;
}}
.st-key-coord_ent_matriz .coord-total {{
    background-color: #e8f4ea;
    color: #004D28;
    font-weight: 700;
    padding: 0;
    text-align: center;
    border-radius: 4px;
    border: 1px solid #c8e6c9;
    height: {_ALTURA_CAMPO_REM}rem;
    min-height: {_ALTURA_CAMPO_REM}rem;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.82rem;
    box-sizing: border-box;
}}
.st-key-coord_ent_matriz .coord-nota {{
    background-color: #f5f5f5;
    color: #222;
    font-weight: 600;
    padding: 0;
    text-align: center;
    border-radius: 4px;
    border: 1px solid #e0e0e0;
    height: {_ALTURA_CAMPO_REM}rem;
    min-height: {_ALTURA_CAMPO_REM}rem;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.82rem;
    box-sizing: border-box;
    cursor: help;
}}
.st-key-coord_ent_matriz .coord-nota-conf,
.st-key-coord_ent_matriz .coord-total.coord-nota-conf {{
    background-color: #fff3e0;
    border-color: #ffcc80;
    color: #e65100;
}}
.st-key-coord_ent_matriz .coord-header {{
    font-size: 0.76rem;
    font-weight: 700;
    text-align: center;
    padding: 0.15rem 0.1rem;
    line-height: 1.1;
}}
.st-key-coord_ent_matriz .coord-header-fixo {{
    background-color: #ffffff !important;
    position: relative;
    z-index: 6;
}}
.st-key-coord_ent_matriz .coord-grupo,
.st-key-coord_ent_matriz .coord-sala {{
    background-color: #ffffff;
}}
.st-key-coord_ent_matriz .coord-grupo {{
    font-weight: 600;
    text-align: center;
    font-size: 0.86rem;
    height: {_ALTURA_CAMPO_REM}rem;
    display: flex;
    align-items: center;
    justify-content: center;
}}
.st-key-coord_ent_matriz .coord-sala {{
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 0.84rem;
    height: {_ALTURA_CAMPO_REM}rem;
    display: flex;
    align-items: center;
    justify-content: center;
}}
</style>
"""


def _codigos_ciclo(ciclos: pd.DataFrame) -> dict[str, str]:
    codigos: dict[str, str] = {}
    for i, (_, row) in enumerate(ciclos.iterrows(), start=1):
        nome = str(row["Nome_Ciclo"])
        nome_l = nome.lower()
        if "entrega" in nome_l or "final" in nome_l:
            codigos[nome] = "EF"
            continue
        m = re.search(r"(\d+)", nome)
        codigos[nome] = f"C{m.group(1)}" if m else f"C{i}"
    return codigos


def _col_ap(codigo: str) -> str:
    return f"{codigo}_A"


def _col_ct(codigo: str) -> str:
    return f"{codigo}_C"


def _col_total(codigo: str) -> str:
    return f"{codigo}_T"


def _col_origem(codigo: str) -> str:
    return f"{codigo}_O"


def _slug(texto: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", str(texto).strip()).strip("_") or "x"


def _widget_key(id_disc: str, grupo, sala, cod: str, campo: str) -> str:
    return f"cent_{id_disc}_{_slug(grupo)}_{_slug(sala)}_{cod}_{campo}"


def _chave_grupo_sala(grupo, sala) -> tuple[str, str]:
    return str(grupo).strip(), str(sala).strip()


def _info_painel(
    painel: dict[tuple[str, str, str], dict],
    grupo: str,
    sala: str,
    id_ciclo: str,
) -> dict | None:
    grupo = str(grupo).strip()
    sala = str(sala).strip()
    id_ciclo = str(id_ciclo).strip()
    return painel.get((grupo, sala, id_ciclo)) or painel.get((grupo, "", id_ciclo))


def _tooltip_painel(info: dict | None) -> str:
    if not info or not info.get("oficial"):
        return "Sem avaliações da banca"
    oficial = info["oficial"]
    if oficial.get("origem") == "conferencia":
        cabeca = "Nota da conferência (substitui a média)"
    else:
        n = oficial.get("n_avaliadores") or 0
        cabeca = f"Média da banca ({n} professor(es))"
    linhas = [cabeca]
    for a in info.get("avaliadores") or []:
        marca = " [conferência]" if a.get("eh_conferencia") else ""
        linhas.append(
            f"{a.get('nome', '?')}{marca}: "
            f"A {formatar_nota_entrega(a['nota_apresentacao'])} · "
            f"C {formatar_nota_entrega(a['nota_conteudo'])} · "
            f"T {formatar_nota_entrega(a['nota_total'])}"
        )
    return "\n".join(linhas)


def _calcular_total_celula(ap_txt: str, ct_txt: str) -> str:
    ap_txt = str(ap_txt).strip()
    ct_txt = str(ct_txt).strip()
    if not ap_txt and not ct_txt:
        return "0,0"
    nota_ap = parse_nota_entrega(ap_txt) if ap_txt else None
    nota_ct = parse_nota_entrega(ct_txt) if ct_txt else None
    if nota_ap is not None and nota_ct is not None:
        return formatar_nota_entrega(round(nota_ap + nota_ct, 1))
    return "0,0"


def _valor_invalido(valor: str) -> bool:
    valor = str(valor).strip()
    if not valor:
        return False
    nota = parse_nota_entrega(valor)
    return nota is None or nota > 5


def _css_invalidos(chaves: set[str]) -> str:
    if not chaves:
        return ""
    regras = [
        f'.st-key-{chave} div[data-baseweb="input"] {{ '
        f"border: 1px solid #b71c1c !important; "
        f"background-color: #ffcdd2 !important; }}"
        for chave in sorted(chaves)
    ]
    return "<style>" + "\n".join(regras) + "</style>"


def _inferir_tipo_ciclo(nome_ciclo: str) -> str:
    nome_l = nome_ciclo.lower()
    if "entrega" in nome_l or "final" in nome_l:
        return "Entrega_Final"
    return "Ciclo"


def _listar_grupos_disciplina(entrancia: pd.DataFrame) -> pd.DataFrame:
    base = entrancia[["Grupo", "Sala"]].drop_duplicates().copy()
    base["Sala"] = base["Sala"].astype(str).str.strip()
    return ordenar_df_grupos(base)


def _montar_grid(
    grupos: pd.DataFrame,
    ciclos: pd.DataFrame,
    painel: dict[tuple[str, str, str], dict],
    codigos: dict[str, str],
) -> pd.DataFrame:
    linhas = []
    for _, row in grupos.iterrows():
        grupo = str(row["Grupo"]).strip()
        sala = str(row["Sala"]).strip()
        linha = {"Grupo": row["Grupo"], "Sala": sala}
        for _, ciclo in ciclos.iterrows():
            nome = str(ciclo["Nome_Ciclo"])
            cod = codigos[nome]
            id_ciclo = str(ciclo["ID_Ciclo"]).strip()
            info = _info_painel(painel, grupo, sala, id_ciclo)
            aval = (info or {}).get("oficial")
            if aval:
                linha[_col_ap(cod)] = formatar_nota_entrega(aval["nota_apresentacao"])
                linha[_col_ct(cod)] = formatar_nota_entrega(aval["nota_conteudo"])
                linha[_col_total(cod)] = formatar_nota_entrega(aval["nota_total"])
                linha[_col_origem(cod)] = str(aval.get("origem") or "")
            else:
                linha[_col_ap(cod)] = ""
                linha[_col_ct(cod)] = ""
                linha[_col_total(cod)] = ""
                linha[_col_origem(cod)] = ""
        linhas.append(linha)
    return ordenar_df_grupos(pd.DataFrame(linhas))


def _mapa_linhas(df: pd.DataFrame) -> dict[tuple[str, str], pd.Series]:
    mapa: dict[tuple[str, str], pd.Series] = {}
    for _, row in df.iterrows():
        mapa[_chave_grupo_sala(row["Grupo"], row["Sala"])] = row
    return mapa


def _contar_pendentes(df: pd.DataFrame, codigos_visiveis: dict[str, str]) -> int:
    pendentes = 0
    for _, row in df.iterrows():
        for cod in codigos_visiveis.values():
            ap = str(row[_col_ap(cod)]).strip()
            ct = str(row[_col_ct(cod)]).strip()
            if not ap and not ct:
                pendentes += 1
    return pendentes


def _ciclos_visiveis(nomes_todos: list[str], selecionados: list[str]) -> list[str]:
    if not selecionados:
        return nomes_todos
    sel = set(selecionados)
    return [n for n in nomes_todos if n in sel]


def _sincronizar_campos(
    df_grid: pd.DataFrame,
    id_disc: str,
    codigos: dict[str, str],
    nomes_ciclos_visiveis: list[str],
    forcar: bool = False,
):
    for _, row in df_grid.iterrows():
        grupo, sala = row["Grupo"], row["Sala"]
        for nome in nomes_ciclos_visiveis:
            cod = codigos[nome]
            edit_key = _widget_key(id_disc, grupo, sala, cod, "edit")
            if st.session_state.get(edit_key) and not forcar:
                continue
            ap_key = _widget_key(id_disc, grupo, sala, cod, "ap")
            ct_key = _widget_key(id_disc, grupo, sala, cod, "ct")
            tot_key = _widget_key(id_disc, grupo, sala, cod, "tot")

            if forcar or ap_key not in st.session_state:
                st.session_state[ap_key] = str(row[_col_ap(cod)]).strip()
            if forcar or ct_key not in st.session_state:
                st.session_state[ct_key] = str(row[_col_ct(cod)]).strip()
            if forcar or tot_key not in st.session_state:
                st.session_state[tot_key] = _calcular_total_celula(
                    st.session_state.get(ap_key, ""),
                    st.session_state.get(ct_key, ""),
                )


def _on_campo_change(id_disc: str, grupo, sala, cod: str, campo: str):
    ap_key = _widget_key(id_disc, grupo, sala, cod, "ap")
    ct_key = _widget_key(id_disc, grupo, sala, cod, "ct")
    tot_key = _widget_key(id_disc, grupo, sala, cod, "tot")
    inv_key = f"_coord_ent_invalid_{id_disc}"

    st.session_state[tot_key] = _calcular_total_celula(
        st.session_state.get(ap_key, ""),
        st.session_state.get(ct_key, ""),
    )

    invalidos = st.session_state.setdefault(inv_key, set())
    for chave_campo in (ap_key, ct_key):
        valor = str(st.session_state.get(chave_campo, "")).strip()
        if _valor_invalido(valor):
            invalidos.add(chave_campo)
        else:
            invalidos.discard(chave_campo)


def _coletar_editado(
    df_grid: pd.DataFrame,
    id_disc: str,
    codigos: dict[str, str],
    nomes_ciclos_visiveis: list[str],
) -> pd.DataFrame:
    """Coleta só células em modo alteração; as demais repetem o valor oficial."""
    linhas = []
    for _, row in df_grid.iterrows():
        grupo, sala = row["Grupo"], row["Sala"]
        linha = {"Grupo": grupo, "Sala": sala}
        for nome in nomes_ciclos_visiveis:
            cod = codigos[nome]
            edit_key = _widget_key(id_disc, grupo, sala, cod, "edit")
            if st.session_state.get(edit_key):
                ap_key = _widget_key(id_disc, grupo, sala, cod, "ap")
                ct_key = _widget_key(id_disc, grupo, sala, cod, "ct")
                tot_key = _widget_key(id_disc, grupo, sala, cod, "tot")
                linha[_col_ap(cod)] = str(st.session_state.get(ap_key, "")).strip()
                linha[_col_ct(cod)] = str(st.session_state.get(ct_key, "")).strip()
                linha[_col_total(cod)] = str(st.session_state.get(tot_key, "")).strip()
            else:
                linha[_col_ap(cod)] = str(row[_col_ap(cod)]).strip()
                linha[_col_ct(cod)] = str(row[_col_ct(cod)]).strip()
                linha[_col_total(cod)] = str(row.get(_col_total(cod), "")).strip()
        linhas.append(linha)
    return pd.DataFrame(linhas)


def _validar_alteracoes(
    original: pd.DataFrame,
    editado: pd.DataFrame,
    ciclos: pd.DataFrame,
    codigos: dict[str, str],
) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str, str, str, float, float]]]:
    invalidas: list[tuple[int, str, str]] = []
    validas: list[tuple[int, str, str, str, str, float, float]] = []
    orig_map = _mapa_linhas(original)

    for idx in range(len(editado)):
        chave = _chave_grupo_sala(editado.iloc[idx]["Grupo"], editado.iloc[idx]["Sala"])
        if chave not in orig_map:
            continue
        orig_row = orig_map[chave]
        grupo, sala = chave

        for _, ciclo in ciclos.iterrows():
            nome = str(ciclo["Nome_Ciclo"])
            id_ciclo = str(ciclo["ID_Ciclo"]).strip()
            cod = codigos[nome]
            col_ap = _col_ap(cod)
            col_ct = _col_ct(cod)

            ap_novo = str(editado.iloc[idx][col_ap]).strip()
            ct_novo = str(editado.iloc[idx][col_ct]).strip()
            ap_ant = str(orig_row[col_ap]).strip()
            ct_ant = str(orig_row[col_ct]).strip()

            if ap_novo == ap_ant and ct_novo == ct_ant:
                continue

            nota_ap = parse_nota_entrega(ap_novo)
            nota_ct = parse_nota_entrega(ct_novo)

            if nota_ap is None or nota_ct is None or nota_ap > 5 or nota_ct > 5:
                invalidas.append(
                    (idx, col_ap if nota_ap is None or nota_ap > 5 else col_ct, ap_novo or ct_novo)
                )
                continue

            validas.append((idx, grupo, sala, id_ciclo, nome, nota_ap, nota_ct))

    return invalidas, validas


def _salvar_validas(validas: list, id_disciplina: str, usuario: dict) -> int:
    salvos = 0
    for _, grupo, sala, id_ciclo, nome_ciclo, nota_ap, nota_ct in validas:
        salvar_avaliacao_grupo(
            id_ciclo=id_ciclo,
            nome_ciclo=nome_ciclo,
            id_disciplina=id_disciplina,
            sala=sala,
            grupo=grupo,
            nota_apresentacao=nota_ap,
            nota_conteudo=nota_ct,
            comentario=f"Conferência coordenador — {usuario.get('nome', '')}",
            email_avaliador=usuario["email"],
            nome_avaliador=usuario["nome"],
            tipo=TIPO_AVALIACAO_CONFERENCIA,
        )
        salvos += 1
    return salvos


def _pesos_colunas(n_ciclos: int) -> list[int]:
    return [1] * (2 + 3 * n_ciclos)


def _render_cabecalho(cols, nomes_ciclos_visiveis: list[str], codigos: dict[str, str]):
    cols[0].markdown(
        '<div class="coord-header coord-header-fixo">Sala</div>',
        unsafe_allow_html=True,
    )
    cols[1].markdown(
        '<div class="coord-header coord-header-fixo">Gr.</div>',
        unsafe_allow_html=True,
    )
    for i, nome in enumerate(nomes_ciclos_visiveis):
        cod = codigos[nome]
        base = 2 + i * 3
        cols[base].markdown(f'<div class="coord-header">{cod}·A</div>', unsafe_allow_html=True)
        cols[base + 1].markdown(f'<div class="coord-header">{cod}·C</div>', unsafe_allow_html=True)
        cols[base + 2].markdown(f'<div class="coord-header">{cod}·T</div>', unsafe_allow_html=True)


def _render_linha(
    cols,
    grupo,
    sala: str,
    id_disc: str,
    nomes_ciclos_visiveis: list[str],
    codigos: dict[str, str],
    painel: dict[tuple[str, str, str], dict],
    ciclos: pd.DataFrame,
):
    import html as html_mod

    cols[0].markdown(f'<div class="coord-sala" title="{html_mod.escape(sala)}">{html_mod.escape(sala)}</div>', unsafe_allow_html=True)
    cols[1].markdown(f'<div class="coord-grupo">{html_mod.escape(str(grupo))}</div>', unsafe_allow_html=True)

    mapa_ciclo_id = {
        str(r["Nome_Ciclo"]): str(r["ID_Ciclo"]).strip() for _, r in ciclos.iterrows()
    }

    for i, nome in enumerate(nomes_ciclos_visiveis):
        cod = codigos[nome]
        base = 2 + i * 3
        id_ciclo = mapa_ciclo_id.get(nome, "")
        info = _info_painel(painel, str(grupo), sala, id_ciclo)
        tip = html_mod.escape(_tooltip_painel(info))
        origem = ""
        if info and info.get("oficial"):
            origem = str(info["oficial"].get("origem") or "")

        ap_key = _widget_key(id_disc, grupo, sala, cod, "ap")
        ct_key = _widget_key(id_disc, grupo, sala, cod, "ct")
        tot_key = _widget_key(id_disc, grupo, sala, cod, "tot")
        edit_key = _widget_key(id_disc, grupo, sala, cod, "edit")

        editando = bool(st.session_state.get(edit_key))
        if editando:
            cols[base].text_input(
                f"{cod}·A",
                label_visibility="collapsed",
                key=ap_key,
                on_change=_on_campo_change,
                args=(id_disc, grupo, sala, cod, "ap"),
            )
            cols[base + 1].text_input(
                f"{cod}·C",
                label_visibility="collapsed",
                key=ct_key,
                on_change=_on_campo_change,
                args=(id_disc, grupo, sala, cod, "ct"),
            )
            total = str(st.session_state.get(tot_key, "0,0"))
            cols[base + 2].markdown(
                f'<div class="coord-total" title="{tip}">{html_mod.escape(total)}</div>',
                unsafe_allow_html=True,
            )
            cols[base + 2].checkbox("Alt.", key=edit_key, help="Desmarque para cancelar a edição")
        else:
            ap = str(st.session_state.get(ap_key, "")).strip()
            ct = str(st.session_state.get(ct_key, "")).strip()
            tot = str(st.session_state.get(tot_key, "")).strip()
            if not tot and (ap or ct):
                tot = _calcular_total_celula(ap, ct)
            marca = " *" if origem == "conferencia" else ""
            cls_extra = " coord-nota-conf" if origem == "conferencia" else ""
            cols[base].markdown(
                f'<div class="coord-nota{cls_extra}" title="{tip}">{html_mod.escape(ap or "—")}{marca}</div>',
                unsafe_allow_html=True,
            )
            cols[base + 1].markdown(
                f'<div class="coord-nota{cls_extra}" title="{tip}">{html_mod.escape(ct or "—")}{marca}</div>',
                unsafe_allow_html=True,
            )
            cols[base + 2].markdown(
                f'<div class="coord-total{cls_extra}" title="{tip}">{html_mod.escape(tot or "—")}{marca}</div>',
                unsafe_allow_html=True,
            )
            cols[base + 2].checkbox(
                "Alt.",
                key=edit_key,
                help="Marque para alterar esta nota (grava como conferência e substitui a média)",
            )


def render(usuario: dict):
    st.header("Conferir notas grupos")
    st.caption(
        "Visão da **média da banca** (A / C / T). Passe o mouse na nota para ver "
        "quais professores avaliaram. Marque **Alt.** para editar: o lançamento grava "
        "como **conferência** e **substitui a média**. "
        "Asterisco (*) = já há nota de conferência. "
        "Colunas com largura fixa — ao rolar, **Sala** e **Gr.** permanecem visíveis."
    )

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox(
        "Disciplina:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
        key="coord_ent_disc",
    )
    id_disc = id_disciplina_por_nome(df_disc, disc_sel)

    df_ciclos = ler_aba("Ciclos")
    ciclos = df_ciclos[df_ciclos["ID_Disciplina"].astype(str).str.strip() == id_disc]
    ciclos = ordenar_ciclos(ciclos_visiveis_avaliacao(ciclos, id_disc))
    if ciclos.empty:
        st.warning("Nenhum ciclo cadastrado.")
        return

    codigos = _codigos_ciclo(ciclos)
    nomes_ciclos_todos = ciclos["Nome_Ciclo"].astype(str).tolist()

    df_entrancia = ler_aba("Entrancia_Turma")
    entrancia = df_entrancia[df_entrancia["ID_Disciplina"].astype(str).str.strip() == id_disc]
    if entrancia.empty:
        st.warning("Nenhum grupo cadastrado na entrância.")
        return

    grupos = _listar_grupos_disciplina(entrancia)

    c1, c2, c3 = st.columns(3)
    salas = sorted(grupos["Sala"].dropna().astype(str).unique().tolist())
    with c1:
        filtro_sala = selectbox_sala(
            "Filtrar sala:",
            salas,
            key="coord_ent_sala",
            usuario=usuario,
        )
    opcoes_grupo = ordenar_grupos_lista(grupos["Grupo"].astype(str).unique().tolist())
    filtro_grupo = c2.selectbox("Filtrar grupo:", ["Todos"] + opcoes_grupo, key="coord_ent_grupo")
    ciclos_filtro = c3.multiselect(
        "Ciclos (vazio = todos):",
        nomes_ciclos_todos,
        key="coord_ent_ciclos",
    )

    if filtro_sala != "Todas":
        grupos = grupos[grupos["Sala"].astype(str) == filtro_sala]
    if filtro_grupo != "Todos":
        grupos = grupos[grupos["Grupo"].astype(str) == str(filtro_grupo)]
    grupos = ordenar_df_grupos(grupos)

    if grupos.empty:
        st.info("Nenhum grupo encontrado com os filtros aplicados.")
        return

    nomes_ciclos_visiveis = _ciclos_visiveis(nomes_ciclos_todos, ciclos_filtro)
    codigos_visiveis = {n: codigos[n] for n in nomes_ciclos_visiveis}
    ciclos_visiveis_df = ciclos[ciclos["Nome_Ciclo"].astype(str).isin(nomes_ciclos_visiveis)]

    painel = carregar_painel_conferencia(id_disc)
    df_grid = _montar_grid(grupos, ciclos, painel, codigos)
    pendentes = _contar_pendentes(df_grid, codigos_visiveis)

    m1, m2, m3 = st.columns(3)
    m1.metric("Grupos exibidos", len(df_grid))
    m2.metric("Ciclos na tela", len(nomes_ciclos_visiveis))
    m3.metric("Combinações grupo/ciclo sem nota", pendentes)

    if nomes_ciclos_visiveis:
        st.caption(" · ".join(f"**{codigos[n]}** = {n}" for n in nomes_ciclos_visiveis))

    ctx = (
        f"{id_disc}|{filtro_sala}|{filtro_grupo}|"
        f"{','.join(nomes_ciclos_visiveis)}|{len(df_grid)}|{len(painel)}"
    )
    if st.session_state.get("_coord_ent_ctx") != ctx:
        st.session_state["_coord_ent_ctx"] = ctx
        st.session_state.pop(f"_coord_ent_invalid_{id_disc}", None)
        _sincronizar_campos(df_grid, id_disc, codigos, nomes_ciclos_visiveis, forcar=True)
    else:
        _sincronizar_campos(df_grid, id_disc, codigos, nomes_ciclos_visiveis, forcar=False)

    invalidos = st.session_state.get(f"_coord_ent_invalid_{id_disc}", set())
    st.markdown(_css_matriz(len(nomes_ciclos_visiveis)), unsafe_allow_html=True)
    st.markdown(_css_invalidos(invalidos), unsafe_allow_html=True)

    st.subheader("Conferência por grupo")
    with st.container(key="coord_ent_matriz"):
        pesos = _pesos_colunas(len(nomes_ciclos_visiveis))
        _render_cabecalho(st.columns(pesos), nomes_ciclos_visiveis, codigos)
        for _, row in df_grid.iterrows():
            _render_linha(
                st.columns(pesos),
                row["Grupo"],
                str(row["Sala"]),
                id_disc,
                nomes_ciclos_visiveis,
                codigos,
                painel,
                ciclos_visiveis_df,
            )

    if st.button("💾 Salvar alterações da conferência", type="primary", width="stretch"):
        df_editado = _coletar_editado(df_grid, id_disc, codigos, nomes_ciclos_visiveis)
        invalidas, validas = _validar_alteracoes(
            df_grid, df_editado, ciclos_visiveis_df, codigos
        )

        if invalidas:
            st.error(
                f"**{len(invalidas)}** célula(s) inválida(s). Corrija valores de 0 a 5 em A e C."
            )
            for idx, col, valor in invalidas[:8]:
                gr = df_editado.iloc[idx]["Grupo"]
                sa = df_editado.iloc[idx]["Sala"]
                st.caption(f"Gr. **{gr}** · Sala **{sa}** · **{col}** = {valor}")
            if len(invalidas) > 8:
                st.caption(f"… e mais {len(invalidas) - 8} célula(s).")
        elif validas:
            salvos = _salvar_validas(validas, id_disc, usuario)
            registrar_log(
                usuario["email"],
                usuario["nome"],
                f"Conferência entregas {disc_sel} ({salvos} lançamentos)",
            )
            st.session_state.pop("_coord_ent_ctx", None)
            # Sai do modo edição nas células salvas
            for _, grupo, sala, _id_ciclo, nome_ciclo, _ap, _ct in validas:
                cod = codigos.get(nome_ciclo)
                if cod:
                    st.session_state[_widget_key(id_disc, grupo, sala, cod, "edit")] = False
            st.success(f"{salvos} nota(s) de conferência salva(s) (substituem a média)!")
            st.rerun()
        else:
            st.info("Nenhuma alteração detectada. Marque **Alt.** nas notas que quiser mudar.")
