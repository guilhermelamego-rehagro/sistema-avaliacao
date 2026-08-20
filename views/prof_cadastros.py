"""Cadastros acadêmicos do coordenador: disciplinas, ciclos e professores."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from domain.cadastros import (
    COLUNAS_CICLOS,
    ENCONTRO_OPCOES,
    STATUS_OPCOES,
    TIPOS_PROFESSOR_CONFIG,
    carregar_ciclos,
    carregar_disciplinas,
    carregar_professores,
    normalizar_df_ciclos_editor,
    pares_codigo_alterado,
    alinhar_codigos_frequencia,
    alinhar_codigos_ciclos,
    propagar_codigo_disciplina,
    salvar_ciclos,
    salvar_disciplinas,
    salvar_professores,
)
from domain.encontro_presencial import (
    carregar_datas_encontro,
    normalizar_df_datas_editor,
    salvar_datas_encontro,
)
from domain.modelo_padrao import (
    aplicar_decisao_entrega_final,
    entrega_final_ja_separada,
    garantir_estrutura_padrao,
)
from utils.disciplina import normalizar_id
from utils.logs import registrar_log


def _ids_disciplina(df_disc: pd.DataFrame) -> list[str]:
    return sorted(
        {str(x).strip() for x in df_disc["ID_Disciplina"].tolist() if str(x).strip()}
    )


def _rotulo_disc(df_disc: pd.DataFrame, id_disc: str) -> str:
    match = df_disc[df_disc["ID_Disciplina"].astype(str).str.strip() == str(id_disc).strip()]
    if match.empty:
        return str(id_disc)
    return f"{id_disc} — {match.iloc[0]['Nome_Disciplina']}"


COLUNAS_DISC = ["ID_Disciplina", "Nome_Disciplina", "Status", "Encontro_Presencial"]


def _garantir_df_disciplinas(chave: str) -> pd.DataFrame:
    if chave not in st.session_state:
        st.session_state[chave] = carregar_disciplinas()
    df = st.session_state[chave].copy()
    for col in COLUNAS_DISC:
        if col not in df.columns:
            if col == "Encontro_Presencial":
                df[col] = "Não"
            elif col == "Status":
                df[col] = "inativo"
            else:
                df[col] = ""
    df["Encontro_Presencial"] = df["Encontro_Presencial"].replace("", "Não")
    st.session_state[chave] = df
    return df


def _seed_campos_disciplina(idx: int, row: pd.Series, ver: int):
    padroes = {
        f"disc_id_{idx}_{ver}": str(row.get("ID_Disciplina", "")),
        f"disc_nome_{idx}_{ver}": str(row.get("Nome_Disciplina", "")),
        f"disc_status_{idx}_{ver}": str(row.get("Status", "inativo")),
        f"disc_enc_{idx}_{ver}": str(row.get("Encontro_Presencial", "Não")),
    }
    for chave, valor in padroes.items():
        if chave not in st.session_state:
            st.session_state[chave] = valor


def _ler_disciplina_form(idx: int, ver: int) -> dict:
    return {
        "ID_Disciplina": str(st.session_state.get(f"disc_id_{idx}_{ver}", "")).strip(),
        "Nome_Disciplina": str(st.session_state.get(f"disc_nome_{idx}_{ver}", "")).strip(),
        "Status": str(st.session_state.get(f"disc_status_{idx}_{ver}", "inativo")).strip(),
        "Encontro_Presencial": str(st.session_state.get(f"disc_enc_{idx}_{ver}", "Não")).strip(),
    }


def render_disciplinas(usuario: dict):
    st.header("Cadastro de disciplinas")
    st.caption(
        "Cada disciplina aparece recolhida (código e nome). Clique para expandir e editar. "
        "O **código** é só a disciplina/área (ex.: **TRIB**), sem ano nem trimestre — "
        "isso fica no planejamento (oferta). Se você alterar um código já usado "
        "(ex.: 20263TRI → TRIB), o sistema atualiza ciclos, notas, presença e as demais abas. "
        "Deixe **apenas uma** disciplina como ativa. "
        "**Encontro presencial** habilita as datas e o lançamento de presença no card. "
        "Ao cadastrar, o sistema cria os componentes padrão "
        "(4 ciclos, entrega final, reuniões diárias e atividades individuais). "
        "Se a disciplina **ativa** tiver encontro presencial, perguntamos se a "
        "entrega final deve ter avaliação própria."
    )
    chave = "cad_disc_edit"
    ver_chave = "cad_disc_widgets_ver"
    if ver_chave not in st.session_state:
        st.session_state[ver_chave] = 0
    ver = int(st.session_state[ver_chave])

    for aviso in st.session_state.pop("cad_disc_avisos", []):
        st.info(aviso)

    if _render_pergunta_entrega_final(usuario):
        return

    df = _garantir_df_disciplinas(chave)

    c_nova, _ = st.columns([1, 3])
    if c_nova.button("➕ Nova disciplina", width="stretch"):
        nova = pd.DataFrame(
            [{"ID_Disciplina": "", "Nome_Disciplina": "", "Status": "inativo", "Encontro_Presencial": "Não"}]
        )
        st.session_state[chave] = pd.concat([st.session_state[chave], nova], ignore_index=True)
        st.session_state[ver_chave] = ver + 1
        st.rerun()

    if df.empty:
        st.info("Nenhuma disciplina cadastrada. Use **Nova disciplina** para começar.")
        return

    remover_idx: int | None = None
    for idx, row in df.iterrows():
        _seed_campos_disciplina(idx, row, ver)

    for idx in sorted(
        df.index.tolist(),
        key=lambda i: (
            0 if str(st.session_state.get(f"disc_status_{i}_{ver}", "inativo")).strip() == "ativo" else 1,
            str(st.session_state.get(f"disc_id_{i}_{ver}", "")).strip(),
        ),
    ):
        row = df.loc[idx]
        nome_atual = str(st.session_state.get(f"disc_nome_{idx}_{ver}", "")).strip()
        status_atual = str(st.session_state.get(f"disc_status_{idx}_{ver}", "inativo")).strip()
        enc_atual = str(st.session_state.get(f"disc_enc_{idx}_{ver}", "Não")).strip()
        codigo_atual = str(st.session_state.get(f"disc_id_{idx}_{ver}", "")).strip() or "—"
        rotulos = []
        if status_atual == "ativo":
            rotulos.append("Ativa")
        if enc_atual == "Sim":
            rotulos.append("Encontro presencial")
        rotulo_expander = f"{codigo_atual} — {nome_atual or 'Nova disciplina'}"
        if rotulos:
            rotulo_expander = f"{rotulo_expander} ({' · '.join(rotulos)})"

        with st.expander(rotulo_expander, expanded=False):
            if st.button("Remover disciplina", key=f"disc_del_{idx}_{ver}"):
                remover_idx = idx

            c1, c2 = st.columns(2)
            c1.text_input(
                "Código",
                key=f"disc_id_{idx}_{ver}",
                placeholder="Ex.: TRIB",
                help="Sigla estável da disciplina. Ano e trimestre não entram aqui.",
            )
            c2.text_input("Nome", key=f"disc_nome_{idx}_{ver}")
            c3, c4 = st.columns(2)
            c3.selectbox("Status", STATUS_OPCOES, key=f"disc_status_{idx}_{ver}")
            c4.selectbox(
                "Encontro presencial",
                ENCONTRO_OPCOES,
                key=f"disc_enc_{idx}_{ver}",
                help=(
                    "Sim: cadastre abaixo os dias do encontro e lance presença manualmente. "
                    "Ao ativar a disciplina, perguntamos se a entrega final terá avaliação própria."
                ),
            )

            enc_atual = str(st.session_state.get(f"disc_enc_{idx}_{ver}", "Não")).strip()
            if enc_atual == "Sim":
                id_disc_card = str(st.session_state.get(f"disc_id_{idx}_{ver}", "")).strip()
                _render_datas_encontro_card(usuario, id_disc_card, idx)

    if remover_idx is not None:
        restante = st.session_state[chave].drop(index=remover_idx).reset_index(drop=True)
        st.session_state[chave] = restante
        st.session_state[ver_chave] = ver + 1
        st.rerun()

    if st.button("Salvar disciplinas", type="primary"):
        linhas = [_ler_disciplina_form(i, ver) for i in range(len(st.session_state[chave]))]
        edited = pd.DataFrame(linhas)
        antes = st.session_state[chave].copy()
        pares = pares_codigo_alterado(antes, edited)
        erro = salvar_disciplinas(edited)
        if erro:
            st.error(erro)
        else:
            avisos_prop = []
            if pares:
                with st.spinner("Atualizando o código nas demais abas da planilha..."):
                    for antigo, novo in pares:
                        avisos_prop.extend(
                            [f"{antigo} → {novo}: {msg}" for msg in propagar_codigo_disciplina(antigo, novo)]
                        )
                        registrar_log(
                            usuario["email"],
                            usuario["nome"],
                            f"Renomeou código da disciplina {antigo} → {novo}",
                        )
            registrar_log(usuario["email"], usuario["nome"], "Atualizou cadastro de disciplinas")
            avisos, pergunta = _pos_salvar_disciplinas(antes, edited, pares_renomeacao=pares)
            st.session_state[chave] = carregar_disciplinas()
            st.session_state[ver_chave] = ver + 1
            if pergunta:
                st.session_state["cad_disc_pergunta_ef"] = pergunta
            if avisos or avisos_prop:
                st.session_state["cad_disc_avisos"] = avisos + avisos_prop
            st.success("Disciplinas salvas na planilha.")
            st.rerun()

    st.caption(
        "Se o código da disciplina mudou no cadastro (ex.: 20263TRI → TRIB) e as presenças "
        "sumiram, alinhe a planilha de frequência."
    )
    if st.button("Alinhar códigos na planilha de presenças", key="cad_disc_alinhar_freq"):
        with st.spinner("Lendo calendários e atualizando IDs antigos…"):
            avisos = alinhar_codigos_frequencia()
        if not avisos:
            st.info("Não encontrei código antigo na planilha de presenças. Os IDs já coincidem com o cadastro.")
        else:
            registrar_log(
                usuario["email"],
                usuario["nome"],
                "Alinhou códigos de disciplina na planilha de presenças",
            )
            st.session_state["cad_disc_avisos"] = avisos
            st.rerun()


def _mapa_status_encontro(df: pd.DataFrame) -> dict[str, tuple[str, str]]:
    mapa = {}
    if df is None or df.empty:
        return mapa
    for _, row in df.iterrows():
        id_disc = normalizar_id(row.get("ID_Disciplina", ""))
        if not id_disc:
            continue
        mapa[id_disc] = (
            str(row.get("Status", "")).strip().lower(),
            str(row.get("Encontro_Presencial", "")).strip(),
        )
    return mapa


def _pos_salvar_disciplinas(
    antes: pd.DataFrame,
    depois: pd.DataFrame,
    pares_renomeacao: list[tuple[str, str]] | None = None,
) -> tuple[list[str], dict | None]:
    avisos: list[str] = []
    mapa_antes = _mapa_status_encontro(antes)
    mapa_depois = _mapa_status_encontro(depois)
    destinos = {novo for _, novo in (pares_renomeacao or [])}
    ids_novos = [i for i in mapa_depois if i not in mapa_antes and i not in destinos]
    ids_para_modelo = list(ids_novos)

    ativos = [i for i, (status, _) in mapa_depois.items() if status == "ativo"]
    for id_disc in ativos:
        if id_disc not in ids_para_modelo:
            ids_para_modelo.append(id_disc)

    for id_disc in ids_para_modelo:
        avisos.extend(garantir_estrutura_padrao(id_disc))

    pergunta = None
    for id_disc, (status, encontro) in mapa_depois.items():
        if status != "ativo" or encontro != "Sim":
            continue
        status_ant, encontro_ant = mapa_antes.get(id_disc, ("", ""))
        virou_ativo_presencial = not (status_ant == "ativo" and encontro_ant == "Sim")
        if not virou_ativo_presencial:
            continue
        if entrega_final_ja_separada(id_disc):
            continue
        nome = ""
        match = depois[depois["ID_Disciplina"].map(normalizar_id) == id_disc]
        if not match.empty:
            nome = str(match.iloc[0]["Nome_Disciplina"]).strip()
        pergunta = {"id": id_disc, "nome": nome or id_disc}
        break
    return avisos, pergunta


def _render_pergunta_entrega_final(usuario: dict) -> bool:
    pendente = st.session_state.get("cad_disc_pergunta_ef")
    if not pendente:
        return False

    id_disc = pendente.get("id", "")
    nome = pendente.get("nome", id_disc)
    st.warning(
        f"A disciplina **{nome}** está ativa e tem encontro presencial. "
        "Antes de continuar, escolha como a **entrega final** entra no boletim."
    )
    st.markdown(
        "- **Sim:** pares, banca e orientador próprios no encontro (ciclo separado).\n"
        "- **Não:** as notas da entrega final são as do último ciclo (em geral o Ciclo 4). "
        "As datas do encontro e o lançamento de presença continuam valendo."
    )
    c1, c2 = st.columns(2)
    if c1.button("Sim, avaliação separada para a entrega final", type="primary"):
        erro = aplicar_decisao_entrega_final(id_disc, True)
        if erro:
            st.error(erro)
        else:
            registrar_log(
                usuario["email"],
                usuario["nome"],
                f"Entrega final com avaliação própria em {id_disc}",
            )
            st.session_state.pop("cad_disc_pergunta_ef", None)
            st.success(
                "Ciclo **Entrega Final** criado e vinculado. "
                "Preencha as datas em Cadastro de ciclos e a janela da banca nas configurações."
            )
            st.rerun()
    if c2.button("Não, reaproveitar o último ciclo"):
        erro = aplicar_decisao_entrega_final(id_disc, False)
        if erro:
            st.error(erro)
        else:
            registrar_log(
                usuario["email"],
                usuario["nome"],
                f"Entrega final reaproveita último ciclo em {id_disc}",
            )
            st.session_state.pop("cad_disc_pergunta_ef", None)
            st.success("Entrega final fica com as mesmas notas do último ciclo.")
            st.rerun()
    return True


def _reset_data_editor_widget(widget_key: str):
    if widget_key in st.session_state:
        del st.session_state[widget_key]


def _render_datas_encontro_card(usuario: dict, id_disc: str, card_idx: int):
    st.markdown("**Datas do encontro presencial**")
    if not id_disc:
        st.caption("Informe e salve o **código** da disciplina antes de cadastrar os dias.")
        return

    st.caption(
        "Use **Adicionar dia** para incluir várias datas de uma vez; salve quando terminar. "
        "Essas datas entram na frequência das aulas e no lançamento manual de presença."
    )
    data_key = f"cad_encontro_datas_df_{id_disc}"
    editor_key = f"editor_encontro_datas_{id_disc}_{card_idx}"
    if data_key not in st.session_state:
        st.session_state[data_key] = normalizar_df_datas_editor(carregar_datas_encontro(id_disc))
        _reset_data_editor_widget(editor_key)

    c_add, _ = st.columns([1, 3])
    if c_add.button("➕ Adicionar dia", key=f"add_enc_day_{id_disc}_{card_idx}"):
        base = normalizar_df_datas_editor(st.session_state[data_key])
        nova = pd.DataFrame([{"Data": None, "Descricao": "", "Ativo": "Sim"}])
        st.session_state[data_key] = pd.concat([base, nova], ignore_index=True)
        _reset_data_editor_widget(editor_key)
        st.rerun()

    edited = st.data_editor(
        st.session_state[data_key],
        column_config={
            "Data": st.column_config.DateColumn(
                "Data",
                format="DD/MM/YYYY",
                help="Obrigatório ao salvar; linhas vazias são ignoradas.",
            ),
            "Descricao": st.column_config.TextColumn("Descrição", help="Ex.: Dia 1 — abertura"),
            "Ativo": st.column_config.SelectboxColumn("Ativo", options=["Sim", "Não"], required=True),
        },
        column_order=["Data", "Descricao", "Ativo"],
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key=editor_key,
    )
    st.session_state[data_key] = normalizar_df_datas_editor(edited)

    if st.button("Salvar datas deste encontro", key=f"save_enc_dates_{id_disc}_{card_idx}"):
        gravar = st.session_state[data_key].copy()
        gravar = gravar[gravar["Data"].notna()]
        if gravar.empty:
            st.error("Informe ao menos uma data antes de salvar.")
            return
        gravar["ID_Disciplina"] = id_disc
        erro = salvar_datas_encontro(gravar, id_disc)
        if erro:
            st.error(erro)
        else:
            registrar_log(usuario["email"], usuario["nome"], f"Atualizou datas do encontro {id_disc}")
            st.session_state[data_key] = carregar_datas_encontro(id_disc)
            _reset_data_editor_widget(editor_key)
            st.success("Datas do encontro salvas.")
            st.rerun()


def _df_ciclos_para_editor(df: pd.DataFrame, filtro: str) -> pd.DataFrame:
    out = normalizar_df_ciclos_editor(df.copy())
    if filtro != "(todas)":
        id_filtro = filtro.split(" — ")[0].strip()
        out = out[out["ID_Disciplina"].astype(str).str.strip() == id_filtro]
        out = out.sort_values("Ordem", na_position="last")
    else:
        out = out.sort_values(["ID_Disciplina", "Ordem"], na_position="last")
    return out.reset_index(drop=True)


def _montar_df_salvar_ciclos(base: pd.DataFrame, edited: pd.DataFrame, filtro: str) -> pd.DataFrame:
    bloco = normalizar_df_ciclos_editor(edited)
    if filtro == "(todas)":
        return bloco
    id_filtro = filtro.split(" — ")[0].strip()
    resto = normalizar_df_ciclos_editor(base)
    resto = resto[resto["ID_Disciplina"].astype(str).str.strip() != id_filtro]
    return normalizar_df_ciclos_editor(pd.concat([resto, bloco], ignore_index=True))


def render_ciclos(usuario: dict):
    st.header("Cadastro de ciclos")
    st.caption(
        "Cada ciclo tem **duas linhas do tempo**. **Início do ciclo** e **Apresentação de projeto** "
        "marcam o período acadêmico (dailies e anotações). **Abertura** e **encerramento das pares** "
        "são a janela em que o aluno avalia os colegas — preencha manualmente. "
        "A coluna **Ordem** vale dentro de cada disciplina (1, 2, 3…). "
        "Status **ativo** ainda entra na avaliação do curso na janela de pares. "
        "Se a disciplina tiver **encontro presencial** e a entrega final for avaliação própria, "
        "cadastre também o ciclo **Entrega Final**.\n\n"
        "Edite a grade abaixo e clique em **Salvar ciclos** ao terminar (as alterações só vão "
        "para a planilha nesse botão)."
    )
    df_disc = carregar_disciplinas()
    ids_disc = _ids_disciplina(df_disc)
    if not ids_disc:
        st.warning("Cadastre ao menos uma disciplina antes dos ciclos.")
        return

    chave = "cad_ciclos_edit_v3"
    ver_ed = "cad_ciclos_editor_ver"
    if chave not in st.session_state:
        st.session_state[chave] = carregar_ciclos()
    elif any(col not in st.session_state[chave].columns for col in COLUNAS_CICLOS):
        st.session_state[chave] = carregar_ciclos()
        st.session_state[ver_ed] = int(st.session_state.get(ver_ed, 0)) + 1
    if ver_ed not in st.session_state:
        st.session_state[ver_ed] = 0

    filtro = st.selectbox(
        "Filtrar por disciplina:",
        ["(todas)"] + [_rotulo_disc(df_disc, i) for i in ids_disc],
        key="cad_ciclo_filtro",
    )
    df_edit = _df_ciclos_para_editor(st.session_state[chave], filtro)
    editor_key = f"editor_ciclos_v3_{filtro}_{st.session_state[ver_ed]}"

    with st.form("cad_ciclos_form", border=False):
        edited = st.data_editor(
            df_edit,
            column_config={
                "ID_Ciclo": st.column_config.TextColumn("ID do ciclo", required=True),
                "Nome_Ciclo": st.column_config.TextColumn("Nome", required=True),
                "ID_Disciplina": st.column_config.SelectboxColumn(
                    "Disciplina", options=ids_disc, required=True
                ),
                "Data_Inicio_Ciclo": st.column_config.DateColumn(
                    "Início do ciclo",
                    format="DD/MM/YYYY",
                    help="Primeiro dia acadêmico deste ciclo (dailies e anotações).",
                ),
                "Data_Apresentacao": st.column_config.DateColumn(
                    "Apresentação de projeto",
                    format="DD/MM/YYYY",
                    help="Término acadêmico do ciclo; em geral a segunda da apresentação.",
                ),
                "Data início": st.column_config.DateColumn(
                    "Abertura das pares",
                    format="DD/MM/YYYY",
                    help="Quando o aluno pode começar a avaliação de pares.",
                ),
                "Data fim": st.column_config.DateColumn(
                    "Encerramento das pares",
                    format="DD/MM/YYYY",
                    help="Último dia da avaliação de pares.",
                ),
                "Status": st.column_config.SelectboxColumn("Status", options=STATUS_OPCOES, required=True),
                "Ordem": st.column_config.NumberColumn(
                    "Ordem na disciplina",
                    min_value=1,
                    step=1,
                    help="Sequência só desta disciplina. Cada disciplina tem o próprio 1, 2, 3…",
                ),
            },
            column_order=[c for c in COLUNAS_CICLOS if c in df_edit.columns],
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            key=editor_key,
        )
        salvar = st.form_submit_button("Salvar ciclos", type="primary", width="stretch")

    if salvar:
        df_save = _montar_df_salvar_ciclos(st.session_state[chave], edited, filtro)
        erro = salvar_ciclos(df_save)
        if erro:
            st.error(erro)
        else:
            registrar_log(usuario["email"], usuario["nome"], "Atualizou cadastro de ciclos")
            st.session_state[chave] = carregar_ciclos()
            st.session_state[ver_ed] = int(st.session_state[ver_ed]) + 1
            _reset_data_editor_widget(editor_key)
            st.success("Ciclos salvos na planilha.")
            st.rerun()

    st.caption(
        "Se o código da disciplina mudou (ex.: 20263TRI → TRIB) e os ciclos não aparecem "
        "na disciplina nova, alinhe os IDs nas abas Ciclos, Avaliações e respostas do curso."
    )
    if st.button("Alinhar códigos antigos nas abas de ciclos e avaliações", key="cad_ciclo_alinhar"):
        with st.spinner("Atualizando IDs antigos nas abas de avaliação…"):
            avisos = alinhar_codigos_ciclos()
        if not avisos:
            st.info("Não encontrei código antigo nos ciclos. Os IDs já coincidem com o cadastro.")
        else:
            registrar_log(
                usuario["email"],
                usuario["nome"],
                "Alinhou códigos de disciplina nas abas de ciclos e avaliações",
            )
            st.session_state[chave] = carregar_ciclos()
            for msg in avisos:
                st.write(f"- {msg}")
            st.success("Códigos alinhados.")


def render_professores(usuario: dict):
    st.header("Cadastro de professores")
    st.caption(
        "Edita a aba **Config_Professores**. Reaproveita disciplina, ciclo, tipo e sala "
        "já preenchidos na planilha. Orientador é filtrado pela **sala** do aluno; "
        "especialista vale para todas as salas do ciclo."
    )
    df_disc = carregar_disciplinas()
    df_ciclos = carregar_ciclos()
    ids_disc = _ids_disciplina(df_disc)
    ids_ciclo = sorted(
        {str(x).strip() for x in df_ciclos["ID_Ciclo"].tolist() if str(x).strip()}
    )
    if not ids_ciclo:
        st.warning("Cadastre ciclos antes de vincular professores.")
        return

    chave = "cad_prof_edit_v2"
    if chave not in st.session_state:
        st.session_state[chave] = carregar_professores()

    c_disc, c_ciclo = st.columns(2)
    filtro_disc = c_disc.selectbox(
        "Filtrar por disciplina:",
        ["(todas)"] + [_rotulo_disc(df_disc, i) for i in ids_disc],
        key="cad_prof_filtro_disc",
    )
    id_disc_filtro = ""
    if filtro_disc != "(todas)":
        id_disc_filtro = filtro_disc.split(" — ")[0].strip()

    ciclos_opcoes = df_ciclos
    if id_disc_filtro:
        ciclos_opcoes = df_ciclos[
            df_ciclos["ID_Disciplina"].astype(str).str.strip() == id_disc_filtro
        ]
    opcoes_ciclo = []
    mapa_ciclo: dict[str, str] = {}
    for _, row in ciclos_opcoes.iterrows():
        cid = str(row["ID_Ciclo"]).strip()
        if not cid:
            continue
        rotulo = f"{cid} — {row.get('Nome_Ciclo', '')}"
        opcoes_ciclo.append(rotulo)
        mapa_ciclo[rotulo] = cid
        mapa_ciclo[cid] = cid

    filtro_ciclo = c_ciclo.selectbox(
        "Filtrar por ciclo:",
        ["(todos)"] + opcoes_ciclo,
        key=f"cad_prof_filtro_ciclo_{id_disc_filtro or 'todas'}",
    )

    df_edit = st.session_state[chave].copy()
    if id_disc_filtro:
        df_edit = df_edit[df_edit["ID_Disciplina"].astype(str).str.strip() == id_disc_filtro]
    if filtro_ciclo != "(todos)":
        id_ciclo_filtro = mapa_ciclo.get(filtro_ciclo, filtro_ciclo.split(" — ")[0].strip())
        df_edit = df_edit[df_edit["ID_Ciclo"].astype(str).str.strip() == id_ciclo_filtro]
    else:
        id_ciclo_filtro = ""

    visiveis = ["ID_Disciplina", "ID_Ciclo", "Professor", "Tipo", "Sala"]
    for col in visiveis:
        if col not in df_edit.columns:
            df_edit[col] = ""
    df_visivel = df_edit[visiveis].copy()

    tipos = list(
        dict.fromkeys(
            TIPOS_PROFESSOR_CONFIG
            + [t for t in df_visivel["Tipo"].astype(str).str.strip() if t]
        )
    )
    edited = st.data_editor(
        df_visivel,
        column_config={
            "ID_Disciplina": st.column_config.SelectboxColumn(
                "Disciplina", options=ids_disc, required=True
            ),
            "ID_Ciclo": st.column_config.SelectboxColumn("Ciclo", options=ids_ciclo, required=True),
            "Professor": st.column_config.TextColumn("Nome do professor", required=True),
            "Tipo": st.column_config.SelectboxColumn("Tipo", options=tipos),
            "Sala": st.column_config.TextColumn("Sala", help="Obrigatório para orientador."),
        },
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key=f"editor_professores_{id_disc_filtro}_{id_ciclo_filtro}",
    )

    if st.button("Salvar professores", type="primary"):
        base = st.session_state[chave].copy()
        if id_ciclo_filtro and id_disc_filtro:
            mesmo_disc = base[base["ID_Disciplina"].astype(str).str.strip() == id_disc_filtro]
            resto = pd.concat(
                [
                    base[base["ID_Disciplina"].astype(str).str.strip() != id_disc_filtro],
                    mesmo_disc[mesmo_disc["ID_Ciclo"].astype(str).str.strip() != id_ciclo_filtro],
                ],
                ignore_index=True,
            )
        elif id_ciclo_filtro:
            resto = base[base["ID_Ciclo"].astype(str).str.strip() != id_ciclo_filtro]
        elif id_disc_filtro:
            resto = base[base["ID_Disciplina"].astype(str).str.strip() != id_disc_filtro]
        else:
            resto = base.iloc[0:0]
        df_save = pd.concat([resto, edited], ignore_index=True)
        erro = salvar_professores(df_save)
        if erro:
            st.error(erro)
        else:
            registrar_log(usuario["email"], usuario["nome"], "Atualizou Config_Professores")
            st.session_state[chave] = carregar_professores()
            st.success("Professores salvos na planilha.")
            st.rerun()
