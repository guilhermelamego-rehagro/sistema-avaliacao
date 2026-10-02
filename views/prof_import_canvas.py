"""Importação de notas de atividades individuais a partir do export do Canvas."""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.atividades_notas import ACAO_IMPORTACAO, registrar_historico
from domain.canvas_import import (
    DESCARTAR,
    alunos_app_sem_canvas,
    carregar_alunos_disciplina,
    carregar_mapa_canvas,
    contar_substituicoes,
    cruzar_alunos,
    gravar_importacao,
    ler_export_canvas,
    montar_notas,
)
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.logs import registrar_log

_REVISAR_DEPOIS = "— Não importar agora —"
_OPCAO_DESCARTAR = "Descartar (não perguntar de novo)"
_METODO_LABEL = {
    "vinculo_salvo": "Vínculo salvo",
    "nome_exato": "Nome exato",
    "nome_parcial": "Nome parcial",
    "manual": "Manual",
    "descartado": "Descartado",
    "": "Sem correspondência",
}


def _render_atividades(atividades, notas: pd.DataFrame):
    st.subheader("1. Atividades encontradas")
    resumo = []
    for a in atividades:
        sub = notas[notas["ID_Atividade"] == a.id] if not notas.empty else notas
        resumo.append(
            {
                "Código": a.id,
                "Ciclo": a.ciclo,
                "Prazo": a.prazo.strftime("%d/%m/%Y") if a.prazo is not None else "—",
                "Pontos": a.pontos,
                "Com nota": int((sub["Situacao"] == "nota").sum()) if not sub.empty else 0,
                "Vazias → zero": int((sub["Situacao"] == "zero_vencida").sum()) if not sub.empty else 0,
                "Pendentes": int((sub["Situacao"] == "pendente").sum()) if not sub.empty else 0,
            }
        )
    st.dataframe(pd.DataFrame(resumo), width="stretch", hide_index=True)
    st.caption(
        "Notas convertidas para 0–100 (nota ÷ pontos × 100). Célula vazia vira **zero** "
        "quando o prazo já passou e a atividade já tem nota de alguém da turma; "
        "senão fica **pendente** e não é gravada. Colunas de totais do Canvas são ignoradas."
    )
    sem_nota = [r["Código"] for r in resumo if r["Com nota"] == 0]
    if sem_nota:
        st.warning(
            f"Atividade(s) sem nenhuma nota no arquivo: {', '.join(sem_nota)}. "
            "Confira no Canvas se as notas foram publicadas."
        )


def _render_revisao(cruzamento: pd.DataFrame, alunos: pd.DataFrame, chave: str) -> pd.DataFrame:
    """Escolhas manuais para linhas sem correspondência ou casadas por nome parcial."""
    st.subheader("2. Correspondência de alunos")
    contagem = cruzamento["Metodo"].map(_METODO_LABEL).value_counts()
    cols = st.columns(len(contagem))
    for col, (rotulo, qtd) in zip(cols, contagem.items()):
        col.metric(rotulo, int(qtd))

    revisar = cruzamento[cruzamento["Metodo"].isin(["", "nome_parcial"])]
    if revisar.empty:
        st.success("Todos os alunos do Canvas foram associados automaticamente.")
        return cruzamento

    st.markdown(
        "**Revise as linhas abaixo.** Nome parcial já vem sugerido; sem correspondência, "
        "escolha o aluno do app ou descarte. A escolha fica salva para as próximas importações."
    )
    usados_auto = set(
        cruzamento.loc[~cruzamento["Metodo"].isin(["", "nome_parcial"]) & cruzamento["Email_App"].ne(""), "Email_App"]
    )
    livres = alunos[~alunos["Email"].isin(usados_auto)]
    rotulo_por_email = {
        r["Email"]: f"{r['Nome']} <{r['Email']}>" + (f" · grupo {r['Grupo']}" if r["Grupo"] else "")
        for _, r in livres.iterrows()
    }
    email_por_rotulo = {v: k for k, v in rotulo_por_email.items()}
    opcoes_base = [_REVISAR_DEPOIS, _OPCAO_DESCARTAR] + sorted(rotulo_por_email.values())

    out = cruzamento.copy()
    for idx, row in revisar.iterrows():
        sugerido = rotulo_por_email.get(row["Email_App"], _REVISAR_DEPOIS)
        with st.container(border=True):
            c1, c2 = st.columns([2, 3])
            c1.markdown(f"**{row['Nome_Canvas']}**")
            c1.caption(f"{row['Turma_Canvas']} · {row['Login_Canvas']}")
            if row["Observacao"]:
                c1.caption(f"⚠️ {row['Observacao']}")
            escolha = c2.selectbox(
                "Aluno no app",
                opcoes_base,
                index=opcoes_base.index(sugerido),
                key=f"canvas_rev_{chave}_{row['ID_Canvas']}",
            )
        if escolha == _REVISAR_DEPOIS:
            out.loc[idx, ["Email_App", "Nome_App", "Metodo"]] = ["", "", ""]
        elif escolha == _OPCAO_DESCARTAR:
            out.loc[idx, ["Email_App", "Nome_App", "Metodo"]] = ["", "", "descartado"]
        else:
            email = email_por_rotulo[escolha]
            metodo = "nome_parcial" if email == row["Email_App"] and row["Metodo"] == "nome_parcial" else "manual"
            out.loc[idx, ["Email_App", "Nome_App", "Metodo"]] = [
                email,
                livres.loc[livres["Email"] == email, "Nome"].iloc[0],
                metodo,
            ]

    duplicados = out.loc[out["Email_App"].ne(""), "Email_App"]
    duplicados = duplicados[duplicados.duplicated()]
    if not duplicados.empty:
        st.error(
            "O mesmo aluno do app foi escolhido para mais de uma linha do Canvas: "
            + ", ".join(sorted(set(duplicados)))
        )
    return out


def _render_sem_canvas(alunos: pd.DataFrame, cruzamento: pd.DataFrame):
    sem = alunos_app_sem_canvas(alunos, cruzamento)
    with st.expander(f"Alunos da disciplina no app sem linha no Canvas ({len(sem)})", expanded=not sem.empty):
        if sem.empty:
            st.caption("Todos os alunos da disciplina aparecem no arquivo.")
            return
        st.caption(
            "Não recebem nota nesta importação. Se algum deles estiver no Canvas com outro nome, "
            "associe-o na revisão acima."
        )
        st.dataframe(
            sem[["Nome", "Email", "Sala", "Grupo", "Observacao"]],
            width="stretch",
            hide_index=True,
        )


def _render_previa_notas(notas: pd.DataFrame):
    st.subheader("3. Prévia das notas (0–100)")
    if notas.empty:
        st.info("Nenhum aluno associado — nada a importar.")
        return
    tabela = notas.copy()
    tabela["Valor"] = tabela.apply(
        lambda r: "pend." if r["Situacao"] == "pendente" else f"{r['Nota']:.0f}", axis=1
    )
    pivo = tabela.pivot_table(
        index=["Nome_Aluno", "Email_Aluno"], columns="ID_Atividade", values="Valor", aggfunc="first"
    )
    medias = (
        tabela[tabela["Situacao"] != "pendente"].groupby(["Nome_Aluno", "Email_Aluno"])["Nota"].mean().round(1)
    )
    pivo["Média"] = medias
    st.dataframe(pivo.reset_index(), width="stretch", hide_index=True)
    st.caption("A média considera só atividades gravadas (com nota ou zero por vencimento).")


def render(usuario: dict):
    st.header("📥 Importar atividades do Canvas")
    st.caption(
        "Envie o export de notas do Canvas (Notas → Exportar CSV), já filtrado nas atividades "
        "individuais. Os alunos são associados pelo nome, porque o login do Canvas é o e-mail pessoal."
    )

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox(
        "Disciplina de destino:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
        key="canvas_disc",
    )
    id_disc = id_disciplina_por_nome(df_disc, disc_sel)

    arquivo = st.file_uploader("Arquivo do Canvas (.csv ou .xlsx)", type=["csv", "xlsx"])
    if not arquivo:
        return

    conteudo = arquivo.getvalue()
    chave = hashlib.md5(conteudo + str(id_disc).encode()).hexdigest()[:10]
    try:
        df_canvas, atividades = ler_export_canvas(conteudo, arquivo.name)
    except Exception as e:
        st.error(f"Não foi possível ler o arquivo: {e}")
        return

    alunos = carregar_alunos_disciplina(id_disc)
    if alunos.empty:
        st.error("Nenhum aluno vinculado a esta disciplina na Entrância.")
        return

    cruzamento = cruzar_alunos(df_canvas, alunos, ler_aba("Base_Alunos"), carregar_mapa_canvas())
    if cruzamento["Email_App"].ne("").sum() < len(cruzamento) / 2:
        st.warning(
            "Menos da metade dos alunos do arquivo foi encontrada nesta disciplina. "
            "Confira se a disciplina de destino está certa."
        )

    notas_previas = montar_notas(df_canvas, atividades, cruzamento)
    _render_atividades(atividades, notas_previas)

    cruzamento = _render_revisao(cruzamento, alunos, chave)
    _render_sem_canvas(alunos, cruzamento)

    notas = montar_notas(df_canvas, atividades, cruzamento)
    _render_previa_notas(notas)

    st.subheader("4. Gravar")
    ids = {a.id for a in atividades}
    gravaveis = notas[notas["Situacao"] != "pendente"] if not notas.empty else notas
    substituidas, editadas = contar_substituicoes(id_disc, ids)
    nao_importados = int((cruzamento["Metodo"] == "").sum())
    st.markdown(
        f"Serão gravadas **{len(gravaveis)}** notas de **{gravaveis['Email_Aluno'].nunique() if not gravaveis.empty else 0}** alunos"
        + (f", substituindo **{substituidas}** já importadas destas atividades." if substituidas else ".")
    )
    if editadas:
        st.caption(
            f"{editadas} nota(s) editada(s) por professores nestas atividades continuam valendo; "
            "o valor novo do Canvas fica registrado ao lado em **Notas das atividades**."
        )
    st.caption("Notas novas entram **ocultas** para os alunos até a liberação em **Notas das atividades**.")
    if nao_importados:
        st.caption(f"{nao_importados} linha(s) do Canvas ficam de fora (sem aluno escolhido).")

    duplicado = cruzamento.loc[cruzamento["Email_App"].ne(""), "Email_App"].duplicated().any()
    confirmado = st.checkbox("Conferi a correspondência e a prévia das notas.", key=f"canvas_ok_{chave}")
    if st.button(
        "Gravar importação",
        type="primary",
        width="stretch",
        disabled=not confirmado or duplicado or gravaveis.empty,
    ):
        vinculos = cruzamento[cruzamento["Metodo"].ne("")].copy()
        vinculos["Email_Aluno"] = vinculos.apply(
            lambda r: DESCARTAR if r["Metodo"] == "descartado" else r["Email_App"], axis=1
        )
        vinculos = vinculos.rename(columns={"Metodo": "Origem"})[
            ["ID_Canvas", "Email_Aluno", "Nome_Canvas", "Origem"]
        ]
        with st.spinner("Gravando…"):
            qtd = gravar_importacao(id_disc, notas, ids, vinculos, usuario["email"])
        registrar_log(
            usuario["email"],
            usuario["nome"],
            f"Importou {qtd} notas Canvas ({len(ids)} atividades) - {disc_sel}",
        )
        por_atividade = gravaveis.groupby("ID_Atividade")
        registrar_historico(
            [
                {
                    "ID_Disciplina": id_disc,
                    "ID_Atividade": ida,
                    "Atividade": grupo["Atividade"].iloc[0],
                    "Acao": ACAO_IMPORTACAO,
                    "Motivo": f"{len(grupo)} nota(s) gravada(s)",
                }
                for ida, grupo in por_atividade
            ],
            usuario["email"],
            usuario["nome"],
        )
        st.success(f"{qtd} notas gravadas para **{disc_sel}**.")
