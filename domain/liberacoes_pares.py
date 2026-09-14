"""Liberação excepcional individual de avaliação de pares."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from config import ABAS_AVALIACAO
from data.sheets import garantir_aba_avaliacao, ler_aba, limpar_cache_planilhas, salvar_aba
from utils.disciplina import normalizar_id

ABA = "Liberacoes_Pares_Excepcionais"
COLUNAS = ABAS_AVALIACAO[ABA]
TZ = ZoneInfo("America/Sao_Paulo")
MODOS = ("primeiro_envio", "reenvio")


def _agora() -> datetime:
    return datetime.now(TZ)


def _texto(valor) -> str:
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    return str(valor).strip()


def _parse_ts(valor) -> datetime | None:
    txt = _texto(valor)
    if not txt:
        return None
    try:
        ts = pd.Timestamp(txt)
        if ts.tzinfo is None:
            return ts.tz_localize(TZ).to_pydatetime()
        return ts.tz_convert(TZ).to_pydatetime()
    except Exception:
        return None


def _fmt_ts(valor: datetime | None) -> str:
    if valor is None:
        return ""
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=TZ)
    return valor.astimezone(TZ).isoformat()


def fim_do_dia(dia) -> datetime:
    if isinstance(dia, datetime):
        base = dia.astimezone(TZ).date() if dia.tzinfo else dia.date()
    else:
        base = pd.Timestamp(dia).date()
    return datetime.combine(base, time(23, 59, 59), tzinfo=TZ)


def _normalizar(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUNAS)
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for col in COLUNAS:
        if col not in out.columns:
            out[col] = ""
    out["Email_Aluno"] = out["Email_Aluno"].astype(str).str.strip().str.lower()
    out["Email_Liberador"] = out["Email_Liberador"].astype(str).str.strip().str.lower()
    out["ID_Disciplina"] = out["ID_Disciplina"].map(normalizar_id)
    out["ID_Ciclo"] = out["ID_Ciclo"].map(normalizar_id)
    out["Modo"] = out["Modo"].astype(str).str.strip().replace({"": "primeiro_envio"})
    return out[COLUNAS]


def _carregar_sheets() -> pd.DataFrame:
    garantir_aba_avaliacao(ABA)
    try:
        return _normalizar(ler_aba(ABA))
    except Exception:
        return pd.DataFrame(columns=COLUNAS)


def _salvar_sheets(df: pd.DataFrame) -> None:
    garantir_aba_avaliacao(ABA)
    salvar_aba(ABA, _normalizar(df), COLUNAS)
    limpar_cache_planilhas()


def carregar_liberacoes() -> pd.DataFrame:
    try:
        from auth.supabase_auth import ambiente_app
        from data.supabase_operacional import listar_liberacoes_pares

        if ambiente_app() == "teste":
            return _normalizar(pd.DataFrame(listar_liberacoes_pares()))
    except Exception:
        pass
    return _carregar_sheets()


def _linha_vigente(row: pd.Series, agora: datetime | None = None) -> bool:
    agora = agora or _agora()
    if _texto(row.get("Revogado_Em")):
        return False
    if _texto(row.get("Usado_Em")):
        return False
    limite = _parse_ts(row.get("Valido_Ate"))
    if limite is None or limite < agora:
        return False
    return True


def liberacao_vigente(
    email_aluno: str,
    id_disciplina: str,
    *,
    df: pd.DataFrame | None = None,
) -> dict | None:
    email = _texto(email_aluno).lower()
    id_disc = normalizar_id(id_disciplina)
    if not email or not id_disc:
        return None
    base = carregar_liberacoes() if df is None else df
    if base.empty:
        return None
    candidatos = base[
        (base["Email_Aluno"] == email) & (base["ID_Disciplina"] == id_disc)
    ]
    vigentes = [row for _, row in candidatos.iterrows() if _linha_vigente(row)]
    if not vigentes:
        return None
    vigentes.sort(key=lambda r: _parse_ts(r.get("Criado_Em")) or datetime.min.replace(tzinfo=TZ), reverse=True)
    return vigentes[0].to_dict()


def listar_liberacoes_ativas(id_disciplina: str | None = None) -> pd.DataFrame:
    base = carregar_liberacoes()
    if base.empty:
        return base
    mask = base.apply(_linha_vigente, axis=1)
    out = base[mask].copy()
    if id_disciplina:
        out = out[out["ID_Disciplina"] == normalizar_id(id_disciplina)]
    return out.sort_values("Criado_Em", ascending=False)


def ciclo_pares_para_aluno(
    email_aluno: str,
    ciclos: pd.DataFrame,
    id_disciplina: str,
) -> tuple[pd.Series | None, dict | None]:
    """Ciclo de pares que o aluno deve ver agora.

    1) Liberação excepcional vigente (reenvio ou ainda sem envio).
    2) Entre ciclos abertos na janela (data + kill-switch), o de **maior Ordem
       ainda pendente** para o aluno — assim, após enviar o ciclo superior num
       overlap, o inferior continua disponível se a janela ainda estiver aberta.
    3) Se todos os abertos já foram enviados, devolve o de maior Ordem (mensagem
       de confirmação).
    """
    from domain.ciclos import filtrar_ciclos_ativos, ordenar_ciclos
    from domain.encontro_presencial import ciclos_visiveis_avaliacao
    from domain.pares import aluno_ja_enviou_pares

    email = _texto(email_aluno).lower()
    id_disc = normalizar_id(id_disciplina)

    lib = liberacao_vigente(email, id_disc)
    if lib:
        id_ciclo = normalizar_id(lib.get("ID_Ciclo"))
        bloco = ciclos[ciclos["ID_Ciclo"].map(normalizar_id) == id_ciclo]
        if not bloco.empty:
            row = bloco.iloc[0]
            votou = aluno_ja_enviou_pares(id_ciclo, email)
            reenvio = _texto(lib.get("Modo")) == "reenvio"
            if (not votou) or reenvio:
                return row, lib

    if ciclos is None or ciclos.empty:
        return None, None
    visiveis = ciclos_visiveis_avaliacao(ciclos, id_disc)
    ativos = filtrar_ciclos_ativos(visiveis)
    if ativos.empty:
        return None, None
    ordenados = ordenar_ciclos(ativos)
    for i in range(len(ordenados) - 1, -1, -1):
        row = ordenados.iloc[i]
        id_c = normalizar_id(row.get("ID_Ciclo"))
        if not aluno_ja_enviou_pares(id_c, email):
            return row, None
    return ordenados.iloc[-1], None


def criar_liberacao(
    *,
    email_aluno: str,
    nome_aluno: str,
    id_disciplina: str,
    id_ciclo: str,
    nome_ciclo: str,
    modo: str,
    valido_ate: datetime,
    motivo: str,
    liberador: dict,
) -> str | None:
    """Cria liberação. Revoga outras vigentes do mesmo aluno/disciplina. Retorna erro ou None."""
    email = _texto(email_aluno).lower()
    id_disc = normalizar_id(id_disciplina)
    id_c = normalizar_id(id_ciclo)
    modo_limpo = _texto(modo) or "primeiro_envio"
    if modo_limpo not in MODOS:
        return "Modo inválido."
    if not email or not id_disc or not id_c:
        return "Informe aluno, disciplina e ciclo."
    if not _texto(motivo):
        return "Informe o motivo da liberação."
    if valido_ate.tzinfo is None:
        valido_ate = valido_ate.replace(tzinfo=TZ)
    if valido_ate < _agora():
        return "A validade precisa ser no futuro."

    agora = _agora()
    nova = {
        "ID": str(uuid4()),
        "Email_Aluno": email,
        "Nome_Aluno": _texto(nome_aluno) or email,
        "ID_Disciplina": id_disc,
        "ID_Ciclo": id_c,
        "Nome_Ciclo": _texto(nome_ciclo),
        "Modo": modo_limpo,
        "Valido_Ate": _fmt_ts(valido_ate),
        "Motivo": _texto(motivo),
        "Email_Liberador": _texto(liberador.get("email")).lower(),
        "Nome_Liberador": _texto(liberador.get("nome")),
        "Criado_Em": _fmt_ts(agora),
        "Usado_Em": "",
        "Revogado_Em": "",
    }

    df = _carregar_sheets()
    # Revoga vigentes anteriores do mesmo aluno/disciplina no espelho Sheets.
    if not df.empty:
        for idx, row in df.iterrows():
            if (
                row["Email_Aluno"] == email
                and row["ID_Disciplina"] == id_disc
                and _linha_vigente(row, agora)
            ):
                df.at[idx, "Revogado_Em"] = _fmt_ts(agora)

    df = pd.concat([df, pd.DataFrame([nova])], ignore_index=True)

    try:
        from auth.supabase_auth import ambiente_app
        from data.supabase_operacional import (
            OperacionalIndisponivel,
            atualizar_campos_liberacao_pares,
            listar_liberacoes_pares,
            upsert_liberacao_pares,
        )

        if ambiente_app() == "teste":
            try:
                atuais = listar_liberacoes_pares()
                for row in atuais:
                    serie = pd.Series(row)
                    if (
                        serie["Email_Aluno"] == email
                        and serie["ID_Disciplina"] == id_disc
                        and _linha_vigente(serie, agora)
                    ):
                        atualizar_campos_liberacao_pares(
                            serie["ID"], {"revogado_em": _fmt_ts(agora)}
                        )
                upsert_liberacao_pares(nova)
                try:
                    _salvar_sheets(df)
                except Exception:
                    pass
                return None
            except OperacionalIndisponivel:
                pass
    except Exception:
        pass

    _salvar_sheets(df)
    return None


def revogar_liberacao(id_lib: str, *, ator: dict | None = None) -> str | None:
    id_limpo = _texto(id_lib)
    if not id_limpo:
        return "ID inválido."
    agora = _fmt_ts(_agora())
    df = _carregar_sheets()
    if not df.empty and id_limpo in set(df["ID"].astype(str)):
        df.loc[df["ID"].astype(str) == id_limpo, "Revogado_Em"] = agora

    try:
        from auth.supabase_auth import ambiente_app
        from data.supabase_operacional import (
            OperacionalIndisponivel,
            atualizar_campos_liberacao_pares,
        )

        if ambiente_app() == "teste":
            try:
                atualizar_campos_liberacao_pares(id_limpo, {"revogado_em": agora})
                try:
                    if not df.empty:
                        _salvar_sheets(df)
                except Exception:
                    pass
                return None
            except OperacionalIndisponivel:
                pass
    except Exception:
        pass

    if df.empty or id_limpo not in set(df["ID"].astype(str)):
        return "Liberação não encontrada."
    _salvar_sheets(df)
    return None


def marcar_liberacao_usada(id_lib: str) -> None:
    id_limpo = _texto(id_lib)
    if not id_limpo:
        return
    agora = _fmt_ts(_agora())
    df = _carregar_sheets()
    if not df.empty and id_limpo in set(df["ID"].astype(str)):
        df.loc[df["ID"].astype(str) == id_limpo, "Usado_Em"] = agora

    try:
        from auth.supabase_auth import ambiente_app
        from data.supabase_operacional import (
            OperacionalIndisponivel,
            atualizar_campos_liberacao_pares,
        )

        if ambiente_app() == "teste":
            try:
                atualizar_campos_liberacao_pares(id_limpo, {"usado_em": agora})
                try:
                    if not df.empty:
                        _salvar_sheets(df)
                except Exception:
                    pass
                return
            except OperacionalIndisponivel:
                pass
    except Exception:
        pass

    if not df.empty:
        _salvar_sheets(df)


def validade_padrao_48h() -> datetime:
    return _agora() + timedelta(hours=48)
