"""Indicação de colega para o próximo grupo — ranking do ciclo e janela de escolha."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from config import ABAS_AVALIACAO
from data.sheets import garantir_aba_avaliacao, ler_aba, limpar_cache_planilhas, planilha, salvar_aba
from domain.notas import calcular_boletim_aluno
from domain.presenca import carregar_base_presenca, compilar_grid_dailies, compilar_grid_frequencia
from utils.disciplina import normalizar_id

ABA_JANELAS = "Janelas_Indicacao_Grupo"
ABA_RANKING = "Ranking_Indicacao_Grupo"
ABA_INDICACOES = "Indicacoes_Grupo"

STATUS_RASCUNHO = "rascunho"
STATUS_ABERTA = "aberta"
STATUS_FECHADA = "fechada"

_TZ = ZoneInfo("America/Sao_Paulo")


def _agora() -> str:
    return datetime.now(_TZ).strftime("%d/%m/%Y %H:%M:%S")


def _hoje() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(_TZ).date())


def _garantir_abas():
    for nome in (ABA_JANELAS, ABA_RANKING, ABA_INDICACOES):
        garantir_aba_avaliacao(nome)


def _email_limpo(valor) -> str:
    return str(valor or "").strip().lower()


def _parse_data(valor) -> pd.Timestamp | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = str(valor).strip()
    if not texto or texto.lower() in {"nan", "none", "nat"}:
        return None
    ts = pd.to_datetime(texto, dayfirst=True, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts).normalize()


_SIM = {"sim", "s", "true", "1"}


def _sim(serie: pd.Series) -> pd.Series:
    return serie.astype(str).str.strip().str.lower().isin(_SIM)


def emails_excluidos_lista(texto: str) -> set[str]:
    partes = str(texto or "").replace(";", ",").replace("\n", ",").split(",")
    return {_email_limpo(p) for p in partes if _email_limpo(p)}


def excluidos_da_janela(id_janela: str) -> set[str]:
    janelas = carregar_janelas()
    j = janelas[janelas["ID_Janela"].astype(str).str.strip() == str(id_janela).strip()]
    return emails_excluidos_lista(j.iloc[0].get("Emails_Excluidos", "")) if not j.empty else set()


def _confirmadas(ind: pd.DataFrame) -> pd.DataFrame:
    if ind is None or ind.empty:
        return pd.DataFrame(columns=ABAS_AVALIACAO[ABA_INDICACOES])
    return ind[ind["Status"].astype(str).str.strip().str.lower() == "confirmado"]


def _serializar_excluidos(emails: list[str] | set[str]) -> str:
    limpos = sorted({_email_limpo(e) for e in emails if _email_limpo(e)})
    return "; ".join(limpos)


def carregar_janelas(id_disciplina: str = "") -> pd.DataFrame:
    _garantir_abas()
    try:
        df = ler_aba(ABA_JANELAS)
    except Exception:
        return pd.DataFrame(columns=ABAS_AVALIACAO[ABA_JANELAS])
    if df.empty:
        return pd.DataFrame(columns=ABAS_AVALIACAO[ABA_JANELAS])
    out = df.copy()
    for col in ABAS_AVALIACAO[ABA_JANELAS]:
        if col not in out.columns:
            out[col] = ""
    if id_disciplina:
        id_d = normalizar_id(id_disciplina)
        out = out[out["ID_Disciplina"].map(normalizar_id) == id_d]
    return out.reset_index(drop=True)


def carregar_ranking(id_janela: str = "") -> pd.DataFrame:
    _garantir_abas()
    try:
        df = ler_aba(ABA_RANKING)
    except Exception:
        return pd.DataFrame(columns=ABAS_AVALIACAO[ABA_RANKING])
    if df.empty:
        return pd.DataFrame(columns=ABAS_AVALIACAO[ABA_RANKING])
    out = df.copy()
    for col in ABAS_AVALIACAO[ABA_RANKING]:
        if col not in out.columns:
            out[col] = ""
    if id_janela:
        out = out[out["ID_Janela"].astype(str).str.strip() == str(id_janela).strip()]
    return out.reset_index(drop=True)


def carregar_indicacoes(id_janela: str = "") -> pd.DataFrame:
    _garantir_abas()
    try:
        df = ler_aba(ABA_INDICACOES)
    except Exception:
        return pd.DataFrame(columns=ABAS_AVALIACAO[ABA_INDICACOES])
    if df.empty:
        return pd.DataFrame(columns=ABAS_AVALIACAO[ABA_INDICACOES])
    out = df.copy()
    for col in ABAS_AVALIACAO[ABA_INDICACOES]:
        if col not in out.columns:
            out[col] = ""
    if id_janela:
        out = out[out["ID_Janela"].astype(str).str.strip() == str(id_janela).strip()]
    return out.reset_index(drop=True)


def _alunos_ativos_disciplina(id_disciplina: str) -> pd.DataFrame:
    """Alunos com vínculo na Entrância e grupo preenchido (desistentes ficam de fora)."""
    id_d = normalizar_id(id_disciplina)
    df = ler_aba("Entrancia_Turma")
    if df.empty:
        return pd.DataFrame()
    alunos = df[df["ID_Disciplina"].map(normalizar_id) == id_d].copy()
    if alunos.empty:
        return alunos
    alunos["Email_Limpo"] = alunos["Email_Pessoal"].map(_email_limpo)
    alunos["Grupo"] = alunos["Grupo"].astype(str).str.strip()
    alunos = alunos[
        alunos["Email_Limpo"].ne("")
        & alunos["Grupo"].ne("")
        & ~alunos["Grupo"].str.lower().isin({"nan", "none", "—", "–", "-"})
    ]
    return alunos.drop_duplicates(subset=["Email_Limpo"], keep="first").reset_index(drop=True)


def alunos_para_exclusao(id_disciplina: str) -> pd.DataFrame:
    """Alunos que entram no ranking e na lista de escolha: E-mail, Nome, Turma, Sala, Grupo."""
    from domain.notas import _anexar_turma_base_alunos

    alunos = _alunos_ativos_disciplina(id_disciplina)
    if alunos.empty:
        return pd.DataFrame(columns=["E-mail", "Nome", "Turma", "Sala", "Grupo"])
    alunos = _anexar_turma_base_alunos(alunos)

    def _txt(col: str) -> pd.Series:
        if col not in alunos.columns:
            return pd.Series([""] * len(alunos), index=alunos.index)
        return alunos[col].astype(str).str.strip().replace({"nan": "", "None": ""})

    return pd.DataFrame(
        {
            "E-mail": alunos["Email_Limpo"],
            "Nome": _txt("Nome_Completo"),
            "Turma": _txt("Turma_Ingresso"),
            "Sala": _txt("Sala"),
            "Grupo": _txt("Grupo"),
        }
    ).reset_index(drop=True)


def _mapa_pct(resumo: pd.DataFrame) -> dict[str, float]:
    if resumo is None or resumo.empty:
        return {}
    out: dict[str, float] = {}
    for _, row in resumo.iterrows():
        em = _email_limpo(row.get("Email_Cru", ""))
        if not em:
            continue
        try:
            out[em] = float(row.get("% Realizado", 0) or 0)
        except (TypeError, ValueError):
            out[em] = 0.0
    return out


def _nota_componente_ciclo(email: str, id_disciplina: str, grupo: str, sala: str, id_ciclo: str) -> float | None:
    from domain.componentes import carregar_componentes_disciplina
    from domain.encontro_presencial import resolver_id_ciclo_componente

    boletim = calcular_boletim_aluno(email, id_disciplina, grupo, sala)
    if boletim.empty:
        return None
    comps = carregar_componentes_disciplina(id_disciplina)
    id_c = str(id_ciclo).strip()
    nomes_alvo: set[str] = set()
    for _, comp in comps.iterrows():
        tipo = str(comp.get("Tipo", "")).strip()
        if tipo not in ("Ciclo", "Entrega_Final"):
            continue
        id_cfg = str(comp.get("ID_Ciclo", "")).strip()
        id_res, _ = resolver_id_ciclo_componente(tipo, id_cfg, id_disciplina)
        if str(id_res).strip() == id_c:
            nomes_alvo.add(str(comp.get("Nome", "")).strip())
    if not nomes_alvo:
        return None
    for _, row in boletim.iterrows():
        if str(row.get("Componente", "")).strip() not in nomes_alvo:
            continue
        nota = row.get("Nota (0-100)")
        if nota is None or (isinstance(nota, float) and pd.isna(nota)):
            return None
        try:
            return float(nota)
        except (TypeError, ValueError):
            return None
    return None


def calcular_ranking_ciclo(id_disciplina: str, id_ciclo: str, excluidos: set[str] | None = None) -> pd.DataFrame:
    """
    Ranking por grupo: nota do ciclo (maior), depois % dailies, depois % aulas.
    Empates após os três critérios ficam com Vencedor=Não até desempate da coordenação.
    Excluídos ficam no snapshot (para poder voltar), mas sem posição e sem concorrer.
    """
    id_d = normalizar_id(id_disciplina)
    id_c = str(id_ciclo).strip()
    alunos = _alunos_ativos_disciplina(id_d)
    if alunos.empty:
        return pd.DataFrame(columns=ABAS_AVALIACAO[ABA_RANKING])

    dfs_cache = carregar_base_presenca()
    resumo_aulas, _ = compilar_grid_frequencia(id_d, alunos, dfs_cache=dfs_cache)
    resumo_dailies, _ = compilar_grid_dailies(id_d, alunos, dfs_cache=dfs_cache)
    pct_aulas = _mapa_pct(resumo_aulas)
    pct_dailies = _mapa_pct(resumo_dailies)

    gerado = _agora()
    linhas: list[dict] = []
    for _, aluno in alunos.iterrows():
        email = str(aluno["Email_Pessoal"]).strip()
        email_l = _email_limpo(email)
        grupo = str(aluno.get("Grupo", "")).strip()
        sala = str(aluno.get("Sala", "")).strip()
        nome = str(aluno.get("Nome_Completo", "")).strip()
        nota = _nota_componente_ciclo(email_l, id_d, grupo, sala, id_c)
        linhas.append(
            {
                "ID_Janela": "",
                "ID_Disciplina": id_d,
                "ID_Ciclo": id_c,
                "Email_Aluno": email_l,
                "Nome_Aluno": nome,
                "Sala": sala,
                "Grupo": grupo,
                "Nota_Ciclo": "" if nota is None else round(float(nota), 3),
                "Pct_Dailies": round(pct_dailies.get(email_l, 0.0), 3),
                "Pct_Aulas": round(pct_aulas.get(email_l, 0.0), 3),
                "Posicao_Grupo": "",
                "Vencedor": "Não",
                "Desempate_Coord": "Não",
                "Gerado_Em": gerado,
            }
        )

    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    return definir_vencedores(df, excluidos or set()).reset_index(drop=True)


def definir_vencedores(
    rank: pd.DataFrame, excluidos: set[str], ja_indicaram: set[str] | None = None
) -> pd.DataFrame:
    """
    Posição e melhor de cada grupo sem os excluídos. Único 1º com nota vence sozinho; em empate,
    mantém a escolha da coordenação enquanto os escolhidos seguirem empatados no topo.
    Quem já confirmou indicação nunca perde a marca de melhor do grupo.
    """
    out = rank.copy()
    out["Posicao_Grupo"] = out["Posicao_Grupo"].astype(object)
    ja_indicaram = ja_indicaram or set()
    emails = out["Email_Aluno"].map(_email_limpo)
    exc = emails.isin(excluidos)
    out.loc[exc, ["Posicao_Grupo", "Vencedor", "Desempate_Coord"]] = ["", "Não", "Não"]
    ativos = out[~exc]
    if ativos.empty:
        return out
    out.loc[~exc, "Posicao_Grupo"] = recalcular_posicoes_exibicao(ativos)["Posicao_Grupo"]

    chaves = ["Sala", "Grupo"] if "Sala" in out.columns else ["Grupo"]
    for _, bloco in ativos.groupby(chaves, sort=False, dropna=False):
        em_bloco = bloco["Email_Aluno"].map(_email_limpo)
        topo = candidatos_desempate_grupo(bloco)
        topo_em = set(topo["Email_Aluno"].map(_email_limpo))
        coord = set(em_bloco[_sim(bloco["Vencedor"]) & _sim(bloco["Desempate_Coord"])]) & topo_em
        if coord:
            vencem = coord
        elif len(topo) == 1 and pd.notna(pd.to_numeric(topo.iloc[0].get("Nota_Ciclo"), errors="coerce")):
            vencem = topo_em
        else:
            vencem = set()
        vencem |= set(em_bloco[_sim(bloco["Vencedor"])]) & ja_indicaram
        out.loc[bloco.index, "Vencedor"] = em_bloco.isin(vencem).map({True: "Sim", False: "Não"})
        out.loc[bloco.index, "Desempate_Coord"] = em_bloco.isin(coord).map({True: "Sim", False: "Não"})
    return out


def candidatos_desempate_grupo(bloco: pd.DataFrame) -> pd.DataFrame:
    """
    Alunos empatados no topo do grupo em nota, % dailies e % aulas
    (únicos elegíveis ao desempate da coordenação).
    """
    if bloco is None or bloco.empty:
        return pd.DataFrame()
    b = bloco.copy()
    b["_nota"] = pd.to_numeric(b.get("Nota_Ciclo"), errors="coerce").fillna(-1)
    b["_dailies"] = pd.to_numeric(b.get("Pct_Dailies"), errors="coerce").fillna(-1)
    b["_aulas"] = pd.to_numeric(b.get("Pct_Aulas"), errors="coerce").fillna(-1)
    top_nota = float(b["_nota"].max())
    b = b[b["_nota"] == top_nota]
    top_d = float(b["_dailies"].max())
    b = b[b["_dailies"] == top_d]
    top_a = float(b["_aulas"].max())
    b = b[b["_aulas"] == top_a]
    return b.drop(columns=["_nota", "_dailies", "_aulas"], errors="ignore").reset_index(drop=True)


def recalcular_posicoes_exibicao(rank: pd.DataFrame) -> pd.DataFrame:
    """Recalcula Posicao_Grupo na exibição (empates repetem o número)."""
    if rank is None or rank.empty:
        return rank
    out = rank.copy()
    out["_nota"] = pd.to_numeric(out.get("Nota_Ciclo"), errors="coerce").fillna(-1)
    out["_dailies"] = pd.to_numeric(out.get("Pct_Dailies"), errors="coerce").fillna(-1)
    out["_aulas"] = pd.to_numeric(out.get("Pct_Aulas"), errors="coerce").fillna(-1)
    posicoes = pd.Series(0, index=out.index, dtype=int)
    chaves = ["Sala", "Grupo"] if "Sala" in out.columns else ["Grupo"]
    for _, idx in out.groupby(chaves, sort=False, dropna=False).groups.items():
        bloco = out.loc[list(idx)].sort_values(
            by=["_nota", "_dailies", "_aulas", "Nome_Aluno"],
            ascending=[False, False, False, True],
            kind="mergesort",
        )
        prev_key = None
        pos_atual = 0
        for ordem, i in enumerate(bloco.index):
            key = (
                float(bloco.at[i, "_nota"]),
                float(bloco.at[i, "_dailies"]),
                float(bloco.at[i, "_aulas"]),
            )
            if prev_key is None or key != prev_key:
                pos_atual = ordem + 1
                prev_key = key
            posicoes.at[i] = pos_atual
    out["Posicao_Grupo"] = posicoes
    return out.drop(columns=["_nota", "_dailies", "_aulas"])


def criar_janela_rascunho(
    id_disciplina: str,
    id_ciclo: str,
    nome_ciclo: str,
    email_responsavel: str,
    nome_responsavel: str,
    ranking: pd.DataFrame,
    excluidos: set[str] | None = None,
) -> str:
    """Cria janela em rascunho e grava o snapshot do ranking (excluídos herdados da rodada anterior)."""
    _garantir_abas()
    id_janela = str(uuid4())
    id_d = normalizar_id(id_disciplina)
    agora = _agora()

    rank = ranking.copy()
    rank["ID_Janela"] = id_janela
    rank["ID_Disciplina"] = id_d
    rank["ID_Ciclo"] = str(id_ciclo).strip()
    rank["Gerado_Em"] = agora
    for col in ABAS_AVALIACAO[ABA_RANKING]:
        if col not in rank.columns:
            rank[col] = ""
    rank = rank[ABAS_AVALIACAO[ABA_RANKING]]

    df_rank = carregar_ranking()
    df_rank = pd.concat([df_rank, rank], ignore_index=True)
    salvar_aba(ABA_RANKING, df_rank, ABAS_AVALIACAO[ABA_RANKING])

    ws = planilha.worksheet(ABA_JANELAS)
    ws.append_row(
        [
            id_janela,
            id_d,
            "ciclo",
            str(id_ciclo).strip(),
            str(nome_ciclo or "").strip(),
            "",
            "",
            STATUS_RASCUNHO,
            _serializar_excluidos(excluidos or set()),
            _email_limpo(email_responsavel),
            str(nome_responsavel or "").strip(),
            agora,
        ]
    )
    limpar_cache_planilhas()
    return id_janela


def atualizar_excluidos(id_janela: str, emails: list[str] | set[str]) -> str | None:
    """
    Grava os excluídos da rodada e refaz posições e melhores de cada grupo sem eles.
    Recusa excluir quem já indicou ou já foi indicado nesta rodada (nada é desfeito em silêncio).
    """
    _garantir_abas()
    df = carregar_janelas()
    mask = df["ID_Janela"].astype(str).str.strip() == str(id_janela).strip() if not df.empty else None
    if mask is None or not mask.any():
        return "Rodada não encontrada."
    novos = {_email_limpo(e) for e in emails if _email_limpo(e)}
    adicionados = novos - emails_excluidos_lista(df.loc[mask].iloc[0].get("Emails_Excluidos", ""))

    conf = _confirmadas(carregar_indicacoes(id_janela))
    ja_indicaram = set(conf["Email_Vencedor"].map(_email_limpo))
    problemas = []
    for _, r in conf.iterrows():
        if _email_limpo(r["Email_Vencedor"]) in adicionados:
            problemas.append(f"{str(r.get('Nome_Vencedor', '')).strip() or r['Email_Vencedor']} (já indicou um colega)")
        if _email_limpo(r["Email_Escolhido"]) in adicionados:
            problemas.append(f"{str(r.get('Nome_Escolhido', '')).strip() or r['Email_Escolhido']} (já foi indicado)")
    if problemas:
        return (
            "Nada foi salvo. Não dá para excluir quem já participou da indicação desta rodada: "
            + "; ".join(problemas)
            + ". Desmarque esses alunos e salve de novo."
        )

    df.loc[mask, "Emails_Excluidos"] = _serializar_excluidos(novos)
    salvar_aba(ABA_JANELAS, df, ABAS_AVALIACAO[ABA_JANELAS])

    full = carregar_ranking()
    mask_r = full["ID_Janela"].astype(str).str.strip() == str(id_janela).strip()
    if mask_r.any():
        refeito = definir_vencedores(full[mask_r], novos, ja_indicaram)
        full = full.astype(object)
        full.loc[mask_r, refeito.columns] = refeito
        salvar_aba(ABA_RANKING, full, ABAS_AVALIACAO[ABA_RANKING])
    return None


def marcar_desempate_coord(id_janela: str, emails_vencedores: str | list[str]) -> str | None:
    """
    Em empate, a coordenação elege um ou mais melhores do grupo entre os empatados; cada um indica
    um colega. Desmarca os demais do grupo, exceto quem já confirmou indicação (esse não sai).
    """
    _garantir_abas()
    if isinstance(emails_vencedores, str):
        emails_vencedores = [emails_vencedores]
    escolhidos = {_email_limpo(e) for e in emails_vencedores if _email_limpo(e)}
    if not escolhidos:
        return "Marque ao menos um aluno."
    df = carregar_ranking(id_janela)
    if df.empty:
        return "Ranking da janela não encontrado."
    df = df[~df["Email_Aluno"].map(_email_limpo).isin(excluidos_da_janela(id_janela))]
    alvo = df[df["Email_Aluno"].map(_email_limpo).isin(escolhidos)]
    if alvo["Email_Aluno"].map(_email_limpo).nunique() != len(escolhidos):
        return "Aluno não está no ranking desta janela."
    grupos = alvo[["Sala", "Grupo"]].astype(str).apply(lambda c: c.str.strip()).drop_duplicates()
    if len(grupos) != 1:
        return "Marque alunos do mesmo grupo."
    sala, grupo = grupos.iloc[0]["Sala"], grupos.iloc[0]["Grupo"]
    bloco = df[
        (df["Grupo"].astype(str).str.strip() == grupo)
        & (df["Sala"].astype(str).str.strip() == sala)
    ]
    elegiveis = set(candidatos_desempate_grupo(bloco)["Email_Aluno"].map(_email_limpo))
    if not escolhidos <= elegiveis:
        return "Só é possível desempatar entre alunos empatados em nota, % dailies e % aulas."

    atuais = bloco[bloco["Vencedor"].astype(str).str.strip().str.lower().isin({"sim", "s", "true", "1"})]
    ind = carregar_indicacoes(id_janela)
    confirmados = (
        set(ind.loc[ind["Status"].astype(str).str.strip().str.lower() == "confirmado", "Email_Vencedor"].map(_email_limpo))
        if not ind.empty
        else set()
    )
    presos = atuais[atuais["Email_Aluno"].map(_email_limpo).isin(confirmados - escolhidos)]
    if not presos.empty:
        nomes = ", ".join(presos["Nome_Aluno"].astype(str).str.strip())
        return f"{nomes} já indicou um colega e não pode ser desmarcado."

    full = carregar_ranking().astype(object)
    mask_janela = full["ID_Janela"].astype(str).str.strip() == str(id_janela).strip()
    mask_grupo = (full["Grupo"].astype(str).str.strip() == grupo) & (
        full["Sala"].astype(str).str.strip() == sala
    )
    mask = mask_janela & mask_grupo
    full.loc[mask, "Vencedor"] = "Não"
    full.loc[mask, "Desempate_Coord"] = "Não"
    mask_alunos = mask & full["Email_Aluno"].map(_email_limpo).isin(escolhidos)
    full.loc[mask_alunos, "Vencedor"] = "Sim"
    full.loc[mask_alunos, "Desempate_Coord"] = "Sim"
    full.loc[mask_alunos, "Posicao_Grupo"] = 1
    salvar_aba(ABA_RANKING, full, ABAS_AVALIACAO[ABA_RANKING])
    return None


def abrir_janela(id_janela: str, data_inicio: str, data_fim: str) -> str | None:
    di = _parse_data(data_inicio)
    dfim = _parse_data(data_fim)
    if di is None or dfim is None:
        return "Informe data de início e fim válidas."
    if dfim < di:
        return "A data fim deve ser igual ou posterior à data início."

    rank = carregar_ranking(id_janela)
    if rank.empty:
        return "Gere o ranking antes de abrir a janela."
    ven = rank[_sim(rank["Vencedor"]) & ~rank["Email_Aluno"].map(_email_limpo).isin(excluidos_da_janela(id_janela))]
    if ven.empty:
        return "Não há vencedores definidos. Resolva empates antes de abrir."

    df = carregar_janelas()
    mask = df["ID_Janela"].astype(str).str.strip() == str(id_janela).strip()
    if not mask.any():
        return "Janela não encontrada."
    df.loc[mask, "Data_Inicio"] = di.strftime("%d/%m/%Y")
    df.loc[mask, "Data_Fim"] = dfim.strftime("%d/%m/%Y")
    df.loc[mask, "Status"] = STATUS_ABERTA
    salvar_aba(ABA_JANELAS, df, ABAS_AVALIACAO[ABA_JANELAS])
    return None


def fechar_janela(id_janela: str) -> str | None:
    df = carregar_janelas()
    mask = df["ID_Janela"].astype(str).str.strip() == str(id_janela).strip()
    if not mask.any():
        return "Janela não encontrada."
    df.loc[mask, "Status"] = STATUS_FECHADA
    salvar_aba(ABA_JANELAS, df, ABAS_AVALIACAO[ABA_JANELAS])
    return None


def _janela_vigente(row: pd.Series) -> bool:
    status = str(row.get("Status", "")).strip().lower()
    if status != STATUS_ABERTA:
        return False
    di = _parse_data(row.get("Data_Inicio"))
    dfim = _parse_data(row.get("Data_Fim"))
    if di is None or dfim is None:
        return False
    hoje = _hoje()
    return di <= hoje <= dfim


def janelas_abertas_para_vencedor(email: str) -> pd.DataFrame:
    """Janelas abertas e vigentes em que o e-mail é vencedor e ainda não indicou."""
    email_l = _email_limpo(email)
    janelas = carregar_janelas()
    if janelas.empty:
        return pd.DataFrame()

    vigentes = janelas[janelas.apply(_janela_vigente, axis=1)].copy()
    if vigentes.empty:
        return vigentes

    rank = carregar_ranking()
    ind = carregar_indicacoes()
    ja_indicou = set()
    if not ind.empty:
        feitos = ind[
            (ind["Email_Vencedor"].map(_email_limpo) == email_l)
            & (ind["Status"].astype(str).str.strip().str.lower() == "confirmado")
        ]
        ja_indicou = set(feitos["ID_Janela"].astype(str).str.strip())

    linhas = []
    for _, j in vigentes.iterrows():
        id_j = str(j.get("ID_Janela", "")).strip()
        if id_j in ja_indicou or email_l in emails_excluidos_lista(j.get("Emails_Excluidos", "")):
            continue
        r = rank[
            (rank["ID_Janela"].astype(str).str.strip() == id_j)
            & (rank["Email_Aluno"].map(_email_limpo) == email_l)
            & (rank["Vencedor"].astype(str).str.strip().str.lower().isin({"sim", "s", "true", "1"}))
        ]
        if r.empty:
            continue
        linhas.append(j)
    if not linhas:
        return pd.DataFrame(columns=vigentes.columns)
    return pd.DataFrame(linhas).reset_index(drop=True)


def pool_escolha(id_janela: str, email_vencedor: str) -> pd.DataFrame:
    """
    Candidatos da oferta (Entrância ativa): exclui o próprio, lista manual,
    e quem já foi escolhido nesta janela. Cadeia A→B→C permitida (vencedor
    pode ser escolhido por outro e ainda assim indicar).
    """
    janelas = carregar_janelas()
    j = janelas[janelas["ID_Janela"].astype(str).str.strip() == str(id_janela).strip()]
    if j.empty:
        return pd.DataFrame()
    row = j.iloc[0]
    id_d = normalizar_id(row.get("ID_Disciplina", ""))
    excluidos = emails_excluidos_lista(row.get("Emails_Excluidos", ""))
    excluidos.add(_email_limpo(email_vencedor))

    ind = carregar_indicacoes(id_janela)
    if not ind.empty:
        escolhidos = ind[ind["Status"].astype(str).str.strip().str.lower() == "confirmado"]
        for em in escolhidos["Email_Escolhido"].map(_email_limpo):
            if em:
                excluidos.add(em)

    alunos = _alunos_ativos_disciplina(id_d)
    if alunos.empty:
        return alunos
    pool = alunos[~alunos["Email_Limpo"].isin(excluidos)].copy()
    pool = pool.sort_values(by=["Nome_Completo", "Email_Pessoal"], kind="mergesort")
    return pool.reset_index(drop=True)


def confirmar_indicacao(
    id_janela: str,
    email_vencedor: str,
    nome_vencedor: str,
    email_escolhido: str,
    nome_escolhido: str,
) -> str | None:
    """Persiste indicação com checagem de corrida (escolhido já indicado)."""
    _garantir_abas()
    email_v = _email_limpo(email_vencedor)
    email_e = _email_limpo(email_escolhido)
    if not email_e:
        return "Selecione um colega."
    if email_e == email_v:
        return "Você não pode indicar a si mesmo."

    vigentes = janelas_abertas_para_vencedor(email_v)
    if vigentes.empty or str(id_janela).strip() not in set(vigentes["ID_Janela"].astype(str).str.strip()):
        return "Esta janela não está disponível para indicação."

    pool = pool_escolha(id_janela, email_v)
    if pool.empty or email_e not in set(pool["Email_Limpo"]):
        return "Este colega não está mais disponível. Atualize a página e escolha outro."

    # Releitura imediatamente antes de gravar
    ind = carregar_indicacoes(id_janela)
    if not ind.empty:
        if not ind[
            (ind["Email_Vencedor"].map(_email_limpo) == email_v)
            & (ind["Status"].astype(str).str.strip().str.lower() == "confirmado")
        ].empty:
            return "Você já confirmou sua indicação nesta janela."
        if not ind[
            (ind["Email_Escolhido"].map(_email_limpo) == email_e)
            & (ind["Status"].astype(str).str.strip().str.lower() == "confirmado")
        ].empty:
            return "Este colega acabou de ser indicado por outra pessoa. Escolha outro."

    ws = planilha.worksheet(ABA_INDICACOES)
    ws.append_row(
        [
            str(uuid4()),
            str(id_janela).strip(),
            email_v,
            str(nome_vencedor or "").strip(),
            email_e,
            str(nome_escolhido or "").strip(),
            "confirmado",
            _agora(),
        ]
    )
    limpar_cache_planilhas()
    return None


def indicacao_do_vencedor(id_janela: str, email_vencedor: str) -> dict | None:
    ind = carregar_indicacoes(id_janela)
    if ind.empty:
        return None
    email_l = _email_limpo(email_vencedor)
    feitos = ind[
        (ind["Email_Vencedor"].map(_email_limpo) == email_l)
        & (ind["Status"].astype(str).str.strip().str.lower() == "confirmado")
    ]
    if feitos.empty:
        return None
    row = feitos.iloc[-1]
    return {
        "email_escolhido": _email_limpo(row.get("Email_Escolhido")),
        "nome_escolhido": str(row.get("Nome_Escolhido", "")).strip(),
        "confirmado_em": str(row.get("Confirmado_Em", "")).strip(),
    }
