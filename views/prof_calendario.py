"""Programação e lançamento de aulas e dailies no app."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from calendar import Calendar
from html import escape

from domain.cadastros import carregar_disciplinas
from domain.calendario import (
    CATEGORIA_APRESENTACAO,
    CATEGORIA_ESPECIALISTA,
    CATEGORIAS_AULA,
    DIAS_SEMANA,
    agenda_disciplina,
    datas_da_disciplina,
    detalhes_por_dia,
    eventos_por_dia,
    gerar_datas,
    salvar_calendario_disciplina,
)
from domain.ciclos import hoje_normalizado
from domain.feriados import (
    FONTE_OFICIAL,
    ORIGEM_MANUAL,
    ORIGEM_SINDICATO,
    TIPO_FERIADO,
    TIPO_RECESSO,
    adicionar_institucional,
    aplicar_importacao_oficial,
    conjunto_datas_sem_aula,
    lista_institucional,
    prever_importacao_oficial,
    remover_institucional,
)
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa, normalizar_id
from utils.logs import registrar_log


def _como_date(valor) -> date | None:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, date):
        return valor
    try:
        return pd.Timestamp(valor).date()
    except Exception:
        return None


def _chave_editor(tipo: str, id_disc: str, ver: int) -> str:
    return f"cal_edit_{tipo}_{id_disc}_{ver}"


def _df_editor(tipo: str, id_disc: str) -> pd.DataFrame:
    df = datas_da_disciplina(tipo, id_disc)
    if tipo == "aulas":
        if df.empty:
            return pd.DataFrame(
                {
                    "Data": pd.Series(dtype="object"),
                    "Categoria": pd.Series(dtype=str),
                    "Detalhe": pd.Series(dtype=str),
                }
            )
        if "Detalhe" not in df.columns:
            df = df.copy()
            df["Detalhe"] = ""
        if "Categoria" not in df.columns:
            df = df.copy()
            df["Categoria"] = CATEGORIA_ESPECIALISTA
        return df[["Data", "Categoria", "Detalhe"]].copy()
    if df.empty:
        return pd.DataFrame({"Data": pd.Series(dtype="object")})
    return pd.DataFrame({"Data": df["Data"].tolist()})


def _df_como_tabela(valor) -> pd.DataFrame | None:
    if isinstance(valor, pd.DataFrame):
        return valor
    return None


def _rascunho_editor(tipo: str, id_disc: str, ver: int) -> pd.DataFrame:
    widget = _df_como_tabela(st.session_state.get(_chave_editor(tipo, id_disc, ver)))
    if widget is not None:
        return widget
    salvo = st.session_state.get(f"cal_df_{tipo}_{id_disc}")
    if isinstance(salvo, pd.DataFrame):
        return salvo
    return _df_editor(tipo, id_disc)


def _render_gerador(tipo: str, id_disc: str, ver_chave: str):
    rotulo = "aulas" if tipo == "aulas" else "dailies"
    with st.expander(f"Gerar datas de {rotulo} por período", expanded=False):
        hoje = hoje_normalizado().date()
        c1, c2 = st.columns(2)
        inicio = c1.date_input(
            "Início",
            value=hoje,
            format="DD/MM/YYYY",
            key=f"cal_ini_{tipo}_{id_disc}",
        )
        fim = c2.date_input(
            "Fim",
            value=hoje + timedelta(days=60),
            format="DD/MM/YYYY",
            key=f"cal_fim_{tipo}_{id_disc}",
        )
        categoria = CATEGORIA_ESPECIALISTA
        if tipo == "aulas":
            categoria = st.selectbox(
                "Categoria da aula:",
                CATEGORIAS_AULA,
                index=0,
                key=f"cal_cat_ger_{id_disc}",
                help="As duas categorias entram no Controle de frequência. "
                "Apresentação de projeto costuma ser na segunda-feira, salvo feriado.",
            )
        if tipo == "aulas" and categoria == CATEGORIA_APRESENTACAO:
            padrao = ["Segunda"]
        elif tipo == "aulas":
            padrao = ["Terça", "Quinta"]
        else:
            padrao = []
        nomes_dia = [nome for _, nome in DIAS_SEMANA]
        escolhidos = st.multiselect(
            "Dias da semana",
            nomes_dia,
            default=[n for n in padrao if n in nomes_dia],
            key=f"cal_dias_{tipo}_{id_disc}",
        )
        pular = True
        if tipo == "aulas":
            pular = st.checkbox(
                "Pular feriados e recessos escolares",
                value=True,
                key=f"cal_pular_{id_disc}",
            )
        mapa = {nome: num for num, nome in DIAS_SEMANA}
        if st.button(f"Incluir datas geradas em {rotulo}", key=f"cal_gerar_{tipo}_{id_disc}"):
            anos = list(range(inicio.year, fim.year + 1))
            excluir = conjunto_datas_sem_aula(anos) if pular else set()
            novas = gerar_datas(
                inicio, fim, [mapa[n] for n in escolhidos if n in mapa], excluir=excluir
            )
            if not novas:
                st.warning("Nenhuma data nesse período para os dias escolhidos (ou todas caíram em feriado/recesso).")
                return
            ver = int(st.session_state.get(ver_chave, 0))
            atual = _rascunho_editor(tipo, id_disc, ver)
            if tipo == "aulas":
                atual = _alinhar_editor_aulas(atual)
            existentes = {_como_date(v) for v in atual["Data"].tolist()}
            existentes.discard(None)
            extra = [d for d in novas if d not in existentes]
            if not extra:
                st.info("Essas datas já estavam na lista.")
                return
            bloco = pd.DataFrame({"Data": extra})
            if tipo == "aulas":
                bloco["Categoria"] = categoria
                bloco["Detalhe"] = ""
            st.session_state[f"cal_df_{tipo}_{id_disc}"] = pd.concat(
                [atual, bloco],
                ignore_index=True,
            )
            st.session_state[ver_chave] = ver + 1
            st.rerun()


def _alinhar_editor_aulas(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(
            {
                "Data": pd.Series(dtype="object"),
                "Categoria": pd.Series(dtype=str),
                "Detalhe": pd.Series(dtype=str),
            }
        )
    out = df.copy()
    if "Categoria" not in out.columns:
        out["Categoria"] = CATEGORIA_ESPECIALISTA
    if "Detalhe" not in out.columns:
        out["Detalhe"] = ""
    return out[["Data", "Categoria", "Detalhe"]]


def _render_editor_tipo(tipo: str, id_disc: str, usuario: dict):
    ver_chave = f"cal_ver_{tipo}_{id_disc}"
    if ver_chave not in st.session_state:
        st.session_state[ver_chave] = 0
    df_chave = f"cal_df_{tipo}_{id_disc}"
    if df_chave not in st.session_state:
        bruto = _df_editor(tipo, id_disc)
        st.session_state[df_chave] = (
            _alinhar_editor_aulas(bruto) if tipo == "aulas" else bruto
        )

    _render_gerador(tipo, id_disc, ver_chave)
    ver = int(st.session_state[ver_chave])
    config = {
        "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY", required=True),
    }
    if tipo == "aulas":
        config["Categoria"] = st.column_config.SelectboxColumn(
            "Categoria",
            options=CATEGORIAS_AULA,
            required=True,
        )
        config["Detalhe"] = st.column_config.TextColumn(
            "Detalhe (ciclo, tema da aula…)",
            required=False,
        )
        st.caption(
            "Edite várias linhas sem sair da tabela. A página não recarrega até você "
            "clicar em **Salvar calendário de aulas**."
        )
    rotulo_salvar = (
        "Salvar calendário de aulas" if tipo == "aulas" else "Salvar calendário de dailies"
    )
    with st.form(f"cal_form_{tipo}_{id_disc}_{ver}", border=False):
        edited = st.data_editor(
            st.session_state[df_chave],
            column_config=config,
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            key=_chave_editor(tipo, id_disc, ver),
        )
        enviou = st.form_submit_button(rotulo_salvar, type="primary")

    if not enviou:
        return
    erro = salvar_calendario_disciplina(tipo, id_disc, edited)
    if erro:
        st.error(erro)
        return
    registrar_log(
        usuario["email"],
        usuario["nome"],
        f"Atualizou calendário de {tipo} {id_disc}",
    )
    st.session_state[df_chave] = _df_editor(tipo, id_disc)
    st.session_state[ver_chave] = ver + 1
    st.success("Calendário salvo. A grade de presença usa estas datas.")
    st.rerun()


_MESES_PT = (
    "",
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)
_DIAS_CAB = ("D", "S", "T", "Q", "Q", "S", "S")
_CAL_GRID = Calendar(firstweekday=6)

_CORES = {
    CATEGORIA_ESPECIALISTA: "cal-aula",
    CATEGORIA_APRESENTACAO: "cal-apresentacao",
    "Daily": "cal-daily",
    "Encontro presencial": "cal-encontro",
}


def _eh_feriado(tipo: str) -> bool:
    return str(tipo).startswith("Feriado")


def _eh_recesso(tipo: str) -> bool:
    return str(tipo).startswith("Recesso")


def _eh_academico(tipo: str) -> bool:
    return not _eh_feriado(tipo) and not _eh_recesso(tipo)


def _classe_dia(tipos: list[str]) -> str:
    academicos = [t for t in tipos if _eh_academico(t)]
    if len(academicos) > 1:
        return "cal-varios"
    if len(academicos) == 1:
        return _CORES.get(academicos[0], "cal-aula")
    if any(_eh_feriado(t) or _eh_recesso(t) for t in tipos):
        return "cal-feriado"
    return ""


def _dica_dia(dia: date, tipos: list[str], detalhe: str = "") -> str:
    nomes = " · ".join(tipos)
    weekday = DIAS_SEMANA[dia.weekday()][1]
    base = f"{dia.strftime('%d/%m/%Y')} ({weekday}): {nomes}"
    extra = str(detalhe or "").strip()
    if extra:
        return f"{base} — {extra}"
    return base


def _html_mes(
    ano: int,
    mes: int,
    eventos: dict[date, list[str]],
    hoje: date,
    detalhes: dict[date, str] | None = None,
) -> str:
    notas = detalhes or {}
    semanas = _CAL_GRID.monthdayscalendar(ano, mes)
    cab = "".join(f"<span class='cal-dow'>{d}</span>" for d in _DIAS_CAB)
    linhas = []
    for semana in semanas:
        celulas = []
        for num in semana:
            if num == 0:
                celulas.append("<span class='cal-day cal-empty'></span>")
                continue
            dia = date(ano, mes, num)
            tipos = eventos.get(dia, [])
            classes = ["cal-day"]
            extra = _classe_dia(tipos)
            if extra:
                classes.append(extra)
            if dia == hoje:
                classes.append("cal-hoje")
            dica = escape(_dica_dia(dia, tipos, notas.get(dia, "")), quote=True) if tipos else ""
            attr = f' data-tip="{dica}" title="{dica}"' if dica else ""
            celulas.append(
                f"<span class='{' '.join(classes)}'{attr}>{num}</span>"
            )
        linhas.append(f"<div class='cal-week'>{''.join(celulas)}</div>")
    titulo = f"{_MESES_PT[mes]} {ano}"
    return (
        "<div class='cal-card'>"
        f"<div class='cal-month-title'>{escape(titulo)}</div>"
        f"<div class='cal-week cal-head'>{cab}</div>"
        f"{''.join(linhas)}"
        "</div>"
    )


def _avancar_mes(ano: int, mes: int, delta: int) -> tuple[int, int]:
    total = ano * 12 + (mes - 1) + delta
    return total // 12, total % 12 + 1


def _css_calendario() -> str:
    return """
<style>
.cal-wrap { margin: 0.4rem 0 1rem 0; }
.cal-legenda {
  display: flex; flex-wrap: wrap; gap: 0.9rem 1.4rem;
  justify-content: center; margin: 0.6rem 0 0.8rem 0;
  font-size: 0.92rem; color: #333;
}
.cal-legenda i {
  display: inline-block; width: 14px; height: 14px; border-radius: 50%;
  margin-right: 0.4rem; vertical-align: -2px;
}
.cal-dica {
  background: #fff8e6; border: 1px solid #e6d3a3; color: #5c4a1f;
  border-radius: 8px; padding: 0.55rem 0.9rem; font-size: 0.9rem;
  margin: 0 0 1rem 0;
}
.cal-meses { display: flex; flex-wrap: wrap; gap: 1.2rem; }
.cal-card {
  background: #fff; border-radius: 12px; padding: 1rem 1.1rem 1.15rem;
  box-shadow: 0 2px 10px rgba(0,0,0,0.08); flex: 1; min-width: 280px;
}
.cal-month-title {
  text-align: center; color: #1b5e20; font-weight: 700;
  font-size: 1.15rem; margin-bottom: 0.65rem;
}
.cal-week { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px 4px; justify-items: center; align-items: center; }
.cal-head { margin-bottom: 6px; }
.cal-dow {
  text-align: center; font-size: 0.78rem; color: #888; font-weight: 600;
  padding: 0.15rem 0; width: 100%;
}
.cal-day {
  position: relative; width: 50%; aspect-ratio: 1; display: flex; align-items: center;
  justify-content: center; border-radius: 50%; font-size: 0.72rem; color: #333;
  line-height: 1;
}
.cal-empty { visibility: hidden; }
.cal-aula { background: #2E7D32; color: #fff; font-weight: 600; }
.cal-apresentacao { background: #00796B; color: #fff; font-weight: 600; }
.cal-daily { background: #E67E22; color: #fff; font-weight: 600; }
.cal-encontro { background: #1565C0; color: #fff; font-weight: 600; }
.cal-feriado { background: #C62828; color: #fff; font-weight: 600; }
.cal-varios { background: #7E57C2; color: #fff; font-weight: 600; }
.cal-hoje:not(.cal-aula):not(.cal-apresentacao):not(.cal-daily):not(.cal-encontro):not(.cal-feriado):not(.cal-varios) {
  box-shadow: inset 0 0 0 1.5px #004D28;
  font-weight: 700;
}
.cal-hoje.cal-aula, .cal-hoje.cal-apresentacao, .cal-hoje.cal-daily, .cal-hoje.cal-encontro,
.cal-hoje.cal-feriado, .cal-hoje.cal-varios {
  box-shadow: 0 0 0 1px #fff, 0 0 0 2px #004D28;
}
.cal-day[data-tip]:hover::after {
  content: attr(data-tip);
  position: absolute; left: 50%; bottom: calc(100% + 8px); transform: translateX(-50%);
  background: #1b3d2f; color: #fff; font-size: 0.75rem; font-weight: 500;
  white-space: nowrap; padding: 0.35rem 0.55rem; border-radius: 6px;
  z-index: 5; box-shadow: 0 4px 12px rgba(0,0,0,0.18);
}
.cal-day[data-tip]:hover { cursor: default; filter: brightness(1.08); }
</style>
"""


def _render_calendario_visual(
    id_disc: str,
    *,
    pode_editar: bool = False,
    usuario: dict | None = None,
    visao_aluno: bool = False,
):
    eventos = eventos_por_dia(id_disc)
    detalhes = detalhes_por_dia(id_disc)
    hoje = hoje_normalizado().date()
    chave_off = f"cal_mes_off_{id_disc}"
    if chave_off not in st.session_state:
        st.session_state[chave_off] = 0

    st.caption(
        "Passe o cursor (no computador) ou toque no dia colorido para ver o que está previsto."
    )
    st.markdown(
        "<div class='cal-legenda'>"
        "<span><i style='background:#2E7D32'></i>Aula de especialista</span>"
        "<span><i style='background:#00796B'></i>Apresentação de projeto</span>"
        "<span><i style='background:#E67E22'></i>Daily (orientação)</span>"
        "<span><i style='background:#1565C0'></i>Encontro presencial</span>"
        "<span><i style='background:#C62828'></i>Feriado/recesso</span>"
        "<span><i style='background:#7E57C2'></i>Mais de um evento no dia</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    if not visao_aluno:
        st.markdown(
            "<div class='cal-dica'>💡 Dica: especialista e apresentação de projeto entram na frequência. "
            "Feriados vêm da lista nacional e de Belo Horizonte; o recesso escolar é o indicado pelo sindicato.</div>",
            unsafe_allow_html=True,
        )

    nav_e, _, nav_d = st.columns([1, 3, 1])
    if nav_e.button("← Meses anteriores", key=f"cal_prev_{id_disc}", width="stretch"):
        st.session_state[chave_off] = int(st.session_state[chave_off]) - 2
        st.rerun()
    if nav_d.button("Próximos meses →", key=f"cal_next_{id_disc}", width="stretch"):
        st.session_state[chave_off] = int(st.session_state[chave_off]) + 2
        st.rerun()

    ano, mes = _avancar_mes(hoje.year, hoje.month, int(st.session_state[chave_off]))
    ano2, mes2 = _avancar_mes(ano, mes, 1)
    html = (
        _css_calendario()
        + "<div class='cal-wrap'><div class='cal-meses'>"
        + _html_mes(ano, mes, eventos, hoje, detalhes)
        + _html_mes(ano2, mes2, eventos, hoje, detalhes)
        + "</div></div>"
    )
    if hasattr(st, "html"):
        st.html(html)
    else:
        st.markdown(html, unsafe_allow_html=True)

    academicos = {
        d: t for d, t in eventos.items() if any(_eh_academico(x) for x in t)
    }
    if not academicos:
        st.info("Ainda não há aulas, dailies nem encontro presencial lançados para esta disciplina.")

    visiveis = [
        (d, t)
        for d, t in eventos.items()
        if (d.year, d.month) in {(ano, mes), (ano2, mes2)}
    ]
    if not visiveis:
        return

    opcoes = []
    mapa = {}
    for dia, tipos in visiveis:
        rotulo = f"{dia.strftime('%d/%m/%Y')} — {' · '.join(tipos)}"
        opcoes.append(rotulo)
        mapa[rotulo] = (dia, tipos)
    padrao = 0
    for i, (dia, _t) in enumerate(visiveis):
        if dia >= hoje:
            padrao = i
            break
    escolhido = st.selectbox(
        "Detalhes do dia:",
        opcoes,
        index=padrao,
        key=f"cal_detalhe_{id_disc}_{ano}_{mes}",
    )
    dia, tipos = mapa[escolhido]
    weekday = DIAS_SEMANA[dia.weekday()][1]
    detalhe_atual = detalhes.get(dia, "")
    if detalhe_atual:
        st.success(
            f"**{dia.strftime('%d/%m/%Y')}** ({weekday}): {', '.join(tipos)}. "
            f"**{detalhe_atual}**"
        )
    else:
        st.success(f"**{dia.strftime('%d/%m/%Y')}** ({weekday}): {', '.join(tipos)}.")

    cats_no_dia = [t for t in tipos if t in CATEGORIAS_AULA]
    if pode_editar and cats_no_dia:
        st.caption(
            "Para mudar o tipo da aula ou cadastrar o detalhe (ciclo, tema), "
            "edite as células em **Lançar aulas** e clique em **Salvar calendário de aulas**."
        )

    futuras = [(d, t) for d, t in academicos.items() if d >= hoje]
    if futuras:
        d0, t0 = futuras[0]
        st.caption(
            f"Próximo compromisso acadêmico: **{' · '.join(x for x in t0 if _eh_academico(x))}** "
            f"em **{d0.strftime('%d/%m/%Y')}**."
        )


def _render_preview_importacao(usuario: dict, hoje):
    preview = st.session_state.get("cal_fer_preview")
    if not preview:
        return False
    anos = preview["anos"]
    ini, fim = anos[0], anos[-1]
    st.info(
        f"**Período da importação:** janeiro de **{ini}** a dezembro de **{fim}** "
        f"({len(anos)} ano(s)). Fonte: cadastro interno do app (sem busca na web)."
    )
    st.caption(FONTE_OFICIAL)
    st.write(
        f"Já coincidem com o oficial: **{preview['iguais']}**. "
        f"Faltando na lista (serão incluídas): **{len(preview['incluir'])}**. "
        f"Nome diferente do oficial: **{len(preview['restaurar_nome'])}**."
    )
    if preview["incluir"]:
        st.markdown("Datas oficiais que **voltam ou entram** na lista:")
        st.dataframe(
            pd.DataFrame(preview["incluir"]),
            width="stretch",
            hide_index=True,
        )
    if preview["restaurar_nome"]:
        st.markdown("Datas que já existem, mas com **outro nome**:")
        st.dataframe(
            pd.DataFrame(preview["restaurar_nome"])[["Data", "Origem", "Nome_atual", "Nome"]].rename(
                columns={"Nome_atual": "Nome na lista", "Nome": "Nome oficial"}
            ),
            width="stretch",
            hide_index=True,
        )
    if preview["sobrescreve"] or preview["recessos"] or preview["extras"]:
        partes = []
        if preview["incluir"]:
            partes.append(
                "feriados oficiais que você tinha excluído (ou que ainda não estavam na lista) serão incluídos de novo"
            )
        if preview["restaurar_nome"]:
            partes.append("nomes alterados só mudam se você marcar a opção abaixo")
        if preview["recessos"]:
            partes.append(f"{preview['recessos']} recesso(s) neste período permanecem")
        if preview["extras"]:
            partes.append(f"{preview['extras']} feriado(s) extra(s) (sindicato/manual) permanecem")
        st.warning("Este período **já tem alterações na lista**. " + "; ".join(partes) + ".")
    restaurar = False
    if preview["restaurar_nome"]:
        restaurar = st.checkbox(
            "Também restaurar os nomes oficiais (sobrescreve o nome que está na lista)",
            value=False,
            key="cal_fer_restaura_nome",
        )
    c1, c2 = st.columns(2)
    if c1.button("Confirmar importação", type="primary", key="cal_fer_ok"):
        resultado = aplicar_importacao_oficial(anos, restaurar_nomes=restaurar)
        registrar_log(
            usuario["email"],
            usuario["nome"],
            f"Importou feriados oficiais {ini}–{fim}",
        )
        st.session_state.pop("cal_fer_preview", None)
        st.success(
            f"Importação {ini}–{fim} concluída: {resultado['incluidos']} data(s) incluída(s)"
            + (f", {resultado['nomes']} nome(s) restaurado(s)." if resultado["nomes"] else ".")
        )
        st.rerun()
    if c2.button("Cancelar", key="cal_fer_cancel"):
        st.session_state.pop("cal_fer_preview", None)
        st.rerun()
    return True


def _render_institucional(usuario: dict):
    st.subheader("Feriados e recesso escolar")
    st.caption(
        "Esta lista é a que o calendário usa. **Excluir** tira o dia do mural. "
        "**Adicionar** inclui feriado extra ou recesso do sindicato."
    )
    with st.expander("De onde vêm os feriados oficiais?", expanded=False):
        st.write(FONTE_OFICIAL)

    hoje = hoje_normalizado().date()
    if _render_preview_importacao(usuario, hoje):
        return

    st.markdown("**Importar feriados oficiais**")
    p1, p2, p3 = st.columns([1, 1, 1.4])
    ano_ini = p1.number_input("Ano inicial", min_value=2020, max_value=2040, value=hoje.year, step=1, key="cal_fer_ano_ini")
    ano_fim = p2.number_input("Ano final", min_value=2020, max_value=2040, value=hoje.year + 1, step=1, key="cal_fer_ano_fim")
    if p3.button("Importar/atualizar feriados oficiais", key="cal_sync_fer", width="stretch"):
        ini, fim = int(min(ano_ini, ano_fim)), int(max(ano_ini, ano_fim))
        st.session_state["cal_fer_preview"] = prever_importacao_oficial(list(range(ini, fim + 1)))
        st.rerun()

    lista = lista_institucional()
    anos = sorted(
        {
            pd.Timestamp(d).year
            for d in pd.to_datetime(lista["Data"], format="%d/%m/%Y", errors="coerce")
            if pd.notna(d)
        }
        | {hoje.year}
    )
    ano_sel = st.selectbox("Mostrar ano:", anos, index=anos.index(hoje.year) if hoje.year in anos else 0, key="cal_fer_ano")
    if lista.empty:
        filtro = lista
    else:
        parsed = pd.to_datetime(lista["Data"], format="%d/%m/%Y", errors="coerce")
        filtro = lista[parsed.dt.year == ano_sel].copy()

    with st.form("cal_fer_add"):
        st.markdown("**Adicionar data**")
        c1, c2, c3 = st.columns(3)
        nova_data = c1.date_input("Data", value=hoje, format="DD/MM/YYYY")
        novo_tipo = c2.selectbox("Tipo", [TIPO_FERIADO, TIPO_RECESSO])
        nova_origem = c3.selectbox(
            "Origem",
            [ORIGEM_SINDICATO, ORIGEM_MANUAL, "Nacional", "BH"],
        )
        novo_nome = st.text_input("Nome", placeholder="Ex.: Recesso de fim de ano — Sinepe")
        if st.form_submit_button("Adicionar à lista", type="primary"):
            erro = adicionar_institucional(nova_data, novo_tipo, novo_nome, nova_origem)
            if erro:
                st.error(erro)
            else:
                registrar_log(usuario["email"], usuario["nome"], f"Adicionou {novo_tipo} {novo_nome}")
                st.success("Data incluída na lista.")
                st.rerun()

    if filtro.empty:
        st.info(f"Nenhuma data na lista para {ano_sel}.")
        return

    st.markdown("**Lista**")
    cab1, cab2, cab3, cab4, cab5 = st.columns([1.2, 1.1, 2.4, 1.1, 0.8])
    cab1.caption("Data")
    cab2.caption("Tipo")
    cab3.caption("Nome")
    cab4.caption("Origem")
    cab5.caption("")
    for i, row in filtro.iterrows():
        d1, d2, d3, d4, d5 = st.columns([1.2, 1.1, 2.4, 1.1, 0.8])
        d1.write(str(row["Data"]))
        d2.write(str(row["Tipo"]))
        d3.write(str(row["Nome"]))
        d4.write(str(row["Origem"]))
        chave = f"cal_fer_del_{ano_sel}_{i}_{row['Data']}_{row['Nome']}"
        if d5.button("Excluir", key=chave, width="stretch"):
            erro = remover_institucional(row["Data"], row["Tipo"], row["Nome"], row["Origem"])
            if erro:
                st.error(erro)
            else:
                registrar_log(
                    usuario["email"],
                    usuario["nome"],
                    f"Excluiu {row['Tipo']} {row['Nome']} {row['Data']}",
                )
                st.rerun()


def _anos_da_agenda(agenda: pd.DataFrame) -> pd.Series:
    return agenda["Data"].map(lambda v: (_como_date(v) or date.min).year)


def _banner_anotacoes_daily_hoje(usuario: dict | None, id_disc: str):
    if not usuario or usuario.get("perfil") != "Professor":
        return
    from domain.anotacoes_daily import datas_dailies_disciplina
    from navigation import ROTA_ANOTACOES_DAILY, ir_para
    from views.prof_anotacoes_daily import pode_anotar

    if not pode_anotar(usuario):
        return
    hoje = hoje_normalizado().date()
    if hoje not in datas_dailies_disciplina(id_disc):
        return
    with st.container(border=True):
        col_txt, col_btn = st.columns([3.2, 1.4], vertical_alignment="center")
        with col_txt:
            st.markdown(
                f"**Hoje tem daily** ({hoje.strftime('%d/%m/%Y')}). "
                "Registre as anotações de orientação dos grupos."
            )
        with col_btn:
            if st.button(
                "Anotações da daily",
                type="primary",
                width="stretch",
                key=f"cal_atalho_daily_{id_disc}",
            ):
                ir_para(ROTA_ANOTACOES_DAILY)


def _render_agenda(
    id_disc: str,
    *,
    pode_editar: bool = False,
    usuario: dict | None = None,
    visao_aluno: bool = False,
):
    _render_calendario_visual(
        id_disc,
        pode_editar=pode_editar,
        usuario=usuario,
        visao_aluno=visao_aluno,
    )
    agenda = agenda_disciplina(id_disc)
    if agenda.empty or visao_aluno:
        return
    ano_atual = hoje_normalizado().date().year
    with st.expander("Ver lista de datas"):
        st.caption(f"Por padrão aparece só **{ano_atual}**.")
        c1, c2 = st.columns(2)
        ver_anteriores = c1.checkbox(
            "Mostrar anos anteriores",
            value=False,
            key=f"cal_lista_ant_{id_disc}",
        )
        ver_proximos = c2.checkbox(
            "Mostrar próximos anos",
            value=False,
            key=f"cal_lista_prox_{id_disc}",
        )
        anos = _anos_da_agenda(agenda)
        visivel = anos == ano_atual
        if ver_anteriores:
            visivel = visivel | (anos < ano_atual)
        if ver_proximos:
            visivel = visivel | (anos > ano_atual)
        recorte = agenda.loc[visivel].drop(columns=["Disciplina"], errors="ignore")
        if recorte.empty:
            st.info("Nenhuma data neste recorte. Marque anos anteriores ou próximos para ampliar a lista.")
        else:
            st.dataframe(
                recorte,
                width="stretch",
                hide_index=True,
                column_config={
                    "Data": st.column_config.TextColumn("Data"),
                    "Dia": st.column_config.TextColumn("Dia"),
                    "Tipo": st.column_config.TextColumn("Tipo"),
                    "Detalhe": st.column_config.TextColumn("Detalhe"),
                },
            )


def render(
    usuario: dict,
    *,
    pode_editar: bool | None = None,
    id_disciplina: str | None = None,
    mostrar_cabecalho: bool = True,
    visao_aluno: bool = False,
):
    if pode_editar is None:
        pode_editar = bool(st.session_state.get("modo_coordenador"))

    if mostrar_cabecalho:
        st.header("Calendário")
        if pode_editar:
            st.caption(
                "Lance as datas que entram na frequência e na nota de dailies. "
                "Em cada dia de aula dá para registrar um detalhe, como Ciclo 1 ou o tema da aula."
            )
        else:
            st.caption(
                "Aulas (frequência), dailies e encontro presencial da disciplina."
            )

    df_disc = carregar_disciplinas()
    if df_disc is None or df_disc.empty:
        st.warning("Cadastre as disciplinas antes de lançar o calendário.")
        return

    if id_disciplina:
        id_disc = normalizar_id(id_disciplina)
        match = df_disc[df_disc["ID_Disciplina"].astype(str).str.strip() == str(id_disc).strip()]
        nome = str(match.iloc[0]["Nome_Disciplina"]) if not match.empty else id_disc
        if not visao_aluno:
            st.markdown(f"**Disciplina:** {id_disc} — {nome}")
    else:
        lista = df_disc["Nome_Disciplina"].astype(str).tolist()
        nome = st.selectbox(
            "Disciplina:",
            lista,
            index=indice_disciplina_ativa(df_disc, lista),
            key="cal_disc_sel",
        )
        id_disc = normalizar_id(id_disciplina_por_nome(df_disc, nome))

    _banner_anotacoes_daily_hoje(usuario, id_disc)
    _render_agenda(id_disc, pode_editar=pode_editar, usuario=usuario, visao_aluno=visao_aluno)

    if pode_editar:
        st.markdown("---")
        aba_aulas, aba_dailies, aba_fer = st.tabs(
            ["Lançar aulas", "Lançar dailies", "Feriados e recesso"]
        )
        with aba_aulas:
            st.subheader("Aulas")
            st.caption(
                "Especialista e apresentação de projeto entram na mesma grade de frequência. "
                "Segundas sem feriado costumam ser apresentação de projeto."
            )
            _render_editor_tipo("aulas", id_disc, usuario)
        with aba_dailies:
            st.subheader("Dailies")
            st.caption("Cada data vira uma coluna no Controle de dailies.")
            _render_editor_tipo("dailies", id_disc, usuario)
        with aba_fer:
            _render_institucional(usuario)
