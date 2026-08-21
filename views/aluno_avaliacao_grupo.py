"""Tela do aluno: comentários da banca (avaliação de grupo) por ciclo."""

from __future__ import annotations

import streamlit as st

from data.sheets import ler_aba
from domain.avaliacoes import (
    formatar_nota_entrega,
    listar_comentarios_banca_grupo,
    obter_media_avaliacao_grupo_aluno,
)
from domain.ciclos import obter_disciplina_ativa, ordenar_ciclos
from utils.logs import registrar_log_acesso


def _mapa_ciclos(id_disciplina: str) -> dict[str, tuple[int, str]]:
    df = ler_aba("Ciclos")
    ciclos = ordenar_ciclos(
        df[df["ID_Disciplina"].astype(str).str.strip() == str(id_disciplina).strip()]
    )
    mapa: dict[str, tuple[int, str]] = {}
    for i, (_, row) in enumerate(ciclos.iterrows(), start=1):
        id_ciclo = str(row.get("ID_Ciclo", "")).strip()
        nome = str(row.get("Nome_Ciclo", "")).strip()
        if id_ciclo:
            mapa[id_ciclo] = (i, nome)
    return mapa


def render(usuario: dict):
    st.header("Avaliação do grupo")
    st.caption(
        "Comentários da banca. A nota do grupo (média ou conferência) só aparece "
        "com 2+ avaliações de professores, após o fim da janela de pares do ciclo, "
        "ou se a coordenação registrar nota de conferência."
    )
    registrar_log_acesso(usuario["email"], usuario["nome"], "Visualizou Avaliação do Grupo")

    id_disc, nome_disc = obter_disciplina_ativa()
    if not id_disc:
        st.warning("Nenhuma disciplina ativa no momento.")
        return

    df_entrancia = ler_aba("Entrancia_Turma")
    vinculo = df_entrancia[
        (df_entrancia["Email_Pessoal"].astype(str).str.lower().str.strip() == usuario["email"])
        & (df_entrancia["ID_Disciplina"].astype(str).str.strip() == str(id_disc).strip())
    ]
    if vinculo.empty:
        st.error("Vínculo com a disciplina ativa não encontrado.")
        return

    grupo = str(vinculo.iloc[0]["Grupo"]).strip()
    sala = str(vinculo.iloc[0].get("Sala", "")).strip()
    st.info(f"**Disciplina:** {nome_disc} | **Grupo:** {grupo} | **Sala:** {sala or '—'}")

    registros = listar_comentarios_banca_grupo(str(id_disc), grupo, sala)
    if not registros:
        st.info("A banca ainda não lançou avaliação para o seu grupo nesta disciplina.")
        return

    ordem = _mapa_ciclos(str(id_disc))
    por_ciclo: dict[str, list[dict]] = {}
    for item in registros:
        por_ciclo.setdefault(item["id_ciclo"], []).append(item)

    ciclos_ordenados = sorted(
        por_ciclo.keys(),
        key=lambda cid: (ordem.get(cid, (999, ""))[0], cid),
    )

    for id_ciclo in ciclos_ordenados:
        itens = sorted(por_ciclo[id_ciclo], key=lambda x: x["nome_avaliador"].lower())
        nome_ciclo = ordem.get(id_ciclo, (0, itens[0]["nome_ciclo"] or f"Ciclo {id_ciclo}"))[1]
        oficial = obter_media_avaliacao_grupo_aluno(id_ciclo, grupo, sala, str(id_disc))

        if oficial and oficial.get("origem") == "conferencia":
            titulo = (
                f"{nome_ciclo} — nota da coordenação "
                f"{formatar_nota_entrega(oficial['nota_total'])}"
            )
        elif oficial:
            titulo = (
                f"{nome_ciclo} — média da banca "
                f"{formatar_nota_entrega(oficial['nota_total'])}"
            )
        else:
            titulo = nome_ciclo

        with st.expander(titulo, expanded=True):
            if oficial and oficial.get("origem") == "conferencia":
                st.caption(
                    "A coordenação registrou uma nota de conferência que substitui a média da banca."
                )
            elif not oficial:
                st.caption(
                    "A média da banca será exibida quando houver pelo menos duas "
                    "avaliações de professores ou após o encerramento da janela de pares do ciclo."
                )
            for item in itens:
                with st.container(border=True):
                    rotulo = item["nome_avaliador"]
                    if item.get("eh_conferencia"):
                        rotulo = f"{rotulo} (conferência)"
                    st.markdown(f"**{rotulo}**")
                    st.write(
                        f"Apresentação {formatar_nota_entrega(item['nota_apresentacao'])} · "
                        f"Conteúdo {formatar_nota_entrega(item['nota_conteudo'])} · "
                        f"Total {formatar_nota_entrega(item['nota_total'])}"
                    )
                    if item.get("comentario"):
                        st.write(item["comentario"])
