"""Tela do aluno: comentários da banca (avaliação de grupo) por ciclo."""

from __future__ import annotations

import streamlit as st

from data.sheets import ler_aba
from domain.avaliacoes import formatar_nota_entrega, listar_comentarios_banca_grupo
from domain.ciclos import ciclo_inativo, obter_disciplina_ativa, ordenar_ciclos
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


def _mostrar_media(itens: list[dict], id_ciclo: str) -> bool:
    """Média só com 2+ avaliações da banca ou depois que o ciclo encerrou."""
    return len(itens) >= 2 or ciclo_inativo(id_ciclo)


def render(usuario: dict):
    st.header("Avaliação do grupo")
    st.caption(
        "Comentários da banca. A nota média do grupo aparece com duas ou mais "
        "avaliações, ou após o ciclo encerrar."
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

        if _mostrar_media(itens, id_ciclo):
            media = sum(i["nota_total"] for i in itens) / len(itens)
            titulo = f"{nome_ciclo} — média da banca {formatar_nota_entrega(media)}"
        else:
            titulo = nome_ciclo

        with st.expander(titulo, expanded=True):
            if not _mostrar_media(itens, id_ciclo):
                st.caption(
                    "A média da banca será exibida quando houver pelo menos duas "
                    "avaliações ou após o encerramento do ciclo."
                )
            for item in itens:
                with st.container(border=True):
                    st.markdown(f"**{item['nome_avaliador'] or 'Avaliador'}**")
                    if item["comentario"]:
                        st.write(item["comentario"])
                    else:
                        st.caption("Sem comentário escrito neste lançamento.")
