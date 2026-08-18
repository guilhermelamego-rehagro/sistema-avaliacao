"""Conexão com Google Sheets, leitura em cache e bootstrap de abas."""

from __future__ import annotations

import time

import streamlit as st
import gspread
import pandas as pd
from gspread.exceptions import APIError
from oauth2client.service_account import ServiceAccountCredentials

from config import ABAS_AVALIACAO, ABAS_FREQUENCIA

__all__ = [
    "planilha",
    "obter_planilha",
    "obter_planilha_frequencia",
    "preparar_ambiente_planilhas",
    "garantir_aba_avaliacao",
    "garantir_aba_frequencia",
    "ler_aba",
    "ler_aba_frequencia",
    "salvar_aba",
    "salvar_aba_frequencia",
    "limpar_cache_planilhas",
    "texto_planilha",
]

ESCOPO = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

_CACHE_TTL = 900
_COLUNAS_TEXTO = ("Sala", "Grupo", "Turma", "Turma_Ingresso", "ID_Disciplina", "ID_Ciclo")


def _valor_celula_texto(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if pd.isna(valor):
        return ""
    return str(valor).strip()


def texto_planilha(valor) -> str:
    return _valor_celula_texto(valor)


def _normalizar_colunas_texto(df: pd.DataFrame) -> pd.DataFrame:
    """Evita colunas object com int/str mistos (erro Arrow no st.dataframe)."""
    if df.empty:
        return df
    out = df.copy()
    for col in _COLUNAS_TEXTO:
        if col in out.columns:
            out[col] = out[col].map(_valor_celula_texto)
    return out


def _requisitar_com_retry(func, *args, max_tentativas: int = 4, **kwargs):
    """Repete leituras da API em caso de limite temporário (HTTP 429)."""
    for tentativa in range(max_tentativas):
        try:
            return func(*args, **kwargs)
        except APIError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429 and tentativa < max_tentativas - 1:
                time.sleep(2**tentativa + 1)
                continue
            raise


def _kwargs_get_all_records(colunas_config: list[str] | None) -> dict:
    kwargs = {
        "value_render_option": "UNFORMATTED_VALUE",
        "default_blank": "",
    }
    if colunas_config:
        kwargs["expected_headers"] = colunas_config
        kwargs["numericise_ignore"] = colunas_config
    return kwargs


def _kwargs_get_all_records_frequencia(colunas_config: list[str] | None) -> dict:
    """Frequência usa datas formatadas (dd/mm/aaaa); não há notas decimais com vírgula."""
    kwargs = {
        "value_render_option": "FORMATTED_VALUE",
        "default_blank": "",
    }
    if colunas_config:
        kwargs["expected_headers"] = colunas_config
    return kwargs


def _ambiente_planilha() -> str:
    """Lê ambiente na raiz ou aninhado por engano em planilhas/gcp."""
    valor = st.secrets.get("ambiente")
    if valor is None:
        valor = st.secrets.get("planilhas", {}).get("ambiente")
    if valor is None:
        valor = st.secrets.get("gcp_service_account", {}).get("ambiente")
    ambiente = str(valor or "teste").strip().lower()
    if ambiente in {"producao", "produção", "production", "prod"}:
        return "producao"
    return "teste"


@st.cache_resource(ttl=600)
def conectar_planilha():
    credenciais = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["gcp_service_account"], ESCOPO
    )
    cliente = gspread.authorize(credenciais)
    chave = "id_producao" if _ambiente_planilha() == "producao" else "id_teste"
    return cliente.open_by_key(st.secrets["planilhas"][chave])


@st.cache_resource(ttl=600)
def conectar_planilha_frequencia():
    credenciais = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["gcp_service_account"], ESCOPO
    )
    cliente = gspread.authorize(credenciais)
    return cliente.open_by_key(st.secrets["planilhas"]["id_frequencia"])


@st.cache_resource(ttl=600)
def _worksheet_avaliacao(nome_aba: str):
    return _requisitar_com_retry(conectar_planilha().worksheet, nome_aba)


@st.cache_resource(ttl=600)
def _worksheet_frequencia(nome_aba: str):
    return _requisitar_com_retry(conectar_planilha_frequencia().worksheet, nome_aba)


def _garantir_aba(planilha_obj, nome_aba: str, colunas: list[str]):
    try:
        planilha_obj.worksheet(nome_aba)
    except gspread.WorksheetNotFound:
        ws = planilha_obj.add_worksheet(title=nome_aba, rows=200, cols=len(colunas))
        ws.append_row(colunas)


def _sincronizar_abas_novas():
    """Cria apenas abas novas do config (Disciplinas, Ciclos etc. são legadas)."""
    p_aval = conectar_planilha()
    p_freq = conectar_planilha_frequencia()
    for nome, colunas in ABAS_AVALIACAO.items():
        _garantir_aba(p_aval, nome, colunas)
    for nome, colunas in ABAS_FREQUENCIA.items():
        _garantir_aba(p_freq, nome, colunas)


def preparar_ambiente_planilhas():
    """Uma vez por sessão: garante abas novas. Não bloqueia leitura de abas legadas."""
    if st.session_state.get("_planilhas_prontas"):
        return
    _sincronizar_abas_novas()
    st.session_state["_planilhas_prontas"] = True


def garantir_aba_avaliacao(nome_aba: str):
    if nome_aba not in ABAS_AVALIACAO:
        return
    _garantir_aba(conectar_planilha(), nome_aba, ABAS_AVALIACAO[nome_aba])


def garantir_aba_frequencia(nome_aba: str):
    if nome_aba not in ABAS_FREQUENCIA:
        return
    _garantir_aba(conectar_planilha_frequencia(), nome_aba, ABAS_FREQUENCIA[nome_aba])


def obter_planilha():
    return conectar_planilha()


def obter_planilha_frequencia():
    return conectar_planilha_frequencia()


class _PlanilhaProxy:
    """Compatibilidade com código que usa `planilha.worksheet(...)`."""

    def worksheet(self, nome: str):
        if nome in ABAS_AVALIACAO:
            garantir_aba_avaliacao(nome)
        return _worksheet_avaliacao(nome)

    def __getattr__(self, nome: str):
        return getattr(conectar_planilha(), nome)


planilha = _PlanilhaProxy()


def _ler_registros(ws, colunas_config: list[str] | None, *, frequencia: bool = False) -> list[dict]:
    kwargs_fn = _kwargs_get_all_records_frequencia if frequencia else _kwargs_get_all_records
    kwargs = kwargs_fn(colunas_config)
    try:
        return _requisitar_com_retry(ws.get_all_records, **kwargs)
    except TypeError:
        kwargs.pop("value_render_option", None)
        return _requisitar_com_retry(ws.get_all_records, **kwargs)


@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def ler_aba(nome_aba: str) -> pd.DataFrame:
    if nome_aba in ABAS_AVALIACAO:
        garantir_aba_avaliacao(nome_aba)
    ws = _worksheet_avaliacao(nome_aba)
    registros = _ler_registros(ws, ABAS_AVALIACAO.get(nome_aba))
    return _normalizar_colunas_texto(pd.DataFrame(registros).copy())


@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def ler_aba_frequencia(nome_aba: str) -> pd.DataFrame:
    if nome_aba in ABAS_FREQUENCIA:
        garantir_aba_frequencia(nome_aba)
    ws = _worksheet_frequencia(nome_aba)
    registros = _ler_registros(ws, ABAS_FREQUENCIA.get(nome_aba), frequencia=True)
    df = pd.DataFrame(registros).copy()
    df.columns = df.columns.astype(str).str.strip()
    return _normalizar_colunas_texto(df)


def salvar_aba(nome_aba: str, df: pd.DataFrame, colunas: list[str] | None = None):
    """Substitui o conteúdo da aba (cabeçalho + linhas), no mesmo ID da planilha."""
    ws = planilha.worksheet(nome_aba)
    out = df.copy()
    if colunas:
        for col in colunas:
            if col not in out.columns:
                out[col] = ""
        out = out[colunas]
    else:
        colunas = [str(c) for c in out.columns]

    linhas = []
    if not out.empty:
        limpo = out.fillna("").astype(str).replace({"nan": "", "None": "", "<NA>": ""})
        linhas = limpo.values.tolist()

    _requisitar_com_retry(ws.clear)
    _requisitar_com_retry(ws.update, range_name="A1", values=[colunas] + linhas)
    limpar_cache_planilhas()


def salvar_aba_frequencia(nome_aba: str, df: pd.DataFrame, colunas: list[str] | None = None):
    """Substitui o conteúdo de uma aba da planilha de frequência."""
    if nome_aba in ABAS_FREQUENCIA:
        garantir_aba_frequencia(nome_aba)
    ws = _worksheet_frequencia(nome_aba)
    out = df.copy()
    if colunas:
        for col in colunas:
            if col not in out.columns:
                out[col] = ""
        extras = [c for c in out.columns if c not in colunas]
        out = out[colunas + extras]
        colunas = list(out.columns)
    else:
        colunas = [str(c) for c in out.columns]

    linhas = []
    if not out.empty:
        limpo = out.fillna("").astype(str).replace({"nan": "", "None": "", "<NA>": ""})
        linhas = limpo.values.tolist()

    _requisitar_com_retry(ws.clear)
    _requisitar_com_retry(ws.update, range_name="A1", values=[colunas] + linhas)
    limpar_cache_planilhas()


def limpar_cache_planilhas():
    ler_aba.clear()
    ler_aba_frequencia.clear()
    try:
        from domain.ciclos import _obter_disciplina_ativa_cached
        from domain.presenca import carregar_base_presenca

        _obter_disciplina_ativa_cached.clear()
        carregar_base_presenca.clear()
    except Exception:
        pass
