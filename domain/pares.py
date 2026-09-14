"""Avaliações de pares — leitura/gravação com dual-write no teste.

No ambiente teste: Supabase tipado é preferencial; Sheets espelha (fallback
se o Supabase estiver indisponível). Em produção permanece só Sheets.
A chave de negócio ``ID_Ciclo|Email_Avaliador|Email_Avaliado`` torna o envio
idempotente e reduz perda por corrida no ``append_rows``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd

from data.sheets import ler_aba, limpar_cache_planilhas, planilha

COLUNAS = (
    "Data_Hora",
    "ID_Ciclo",
    "Disciplina",
    "Ciclo",
    "Email_Avaliado",
    "Nome_Avaliado",
    "Grupo",
    "Nota",
    "Email_Avaliador",
    "Nome_Avaliador",
    "Comentário",
    "Duplicação",
    "Moderação",
)

StatusEnvio = Literal["ok", "ja_enviou", "erro"]


def _agora() -> str:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")


def _texto(valor) -> str:
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    return str(valor).strip()


def _normalizar(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        out = pd.DataFrame(columns=list(COLUNAS) + ["chave_origem"])
        return out

    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    # Aliases legados / import
    renomear = {}
    if "Comentario" in out.columns and "Comentário" not in out.columns:
        renomear["Comentario"] = "Comentário"
    if "Moderacao" in out.columns and "Moderação" not in out.columns:
        renomear["Moderacao"] = "Moderação"
    if "Duplicacao" in out.columns and "Duplicação" not in out.columns:
        renomear["Duplicacao"] = "Duplicação"
    if "Carimbo de data/hora" in out.columns and "Data_Hora" not in out.columns:
        renomear["Carimbo de data/hora"] = "Data_Hora"
    if renomear:
        out = out.rename(columns=renomear)

    for col in COLUNAS:
        if col not in out.columns:
            out[col] = ""

    out["ID_Ciclo"] = out["ID_Ciclo"].map(_texto)
    out["Email_Avaliado"] = out["Email_Avaliado"].astype(str).str.strip().str.lower()
    out["Email_Avaliador"] = out["Email_Avaliador"].astype(str).str.strip().str.lower()
    out["Comentário"] = (
        out["Comentário"].astype(str).replace({"nan": "", "None": ""}).str.strip()
    )
    out["Moderação"] = (
        out["Moderação"].astype(str).replace({"nan": "", "None": ""}).str.strip()
    )
    out["Nota"] = pd.to_numeric(out["Nota"], errors="coerce")

    if "chave_origem" not in out.columns:
        out["chave_origem"] = out.apply(_chave_negocio_row, axis=1)
    else:
        faltando = out["chave_origem"].isna() | (
            out["chave_origem"].astype(str).str.strip() == ""
        )
        if faltando.any():
            out.loc[faltando, "chave_origem"] = out.loc[faltando].apply(
                _chave_negocio_row, axis=1
            )

    return out


def _chave_negocio_row(row: pd.Series) -> str:
    return "|".join(
        (
            _texto(row.get("ID_Ciclo")),
            _texto(row.get("Email_Avaliador")).lower(),
            _texto(row.get("Email_Avaliado")).lower(),
        )
    )


def _carregar_sheets() -> pd.DataFrame:
    try:
        df = ler_aba("Avaliacoes")
    except Exception:
        df = pd.DataFrame()
    return _normalizar(df)


def carregar_avaliacoes_pares() -> pd.DataFrame:
    """Supabase tipado no teste; Sheets em produção ou como fallback."""
    try:
        from auth.supabase_auth import ambiente_app
        from data.supabase_operacional import listar_avaliacoes_pares

        if ambiente_app() == "teste":
            return _normalizar(listar_avaliacoes_pares())
    except Exception:
        pass
    return _carregar_sheets()


def aluno_ja_enviou_pares(
    id_ciclo: str,
    email_avaliador: str,
    df: pd.DataFrame | None = None,
) -> bool:
    base = carregar_avaliacoes_pares() if df is None else df
    if base is None or base.empty:
        return False
    id_c = _texto(id_ciclo)
    email = _texto(email_avaliador).lower()
    mask = (base["ID_Ciclo"] == id_c) & (base["Email_Avaliador"] == email)
    return not base[mask].empty


def _linha_dict(
    *,
    agora: str,
    id_ciclo: str,
    disciplina: str,
    ciclo: str,
    email_avaliado: str,
    nome_avaliado: str,
    grupo: str,
    nota,
    email_avaliador: str,
    nome_avaliador: str,
    comentario: str,
) -> dict[str, str]:
    return {
        "Data_Hora": agora,
        "ID_Ciclo": _texto(id_ciclo),
        "Disciplina": _texto(disciplina),
        "Ciclo": _texto(ciclo),
        "Email_Avaliado": _texto(email_avaliado).lower(),
        "Nome_Avaliado": _texto(nome_avaliado),
        "Grupo": _texto(grupo),
        "Nota": _texto(nota),
        "Email_Avaliador": _texto(email_avaliador).lower(),
        "Nome_Avaliador": _texto(nome_avaliador),
        "Comentário": _texto(comentario),
        "Duplicação": "",
        "Moderação": "",
    }


def _espelhar_linhas_sheets(
    linhas: list[dict[str, str]],
    *,
    atualizar_existentes: bool = False,
) -> None:
    """Append (ou atualiza nota/comentário) pela chave de negócio."""
    if not linhas:
        return
    df = _carregar_sheets()
    existentes_idx: dict[str, int] = {}
    if not df.empty:
        for i, row in df.reset_index(drop=True).iterrows():
            existentes_idx[_chave_negocio_row(row)] = int(i)

    aba = planilha.worksheet("Avaliacoes")
    novas = []
    for dados in linhas:
        chave = _chave_negocio_row(pd.Series(dados))
        if chave in existentes_idx:
            if not atualizar_existentes:
                continue
            pos = existentes_idx[chave] + 2  # cabeçalho
            aba.update_cell(pos, 8, dados["Nota"])
            aba.update_cell(pos, 11, dados["Comentário"])
            continue
        novas.append(
            [
                dados["Data_Hora"],
                dados["ID_Ciclo"],
                dados["Disciplina"],
                dados["Ciclo"],
                dados["Email_Avaliado"],
                dados["Nome_Avaliado"],
                dados["Grupo"],
                dados["Nota"],
                dados["Email_Avaliador"],
                dados["Nome_Avaliador"],
                dados["Comentário"],
                dados.get("Duplicação", ""),
                dados.get("Moderação", ""),
            ]
        )
        existentes_idx[chave] = len(existentes_idx)

    if novas:
        aba.append_rows(novas)
    limpar_cache_planilhas()


def _salvar_linhas_sheets_legado(
    linhas: list[dict[str, str]],
    *,
    atualizar_existentes: bool = False,
) -> None:
    """Produção / fallback: gravação idempotente pela chave de negócio."""
    _espelhar_linhas_sheets(linhas, atualizar_existentes=atualizar_existentes)


def enviar_avaliacoes_pares(
    *,
    id_ciclo: str,
    disciplina: str,
    ciclo: str,
    grupo: str,
    email_avaliador: str,
    nome_avaliador: str,
    respostas: dict,
    permitir_reenvio: bool = False,
) -> tuple[StatusEnvio, str]:
    """
    Persiste o envio completo de um aluno (uma linha por colega).

    ``respostas``: ``{email_avaliado: {"nome", "nota", "coment"}}``.
    """
    email_av = _texto(email_avaliador).lower()
    id_c = _texto(id_ciclo)
    if not id_c or not email_av:
        return "erro", "Dados do avaliador/ciclo inválidos."
    if not respostas:
        return "erro", "Nenhum colega para avaliar."

    limpar_cache_planilhas()
    if aluno_ja_enviou_pares(id_c, email_av) and not permitir_reenvio:
        return "ja_enviou", ""

    agora = _agora()
    linhas = [
        _linha_dict(
            agora=agora,
            id_ciclo=id_c,
            disciplina=disciplina,
            ciclo=ciclo,
            email_avaliado=email_aval,
            nome_avaliado=d["nome"],
            grupo=grupo,
            nota=d["nota"],
            email_avaliador=email_av,
            nome_avaliador=nome_avaliador,
            comentario=d.get("coment") or "",
        )
        for email_aval, d in respostas.items()
    ]

    try:
        from auth.supabase_auth import ambiente_app
        from data.supabase_operacional import (
            OperacionalIndisponivel,
            salvar_avaliacao_pares,
        )

        if ambiente_app() == "teste":
            try:
                for dados in linhas:
                    salvar_avaliacao_pares(dados)
                try:
                    _espelhar_linhas_sheets(
                        linhas, atualizar_existentes=permitir_reenvio
                    )
                except Exception:
                    # Já seguro no Supabase — não cair para append duplicado.
                    pass
                return "ok", ""
            except OperacionalIndisponivel:
                pass
    except Exception:
        pass

    try:
        _salvar_linhas_sheets_legado(
            linhas, atualizar_existentes=permitir_reenvio
        )
        return "ok", ""
    except Exception as exc:
        return "erro", f"Falha ao salvar avaliações: {exc}"


def atualizar_moderacao(
    *,
    status: str,
    chave_origem: str = "",
    linha_planilha: int | None = None,
    id_ciclo: str = "",
    email_avaliador: str = "",
    email_avaliado: str = "",
) -> str | None:
    """Atualiza Moderação no Supabase (teste) e espelha no Sheets. Retorna erro ou None."""
    status_limpo = _texto(status)
    if status_limpo not in {"Aprovado", "Ignorar"}:
        return "Status de moderação inválido."

    chave = _texto(chave_origem)
    if not chave and id_ciclo and email_avaliador and email_avaliado:
        chave = "|".join(
            (
                _texto(id_ciclo),
                _texto(email_avaliador).lower(),
                _texto(email_avaliado).lower(),
            )
        )

    try:
        from auth.supabase_auth import ambiente_app
        from data.supabase_operacional import (
            OperacionalIndisponivel,
            atualizar_moderacao_pares,
        )

        if ambiente_app() == "teste" and chave:
            try:
                atualizar_moderacao_pares(chave, status_limpo)
                try:
                    _espelhar_moderacao_sheets(
                        status=status_limpo,
                        chave=chave,
                        linha_planilha=linha_planilha,
                        id_ciclo=id_ciclo,
                        email_avaliador=email_avaliador,
                        email_avaliado=email_avaliado,
                    )
                except Exception:
                    pass
                return None
            except OperacionalIndisponivel:
                pass
    except Exception:
        pass

    return _atualizar_moderacao_sheets(
        status=status_limpo,
        chave=chave,
        linha_planilha=linha_planilha,
        id_ciclo=id_ciclo,
        email_avaliador=email_avaliador,
        email_avaliado=email_avaliado,
    )


def _espelhar_moderacao_sheets(
    *,
    status: str,
    chave: str = "",
    linha_planilha: int | None = None,
    id_ciclo: str = "",
    email_avaliador: str = "",
    email_avaliado: str = "",
) -> None:
    erro = _atualizar_moderacao_sheets(
        status=status,
        chave=chave,
        linha_planilha=linha_planilha,
        id_ciclo=id_ciclo,
        email_avaliador=email_avaliador,
        email_avaliado=email_avaliado,
    )
    if erro:
        raise RuntimeError(erro)


def _atualizar_moderacao_sheets(
    *,
    status: str,
    chave: str = "",
    linha_planilha: int | None = None,
    id_ciclo: str = "",
    email_avaliador: str = "",
    email_avaliado: str = "",
) -> str | None:
    aba = planilha.worksheet("Avaliacoes")
    if linha_planilha is not None and int(linha_planilha) >= 2:
        aba.update_cell(int(linha_planilha), 13, status)
        limpar_cache_planilhas()
        return None

    df = _carregar_sheets()
    if df.empty:
        return "Não foi possível localizar a linha na planilha."

    mask = pd.Series([False] * len(df), index=df.index)
    if chave:
        mask = df["chave_origem"].astype(str) == chave
    if not mask.any() and id_ciclo and email_avaliador and email_avaliado:
        mask = (
            (df["ID_Ciclo"] == _texto(id_ciclo))
            & (df["Email_Avaliador"] == _texto(email_avaliador).lower())
            & (df["Email_Avaliado"] == _texto(email_avaliado).lower())
        )
    if not mask.any():
        return "Linha de avaliação não encontrada na planilha."

    pos = next(i for i, ativo in enumerate(mask.tolist()) if ativo)
    aba.update_cell(pos + 2, 13, status)
    limpar_cache_planilhas()
    return None
