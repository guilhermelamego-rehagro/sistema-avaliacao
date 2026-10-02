"""Notas das atividades individuais: liberação por atividade, grid editável e histórico."""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from data.sheets import ler_aba
from domain.atividades_notas import (
    atividades_liberadas,
    carregar_historico,
    catalogo_atividades,
    nome_curto_atividade,
    notas_efetivas,
    reverter_edicoes,
    salvar_edicoes,
    salvar_liberacao_atividades,
)
from domain.canvas_import import carregar_alunos_disciplina
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa
from utils.logs import registrar_log
from utils.ordenacao import ordenar_grupos_lista

_COR_EDITADA = "background-color: rgba(255, 193, 7, 0.30); font-weight: 600"
_CHAVE_FLASH = "notas_ativ_flash"
_CHAVE_VERSAO = "notas_ativ_versao"


def _versao() -> int:
    return int(st.session_state.get(_CHAVE_VERSAO, 0))


def _concluir(mensagem: str):
    st.session_state[_CHAVE_FLASH] = mensagem
    st.session_state[_CHAVE_VERSAO] = _versao() + 1
    st.rerun()


def _rotulos(catalogo: pd.DataFrame, liberadas: set[str]) -> dict[str, str]:
    out = {}
    for _, a in catalogo.iterrows():
        icone = "✅" if a["ID_Atividade"] in liberadas else "🔒"
        prazo = str(a["Prazo"])[:5]
        out[a["ID_Atividade"]] = f"{icone} {a['ID_Atividade']}" + (f" · {prazo}" if prazo else "")
    return out


def _render_liberacao(id_disc: str, catalogo: pd.DataFrame, efetivas: pd.DataFrame, liberadas: set[str], usuario: dict):
    st.subheader("Liberação para os alunos")
    st.caption(
        "Marque as atividades que os alunos podem ver. Atividade oculta não aparece em "
        "**Minhas notas** nem entra na média de atividades do aluno."
    )
    contagem = efetivas[efetivas["Nota"].notna()].groupby("ID_Atividade").size()
    editadas = efetivas[efetivas["Editada"]].groupby("ID_Atividade").size()
    tabela = pd.DataFrame(
        {
            "Liberada": catalogo["ID_Atividade"].isin(liberadas),
            "Código": catalogo["ID_Atividade"],
            "Prazo": catalogo["Prazo"],
            "Atividade": catalogo["Atividade"].map(nome_curto_atividade),
            "Com nota": catalogo["ID_Atividade"].map(contagem).fillna(0).astype(int),
            "Editadas": catalogo["ID_Atividade"].map(editadas).fillna(0).astype(int),
        }
    )
    editado = st.data_editor(
        tabela,
        hide_index=True,
        width="stretch",
        disabled=[c for c in tabela.columns if c != "Liberada"],
        column_config={"Liberada": st.column_config.CheckboxColumn("Liberada")},
        key=f"notas_ativ_lib_{id_disc}_{_versao()}",
    )
    mudancas = {
        cod: bool(novo)
        for cod, antigo, novo in zip(tabela["Código"], tabela["Liberada"], editado["Liberada"])
        if bool(antigo) != bool(novo)
    }
    if st.button(
        f"Salvar liberação ({len(mudancas)} alteração(ões))" if mudancas else "Salvar liberação",
        type="primary",
        disabled=not mudancas,
        key=f"notas_ativ_lib_salvar_{id_disc}",
    ):
        nomes = dict(zip(catalogo["ID_Atividade"], catalogo["Atividade"]))
        salvar_liberacao_atividades(id_disc, mudancas, nomes, usuario["email"], usuario["nome"])
        lib = [c for c, v in mudancas.items() if v]
        ocu = [c for c, v in mudancas.items() if not v]
        partes = ([f"liberou {', '.join(lib)}"] if lib else []) + ([f"ocultou {', '.join(ocu)}"] if ocu else [])
        registrar_log(usuario["email"], usuario["nome"], f"Atividades: {'; '.join(partes)} - {id_disc}")
        _concluir("Liberação atualizada: " + "; ".join(partes) + ".")


def _montar_matriz(alunos: pd.DataFrame, efetivas: pd.DataFrame, rotulos: dict[str, str]) -> pd.DataFrame:
    base = alunos[["Email", "Nome", "Sala", "Grupo"]].copy()
    fora = efetivas[~efetivas["Email_Aluno"].isin(base["Email"])].drop_duplicates("Email_Aluno")
    if not fora.empty:
        base = pd.concat(
            [
                base,
                pd.DataFrame(
                    {"Email": fora["Email_Aluno"], "Nome": fora["Nome_Aluno"], "Sala": "", "Grupo": "fora da disciplina"}
                ),
            ],
            ignore_index=True,
        )
    mat = base.set_index("Email")
    notas = efetivas.pivot_table(index="Email_Aluno", columns="ID_Atividade", values="Nota", aggfunc="first")
    for ida, rot in rotulos.items():
        mat[rot] = notas[ida].reindex(mat.index) if ida in notas.columns else float("nan")
    mat[list(rotulos.values())] = mat[list(rotulos.values())].astype(float)
    mat["Média"] = mat[list(rotulos.values())].mean(axis=1, skipna=True).round(1)
    return mat.sort_values("Nome")


def _filtrar(mat: pd.DataFrame, id_disc: str) -> pd.DataFrame:
    f1, f2, f3 = st.columns([2, 1.2, 1.2])
    busca = f1.text_input("Filtrar por aluno:", key=f"notas_ativ_busca_{id_disc}", placeholder="Nome (parcial)").strip()
    salas = sorted({s for s in mat["Sala"] if s})
    grupos = ordenar_grupos_lista(sorted({g for g in mat["Grupo"] if g}))
    salas_sel = f2.multiselect("Sala:", salas, key=f"notas_ativ_sala_{id_disc}")
    grupos_sel = f3.multiselect("Grupo:", grupos, key=f"notas_ativ_grupo_{id_disc}")
    vista = mat
    if busca:
        vista = vista[vista["Nome"].str.contains(busca, case=False, na=False)]
    if salas_sel:
        vista = vista[vista["Sala"].isin(salas_sel)]
    if grupos_sel:
        vista = vista[vista["Grupo"].isin(grupos_sel)]
    return vista


def _config_colunas(catalogo: pd.DataFrame, rotulos: dict[str, str], *, edicao: bool) -> dict:
    config: dict = {
        "Nome": st.column_config.TextColumn("Aluno", pinned=True),
        "Sala": st.column_config.TextColumn("Sala", width="small"),
        "Grupo": st.column_config.TextColumn("Grupo", width="small"),
        "Média": st.column_config.TextColumn("Média", width="small"),
    }
    nomes = dict(zip(catalogo["ID_Atividade"], catalogo["Atividade"]))
    for ida, rot in rotulos.items():
        ajuda = nome_curto_atividade(nomes.get(ida, ""))
        if edicao:
            config[rot] = st.column_config.NumberColumn(
                rot, help=ajuda, min_value=0.0, max_value=100.0, step=0.01, format="%.1f"
            )
        else:
            config[rot] = st.column_config.TextColumn(rot, help=ajuda)
    return config


def _render_grid_leitura(vista: pd.DataFrame, efetivas: pd.DataFrame, catalogo: pd.DataFrame, rotulos: dict[str, str]):
    estilo = pd.DataFrame("", index=vista.index, columns=vista.columns)
    for _, r in efetivas[efetivas["Editada"]].iterrows():
        rot = rotulos.get(r["ID_Atividade"])
        if rot and r["Email_Aluno"] in estilo.index:
            estilo.loc[r["Email_Aluno"], rot] = _COR_EDITADA
    texto = vista.copy()
    for col in list(rotulos.values()) + ["Média"]:
        texto[col] = vista[col].map(lambda v: "—" if pd.isna(v) else f"{float(v):.1f}")
    styler = texto.style.apply(lambda _: estilo, axis=None)
    st.dataframe(
        styler,
        hide_index=True,
        width="stretch",
        height=min(52 + 35 * len(vista), 720),
        column_config=_config_colunas(catalogo, rotulos, edicao=False),
    )


def _diferencas(
    vista: pd.DataFrame, editado: pd.DataFrame, catalogo: pd.DataFrame, rotulos: dict[str, str]
) -> tuple[list[dict], list[str]]:
    info = catalogo.set_index("ID_Atividade")
    mudancas: list[dict] = []
    apagadas: list[str] = []
    for ida, rot in rotulos.items():
        for email in vista.index:
            antes, depois = vista.at[email, rot], editado.at[email, rot]
            if pd.isna(antes) and pd.isna(depois):
                continue
            if pd.isna(depois):
                apagadas.append(f"{vista.at[email, 'Nome']} · {ida}")
                continue
            if not pd.isna(antes) and abs(float(antes) - float(depois)) < 0.005:
                continue
            mudancas.append(
                {
                    "Email_Aluno": email,
                    "Nome_Aluno": vista.at[email, "Nome"],
                    "ID_Atividade": ida,
                    "Atividade": info.at[ida, "Atividade"],
                    "Prazo": info.at[ida, "Prazo"],
                    "Nota_Anterior": None if pd.isna(antes) else float(antes),
                    "Nota_Nova": round(float(depois), 2),
                }
            )
    return mudancas, apagadas


def _render_grid_edicao(
    id_disc: str, vista: pd.DataFrame, catalogo: pd.DataFrame, rotulos: dict[str, str], usuario: dict
):
    st.caption(
        "Neste modo o destaque amarelo não aparece e célula pendente mostra *None*. "
        "Nada é gravado até **Salvar alterações**."
    )
    colunas = ["Nome", "Sala", "Grupo"] + list(rotulos.values())
    filtro = hashlib.md5("|".join(vista.index).encode()).hexdigest()[:8]
    editado = st.data_editor(
        vista[colunas],
        hide_index=True,
        width="stretch",
        height=min(52 + 35 * len(vista), 720),
        num_rows="fixed",
        disabled=["Nome", "Sala", "Grupo"],
        column_config=_config_colunas(catalogo, rotulos, edicao=True),
        key=f"notas_ativ_editor_{id_disc}_{_versao()}_{filtro}",
    )
    mudancas, apagadas = _diferencas(vista, editado, catalogo, rotulos)
    if apagadas:
        st.warning(
            "Célula apagada não é gravada: "
            + ", ".join(apagadas)
            + ". Para voltar ao valor do Canvas, use **Reverter edição** abaixo."
        )
    if not mudancas:
        st.caption("Altere as células e salve com um motivo. Mudar o filtro descarta alterações não salvas.")
        return

    st.markdown(f"**{len(mudancas)} alteração(ões) a salvar:**")
    st.dataframe(
        pd.DataFrame(
            {
                "Aluno": [m["Nome_Aluno"] for m in mudancas],
                "Atividade": [rotulos[m["ID_Atividade"]] for m in mudancas],
                "De": [m["Nota_Anterior"] for m in mudancas],
                "Para": [m["Nota_Nova"] for m in mudancas],
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "De": st.column_config.NumberColumn(format="%.1f"),
            "Para": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    motivo = st.text_input(
        "Motivo (obrigatório, fica no histórico):",
        key=f"notas_ativ_motivo_{id_disc}",
        placeholder="Ex.: entrega aceita fora do prazo; correção revista",
    ).strip()
    if st.button(
        "Salvar alterações",
        type="primary",
        disabled=not motivo,
        key=f"notas_ativ_salvar_{id_disc}",
    ):
        qtd = salvar_edicoes(id_disc, mudancas, motivo, usuario["email"], usuario["nome"])
        registrar_log(usuario["email"], usuario["nome"], f"Editou {qtd} nota(s) de atividades - {id_disc}")
        _concluir(f"{qtd} nota(s) editada(s).")


def _render_editadas(id_disc: str, efetivas: pd.DataFrame, rotulos: dict[str, str], usuario: dict):
    ed = efetivas[efetivas["Editada"]].sort_values(["Nome_Aluno", "ID_Atividade"])
    with st.expander(f"Notas editadas manualmente ({len(ed)})", expanded=False):
        if ed.empty:
            st.caption("Nenhuma nota editada nesta disciplina.")
            return
        st.caption(
            "Edições prevalecem sobre o Canvas e não são substituídas por novas importações. "
            "**Canvas (atual)** mostra o valor da última importação."
        )
        rotulo_linha = ed["Nome_Aluno"] + " · " + ed["ID_Atividade"].map(rotulos)
        st.dataframe(
            pd.DataFrame(
                {
                    "Aluno": ed["Nome_Aluno"],
                    "Atividade": ed["ID_Atividade"].map(rotulos),
                    "Nota editada": ed["Nota"],
                    "Canvas (atual)": ed["Nota_Canvas"],
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Nota editada": st.column_config.NumberColumn(format="%.1f"),
                "Canvas (atual)": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        escolha = st.multiselect(
            "Reverter edição (volta ao valor do Canvas):",
            rotulo_linha.tolist(),
            key=f"notas_ativ_rev_sel_{id_disc}_{_versao()}",
        )
        if not escolha:
            return
        motivo = st.text_input("Motivo da reversão (obrigatório):", key=f"notas_ativ_rev_motivo_{id_disc}").strip()
        if st.button("Reverter selecionadas", disabled=not motivo, key=f"notas_ativ_rev_btn_{id_disc}"):
            celulas = ed[rotulo_linha.isin(escolha).values]
            qtd = reverter_edicoes(id_disc, celulas, motivo, usuario["email"], usuario["nome"])
            registrar_log(usuario["email"], usuario["nome"], f"Reverteu {qtd} edição(ões) de atividades - {id_disc}")
            _concluir(f"{qtd} edição(ões) revertida(s).")


def _render_historico(id_disc: str):
    st.subheader("Histórico")
    hist = carregar_historico(id_disc)
    if hist.empty:
        st.caption("Sem registros ainda. Importações, liberações, edições e reversões aparecem aqui.")
        return
    h1, h2 = st.columns([2, 2])
    busca = h1.text_input("Filtrar por aluno ou atividade:", key=f"notas_ativ_hist_busca_{id_disc}").strip()
    acoes = sorted({a for a in hist["Acao"].astype(str) if a})
    acoes_sel = h2.multiselect("Ação:", acoes, key=f"notas_ativ_hist_acao_{id_disc}")
    if busca:
        alvo = hist["Nome_Aluno"].astype(str) + " " + hist["ID_Atividade"].astype(str) + " " + hist["Atividade"].astype(str)
        hist = hist[alvo.str.contains(busca, case=False, na=False)]
    if acoes_sel:
        hist = hist[hist["Acao"].isin(acoes_sel)]
    st.dataframe(
        pd.DataFrame(
            {
                "Data": hist["Data"],
                "Ação": hist["Acao"],
                "Aluno": hist["Nome_Aluno"],
                "Atividade": hist["ID_Atividade"],
                "De": hist["Nota_Anterior"],
                "Para": hist["Nota_Nova"],
                "Motivo / detalhe": hist["Motivo"],
                "Responsável": hist["Nome_Responsavel"],
            }
        ),
        hide_index=True,
        width="stretch",
        height=min(52 + 35 * len(hist), 420),
    )


def render(usuario: dict):
    st.header("Notas das atividades individuais")
    st.caption(
        "Notas importadas do Canvas (0–100). Professores podem liberar por atividade, "
        "editar notas no grid e reverter edições. Tudo fica registrado no histórico."
    )
    flash = st.session_state.pop(_CHAVE_FLASH, None)
    if flash:
        st.success(flash)

    df_disc = ler_aba("Disciplinas")
    lista_disc = df_disc["Nome_Disciplina"].unique().tolist()
    disc_sel = st.selectbox(
        "Disciplina:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
        key="notas_ativ_disc",
    )
    id_disc = id_disciplina_por_nome(df_disc, disc_sel)

    efetivas = notas_efetivas(id_disc)
    if efetivas.empty:
        st.info("Nenhuma nota de atividade nesta disciplina. Importe pelo menu **Importar Canvas**.")
        _render_historico(id_disc)
        return

    catalogo = catalogo_atividades(efetivas)
    liberadas = atividades_liberadas(id_disc)
    rotulos = _rotulos(catalogo, liberadas)

    _render_liberacao(id_disc, catalogo, efetivas, liberadas, usuario)
    st.divider()

    st.subheader("Notas por aluno")
    st.caption(
        "✅ liberada · 🔒 oculta para os alunos · **—** pendente (sem nota). "
        "Células em **amarelo** foram editadas por professor e não mudam em novas importações. "
        "A média considera todas as atividades com nota, liberadas ou não."
    )
    mat = _montar_matriz(carregar_alunos_disciplina(id_disc), efetivas, rotulos)
    vista = _filtrar(mat, id_disc)
    if vista.empty:
        st.warning("Nenhum aluno com os filtros atuais.")
    elif st.toggle("Modo edição", key=f"notas_ativ_modo_{id_disc}"):
        _render_grid_edicao(id_disc, vista, catalogo, rotulos, usuario)
    else:
        _render_grid_leitura(vista, efetivas, catalogo, rotulos)

    _render_editadas(id_disc, efetivas, rotulos, usuario)
    st.divider()
    _render_historico(id_disc)
