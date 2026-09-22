"""Motor de cálculo de notas da disciplina."""

from __future__ import annotations

import re

import pandas as pd

from config import PESO_ORIENTADOR, PESO_PARES
from data.sheets import ler_aba
from domain.avaliacoes import formatar_nota_entrega, obter_media_avaliacao_grupo_aluno, obter_nota_orientador
from domain.ciclos import ciclo_inativo
from domain.componentes import carregar_componentes_disciplina
from domain.encontro_presencial import resolver_id_ciclo_componente
from domain.pares import carregar_avaliacoes_pares
from domain.presenca import calcular_matriz_dailies
from utils.disciplina import normalizar_id


def calcular_nota_pares(media_0_5: float, realizou_avaliacao: bool) -> float:
    multiplicador = 2 if realizou_avaliacao else 1
    return float(media_0_5) * multiplicador


def calcular_nota_ciclo(
    nota_orientador_0_10: float,
    nota_pares_0_10: float,
    nota_grupo_0_10: float,
) -> float:
    componente = (nota_orientador_0_10 * PESO_ORIENTADOR) + (nota_pares_0_10 * PESO_PARES)
    return round(componente * float(nota_grupo_0_10), 2)


def _situacao_pares_ciclo(email: str, id_ciclo: str) -> tuple[float | None, bool]:
    """Retorna (nota de pares 0-10 ou None, se o aluno já enviou a avaliação)."""
    try:
        df = carregar_avaliacoes_pares()
    except Exception:
        return None, False

    if df.empty:
        return None, False

    id_c = str(id_ciclo).strip()
    email_l = email.lower().strip()
    df_c = df[df["ID_Ciclo"].astype(str).str.strip() == id_c]

    realizou = not df_c[df_c["Email_Avaliador"].astype(str).str.lower().str.strip() == email_l].empty
    recebidas = df_c[df_c["Email_Avaliado"].astype(str).str.lower().str.strip() == email_l]
    if recebidas.empty:
        return None, realizou

    media = pd.to_numeric(recebidas["Nota"], errors="coerce").mean()
    if pd.isna(media):
        return None, realizou
    return calcular_nota_pares(media, realizou), realizou


def _nota_pares_ciclo(email: str, id_ciclo: str) -> float | None:
    nota, _ = _situacao_pares_ciclo(email, id_ciclo)
    return nota


def _nota_grupo_ciclo(grupo: str, id_ciclo: str, sala: str = "") -> float | None:
    """Só libera a nota do grupo ao aluno com o mesmo critério da Avaliação do grupo."""
    aval = obter_media_avaliacao_grupo_aluno(id_ciclo, grupo, sala)
    if not aval:
        return None
    return float(aval["nota_total"])


def _montar_detalhe_ciclo(
    nota_grupo: float | None,
    nota_pares: float | None,
    nota_orientador: float | None,
) -> str:
    """Sempre reserva Grupo, Pares e Orientador; usa — se a nota ainda não saiu."""

    def _fmt(nota: float | None) -> str:
        return formatar_nota_entrega(nota) if nota is not None else "—"

    return (
        f"Grupo {_fmt(nota_grupo)} | "
        f"Pares {_fmt(nota_pares)} | "
        f"Orientador {_fmt(nota_orientador)}"
    )


def _resolver_nota_pares_ciclo(
    email: str,
    id_ciclo: str,
    nota_orientador: float | None,
    nota_grupo: float | None,
) -> float | None:
    """Pares só aparece depois que o aluno avalia, ou quando o ciclo já encerrou."""
    nota_pares, realizou = _situacao_pares_ciclo(email, id_ciclo)
    ciclo_encerrado = ciclo_inativo(id_ciclo)

    if not ciclo_encerrado and not realizou:
        return None

    if (
        nota_pares is None
        and nota_orientador is not None
        and nota_grupo is not None
        and ciclo_encerrado
    ):
        return 0.0
    return nota_pares


def _nota_atividades(email: str, id_disciplina: str) -> tuple[float | None, str]:
    try:
        df = ler_aba("Atividades_Individuais")
    except Exception:
        return None, "Sem atividades importadas"

    if df.empty:
        return None, "Sem atividades importadas"

    filtro = df[
        (df["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip())
        & (df["Email_Aluno"].astype(str).str.lower().str.strip() == email.lower().strip())
    ]
    if filtro.empty:
        return None, "Sem notas de atividades"

    media = pd.to_numeric(filtro["Nota"], errors="coerce").mean()
    return round(float(media), 1), f"Média de {len(filtro)} atividade(s)"


def _nota_dailies(email: str, id_disciplina: str = "") -> tuple[float | None, str]:
    df = calcular_matriz_dailies(email)
    if df.empty:
        return None, "Sem calendário de dailies"

    id_limpo = normalizar_id(id_disciplina)
    if id_limpo and "ID_Disciplina" in df.columns:
        df = df[df["ID_Disciplina"].map(normalizar_id) == id_limpo]
    if df.empty:
        return None, "Sem calendário de dailies nesta disciplina"

    vivido = df[df["Status_Tecnico"] != "Futuro"]
    if vivido.empty:
        return None, "Nenhuma daily realizada ainda"

    pres = len(vivido[vivido["Status_Aluno"] == "Presente"])
    pct = pres / len(vivido) * 100
    return round(pct, 1), f"{pres}/{len(vivido)} reuniões"


def calcular_boletim_aluno(email: str, id_disciplina: str, grupo: str, sala: str = "") -> pd.DataFrame:
    componentes = carregar_componentes_disciplina(id_disciplina)
    linhas = []

    for _, comp in componentes.iterrows():
        tipo = str(comp["Tipo"]).strip()
        nome = str(comp["Nome"]).strip()
        peso = float(comp["Peso"])
        id_ciclo_cfg = str(comp.get("ID_Ciclo", "")).strip()
        id_ciclo, origem_ciclo = resolver_id_ciclo_componente(tipo, id_ciclo_cfg, id_disciplina)

        nota: float | None = None
        detalhe = ""
        nota_ori: float | None = None
        nota_grp: float | None = None
        nota_par: float | None = None

        if tipo in ("Ciclo", "Entrega_Final") and id_ciclo:
            nota_ori = obter_nota_orientador(id_ciclo, email)
            nota_grp = _nota_grupo_ciclo(grupo, id_ciclo, sala)
            nota_par = _resolver_nota_pares_ciclo(email, id_ciclo, nota_ori, nota_grp)
            detalhe = _montar_detalhe_ciclo(nota_grp, nota_par, nota_ori)
            if origem_ciclo:
                detalhe += f" · iguais a {origem_ciclo}"

            if nota_ori is not None and nota_par is not None and nota_grp is not None:
                nota = calcular_nota_ciclo(nota_ori, nota_par, nota_grp)

        elif tipo == "Reuniao_Diaria":
            nota, detalhe = _nota_dailies(email, id_disciplina)

        elif tipo == "Atividade_Individual":
            nota, detalhe = _nota_atividades(email, id_disciplina)

        contribuicao = (nota * peso / 100) if nota is not None else None

        linhas.append(
            {
                "Componente": nome,
                "Tipo": tipo,
                "Peso (%)": peso,
                "Nota (0-100)": nota,
                "Nota_Orientador": nota_ori,
                "Nota_Pares": nota_par,
                "Nota_Grupo": nota_grp,
                "Contribuição": contribuicao,
                "Detalhe": detalhe,
            }
        )

    df = pd.DataFrame(linhas)
    return df


def nota_final_boletim(df_boletim: pd.DataFrame) -> float | None:
    if df_boletim.empty or df_boletim["Contribuição"].isna().any():
        contrib = df_boletim["Contribuição"].dropna()
        if contrib.empty:
            return None
        return round(float(contrib.sum()), 2)
    return round(float(df_boletim["Contribuição"].sum()), 2)


def status_academico(
    pct_presenca: float | None,
    nota_final: float | None,
    *,
    minimo_presenca: float = 75.0,
) -> str:
    """
    Regras de resultado da disciplina:
    - Presença < 75%: Reprovado (presença), independente da nota.
    - Presença >= 75%:
        - nota < 40: Reprovado
        - 40 <= nota < 70: Recuperação
        - nota >= 70: Aprovado
    """
    if pct_presenca is not None and float(pct_presenca) < minimo_presenca:
        return "Reprovado (presença)"
    if nota_final is None:
        return "Pendente"
    nota = float(nota_final)
    if nota < 40:
        return "Reprovado"
    if nota < 70:
        return "Recuperação"
    return "Aprovado"


def _fmt_nota_painel(valor: float | None) -> str:
    """Formato curto só para exibição; preferir número no DataFrame do painel."""
    num = _nota_numerica(valor)
    if num is None:
        return "—"
    return f"{num:.1f}"


def _nota_numerica(valor) -> float | None:
    """Converte nota para float; None/vazio/— → None (célula vazia na exportação)."""
    if valor is None:
        return None
    if isinstance(valor, str):
        txt = valor.strip()
        if not txt or txt in {"—", "–", "-", "nan", "None"}:
            return None
        txt = txt.replace(",", ".")
        try:
            return float(txt)
        except ValueError:
            return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _arredondar_exportacao(valor, casas: int = 3) -> float | None:
    num = _nota_numerica(valor)
    if num is None:
        return None
    return round(float(num), casas)


def preparar_exportacao_boletins(df: pd.DataFrame) -> pd.DataFrame:
    """
    Planilha limpa para Excel: textos sem travessão, notas como número
    com até 3 casas decimais, ausências como célula vazia.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    texto = {"Nome", "Turma", "Grupo", "Sala", "Status"}
    for col in out.columns:
        if col in texto:
            out[col] = (
                out[col]
                .map(lambda v: "" if v is None or str(v).strip() in {"", "—", "–", "nan", "None"} else str(v).strip())
            )
            continue
        out[col] = out[col].map(lambda v: _arredondar_exportacao(v, 3))
    return out


def bytes_excel_boletins(df: pd.DataFrame) -> bytes:
    """Gera .xlsx sem formatação especial (números reais, colunas já separadas)."""
    import io

    prep = preparar_exportacao_boletins(df)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        prep.to_excel(writer, index=False, sheet_name="Boletins", na_rep="")
    return buf.getvalue()


def _sigla_componente(nome: str) -> str:
    """Abrevia o nome do componente para cabeçalhos curtos no painel."""
    n = str(nome or "").strip()
    m = re.match(r"(?i)^\s*ciclo\s*(\d+)", n)
    if m:
        return f"C{m.group(1)}"
    if re.search(r"(?i)entrega", n):
        return "EF"
    if re.search(r"(?i)reuni[aã]o|daily", n):
        return "Daily"
    if re.search(r"(?i)atividad", n):
        return "Ativ"
    limpo = re.sub(r"[^A-Za-z0-9]+", "", n)
    return limpo[:8] or "Comp"


def _coluna_unica(base: str, usados: set[str]) -> str:
    if base not in usados:
        usados.add(base)
        return base
    i = 2
    while f"{base}{i}" in usados:
        i += 1
    out = f"{base}{i}"
    usados.add(out)
    return out


def _anexar_turma_base_alunos(alunos: pd.DataFrame) -> pd.DataFrame:
    """
    Turma de ingresso vem da Base_Alunos (provisório até a ficha no Supabase).
    A Entrância nem sempre traz Turma_Ingresso preenchida.
    """
    if alunos is None or alunos.empty:
        return alunos
    out = alunos.copy()
    try:
        base = ler_aba("Base_Alunos")
    except Exception:
        base = pd.DataFrame()
    if base is None or base.empty:
        if "Turma_Ingresso" not in out.columns:
            out["Turma_Ingresso"] = ""
        return out
    col_email = next(
        (c for c in ("Email_Pessoal", "Email", "E-mail") if c in base.columns),
        None,
    )
    col_turma = next(
        (c for c in ("Turma_Ingresso", "Turma", "Turma Ingresso") if c in base.columns),
        None,
    )
    if not col_email or not col_turma:
        if "Turma_Ingresso" not in out.columns:
            out["Turma_Ingresso"] = ""
        return out

    mapa = (
        base[[col_email, col_turma]]
        .assign(
            _em=lambda d: d[col_email].astype(str).str.strip().str.lower(),
            Turma_Ingresso=lambda d: d[col_turma]
            .astype(str)
            .str.strip()
            .replace({"nan": "", "None": "", "—": "", "–": ""}),
        )
        .drop_duplicates(subset=["_em"], keep="first")
        .set_index("_em")["Turma_Ingresso"]
        .to_dict()
    )
    emails = out["Email_Pessoal"].astype(str).str.strip().str.lower()
    # Preferência: Base_Alunos; se vazio, mantém o que já vier da Entrância.
    da_entrancia = (
        out["Turma_Ingresso"].astype(str).str.strip()
        if "Turma_Ingresso" in out.columns
        else pd.Series([""] * len(out), index=out.index)
    )
    da_entrancia = da_entrancia.replace({"nan": "", "None": "", "—": "", "–": ""})
    da_base = emails.map(lambda e: str(mapa.get(e, "") or "").strip())
    out["Turma_Ingresso"] = da_base.where(da_base.ne(""), da_entrancia)
    return out


def montar_painel_boletins_disciplina(id_disciplina: str) -> pd.DataFrame:
    """
    Monta tabela de boletins da disciplina para a tela de liberação de notas.
    Inclui presença realizada (com encontro presencial na conta) e status acadêmico.
    Cabeçalhos de componentes usam siglas curtas (ex.: C1 Ori, C1 Par, EF Tot).
    """
    from domain.presenca import carregar_base_presenca, compilar_grid_frequencia
    from utils.disciplina import normalizar_id

    id_disc = normalizar_id(id_disciplina)
    df_ent = ler_aba("Entrancia_Turma")
    if df_ent.empty:
        return pd.DataFrame()

    alunos = df_ent[
        df_ent["ID_Disciplina"].astype(str).map(normalizar_id) == id_disc
    ].copy()
    if alunos.empty:
        return pd.DataFrame()

    # Um vínculo por e-mail (primeira ocorrência).
    alunos["Email_Limpo"] = alunos["Email_Pessoal"].astype(str).str.strip().str.lower()
    alunos = alunos.drop_duplicates(subset=["Email_Limpo"], keep="first")
    alunos = _anexar_turma_base_alunos(alunos)

    dfs_cache = carregar_base_presenca()
    df_freq, _ = compilar_grid_frequencia(id_disc, alunos, dfs_cache=dfs_cache)
    freq_por_email: dict[str, float] = {}
    if not df_freq.empty:
        for _, fr in df_freq.iterrows():
            em = str(fr.get("Email_Cru", "")).strip().lower()
            freq_por_email[em] = float(fr.get("% Realizado", 0))

    # Mapa estável de colunas a partir do 1º aluno (mesma estrutura de componentes).
    usados: set[str] = set()
    mapa_cols: dict[tuple[str, str], str] = {}
    legendas: list[str] = []

    linhas: list[dict] = []
    for _, aluno in alunos.iterrows():
        email = str(aluno["Email_Pessoal"]).strip()
        email_l = email.lower()
        nome = str(aluno.get("Nome_Completo", "")).strip()
        turma = str(aluno.get("Turma_Ingresso", "")).strip()
        if turma.lower() in {"nan", "none", "—", "–"}:
            turma = ""
        grupo = str(aluno.get("Grupo", "")).strip()
        sala = str(aluno.get("Sala", "")).strip()
        pct = freq_por_email.get(email_l)

        boletim = calcular_boletim_aluno(email_l, id_disc, grupo, sala)
        nota_final = nota_final_boletim(boletim)
        status = status_academico(pct, nota_final)

        linha: dict = {
            "Nome": nome,
            "Turma": turma,
            "Grupo": grupo,
            "Sala": sala,
            "Pres.%": None if pct is None else round(float(pct), 3),
        }

        for _, comp in boletim.iterrows():
            nome_comp = str(comp["Componente"]).strip()
            tipo = str(comp.get("Tipo", "")).strip()
            sigla = _sigla_componente(nome_comp)
            if tipo in ("Ciclo", "Entrega_Final"):
                papeis = (
                    ("Ori", "Nota_Orientador", "Orientador(a)"),
                    ("Par", "Nota_Pares", "Pares"),
                    ("Grp", "Nota_Grupo", "Grupo"),
                    ("Tot", "Nota (0-100)", "Total"),
                )
                for sufixo, campo, rotulo_longo in papeis:
                    chave = (nome_comp, sufixo)
                    if chave not in mapa_cols:
                        col = _coluna_unica(f"{sigla} {sufixo}", usados)
                        mapa_cols[chave] = col
                        legendas.append(f"{col} = {nome_comp} · {rotulo_longo}")
                    linha[mapa_cols[chave]] = _nota_numerica(comp.get(campo))
            else:
                chave = (nome_comp, "")
                if chave not in mapa_cols:
                    col = _coluna_unica(sigla, usados)
                    mapa_cols[chave] = col
                    legendas.append(f"{col} = {nome_comp}")
                linha[mapa_cols[chave]] = _nota_numerica(comp.get("Nota (0-100)"))

        linha["Final"] = _nota_numerica(nota_final)
        linha["Status"] = status
        linhas.append(linha)

    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    # Legenda das siglas fica no attrs (a UI mostra se houver).
    df.attrs["legendas_colunas"] = legendas
    return df.sort_values(["Turma", "Sala", "Grupo", "Nome"], kind="stable").reset_index(drop=True)
