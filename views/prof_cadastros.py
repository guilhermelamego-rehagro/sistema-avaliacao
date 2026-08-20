"""Cadastros acadêmicos do coordenador: disciplinas, ciclos e professores."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from domain.cadastros import (
    COLUNAS_CICLOS,
    ENCONTRO_OPCOES,
    PAPEIS_DISCIPLINA,
    STATUS_OPCOES,
    carregar_ciclos,
    carregar_disciplinas,
    carregar_professores,
    carregar_professores_disciplina,
    listar_professores_cadastro,
    normalizar_df_ciclos_editor,
    pares_codigo_alterado,
    alinhar_codigos_frequencia,
    alinhar_codigos_ciclos,
    papel_padrao_do_cadastro,
    papel_permite_especialista,
    papel_permite_orientador,
    propagar_codigo_disciplina,
    salas_da_disciplina,
    salvar_ciclos,
    salvar_disciplinas,
    substituir_professores_ciclo,
    substituir_professores_disciplina,
)
from domain.ciclos import ciclos_da_disciplina, ordenar_ciclos
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
from utils.disciplina import id_disciplina_por_nome, indice_disciplina_ativa, normalizar_id
from utils.logs import registrar_log


def _seed(chave: str, valor):
    if chave not in st.session_state:
        st.session_state[chave] = valor


def _seed_opcao(chave: str, valor, opcoes: list[str]):
    if not opcoes:
        return
    atual = st.session_state.get(chave)
    if atual not in opcoes:
        st.session_state[chave] = valor if valor in opcoes else opcoes[0]


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
        "Status **ativo** é obrigatório. **Abertura** e **encerramento das pares** definem "
        "quando a avaliação fica disponível para o aluno. "
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


def _bloco_professores_ciclo(
    df_prof: pd.DataFrame, id_disciplina: str, id_ciclo: str
) -> pd.DataFrame:
    if df_prof is None or df_prof.empty:
        return pd.DataFrame()
    id_disc = normalizar_id(id_disciplina)
    id_cic = normalizar_id(id_ciclo)
    return df_prof[
        (df_prof["ID_Disciplina"].map(normalizar_id) == id_disc)
        & (df_prof["ID_Ciclo"].map(normalizar_id) == id_cic)
    ].copy()


def _mapa_vinculos_ciclo(bloco: pd.DataFrame) -> dict[str, dict]:
    """Chave = e-mail (ou nome em minúsculas se sem e-mail) → papéis no ciclo."""
    mapa: dict[str, dict] = {}
    if bloco is None or bloco.empty:
        return mapa
    for _, row in bloco.iterrows():
        email = str(row.get("Email", "")).strip().lower()
        nome = str(row.get("Professor", "")).strip()
        chave = email or nome.lower()
        if not chave or chave in {"nan", "none"}:
            continue
        info = mapa.setdefault(
            chave,
            {"email": email, "nome": nome, "orientador": False, "sala": "", "especialista": False},
        )
        if nome and not info["nome"]:
            info["nome"] = nome
        if email and not info["email"]:
            info["email"] = email
        tipo = str(row.get("Tipo", "")).strip().title()
        if tipo == "Orientador":
            info["orientador"] = True
            sala = str(row.get("Sala", "")).strip()
            if sala and sala.lower() not in {"nan", "none"}:
                info["sala"] = sala
        elif tipo == "Especialista":
            info["especialista"] = True
    return mapa


def _mapa_pool_disciplina(pool: pd.DataFrame) -> dict[str, dict]:
    mapa: dict[str, dict] = {}
    if pool is None or pool.empty:
        return mapa
    for _, row in pool.iterrows():
        email = str(row.get("Email", "")).strip().lower()
        nome = str(row.get("Professor", "")).strip()
        papel = str(row.get("Papel", "")).strip()
        if not email:
            continue
        mapa[email] = {"email": email, "nome": nome, "papel": papel}
    return mapa


def render_professores(usuario: dict):
    st.header("Cadastro de professores")
    st.caption(
        "1) Em **Professores desta disciplina** (recolhido), associe quem pode atuar e o papel. "
        "2) Nos **ciclos**, só aparecem esses professores. "
        "Orientador exige sala; especialista vale para todas as salas."
    )
    df_disc = carregar_disciplinas()
    if df_disc.empty:
        st.warning("Cadastre disciplinas antes de vincular professores.")
        return
    df_ciclos = carregar_ciclos()
    cadastro = listar_professores_cadastro()
    df_prof = carregar_professores()

    lista_disc = [
        str(n).strip()
        for n in df_disc["Nome_Disciplina"].tolist()
        if str(n).strip() and str(n).strip().lower() not in {"nan", "none"}
    ]
    lista_disc = list(dict.fromkeys(lista_disc))
    if not lista_disc:
        st.warning("Nenhuma disciplina com nome cadastrado.")
        return
    nome_disc = st.selectbox(
        "Disciplina:",
        lista_disc,
        index=indice_disciplina_ativa(df_disc, lista_disc),
        key="cad_prof_disc",
    )
    id_disc = normalizar_id(id_disciplina_por_nome(df_disc, nome_disc))
    pool = carregar_professores_disciplina(id_disc)
    pool_mapa = _mapa_pool_disciplina(pool)

    if cadastro.empty:
        st.warning(
            "Não há professores no cadastro (Base_Alunos com perfil Professor). "
            "Cadastre-os antes de associar à disciplina."
        )

    n_pool = len(pool_mapa)
    titulo_pool = (
        f"Professores desta disciplina · {n_pool} vinculado(s)"
        if n_pool
        else "Professores desta disciplina · nenhum vinculado"
    )
    with st.expander(titulo_pool, expanded=False):
        st.caption(
            "Associação feita normalmente uma vez no semestre. "
            "Marque quem pode atuar e o papel (Orientador, Especialista ou Ambos). "
            "Depois, edite os vínculos em cada ciclo."
        )
        if cadastro.empty:
            st.info("Sem professores no cadastro para montar o pool.")
        else:
            for _, p in cadastro.iterrows():
                email = str(p["Email"]).strip().lower()
                nome = str(p["Nome"]).strip()
                tipo_cad = str(p.get("Tipo_Cadastro", "")).strip()
                atual = pool_mapa.get(email)
                k_chk = f"cad_prof_pool_{id_disc}_{email}"
                k_papel = f"cad_prof_papel_{id_disc}_{email}"
                _seed(k_chk, atual is not None)
                papel_sug = (
                    atual["papel"]
                    if atual and atual.get("papel") in PAPEIS_DISCIPLINA
                    else papel_padrao_do_cadastro(tipo_cad)
                )
                _seed_opcao(k_papel, papel_sug, PAPEIS_DISCIPLINA)
                c1, c2 = st.columns([3, 2])
                rotulo = nome if not tipo_cad else f"{nome} (cadastro: {tipo_cad})"
                c1.checkbox(rotulo, key=k_chk)
                c2.selectbox(
                    "Papel na disciplina",
                    PAPEIS_DISCIPLINA,
                    key=k_papel,
                    label_visibility="collapsed",
                )

            if st.button(
                "Salvar professores da disciplina",
                type="primary",
                key=f"cad_prof_pool_salvar_{id_disc}",
            ):
                linhas = []
                for _, p in cadastro.iterrows():
                    email = str(p["Email"]).strip().lower()
                    nome = str(p["Nome"]).strip()
                    if not st.session_state.get(f"cad_prof_pool_{id_disc}_{email}"):
                        continue
                    papel = str(st.session_state.get(f"cad_prof_papel_{id_disc}_{email}", "")).strip()
                    if papel not in PAPEIS_DISCIPLINA:
                        st.error(f"Papel inválido para {nome}.")
                        return
                    linhas.append(
                        {
                            "Disciplina": nome_disc,
                            "ID_Disciplina": id_disc,
                            "Professor": nome,
                            "Email": email,
                            "Papel": papel,
                        }
                    )
                with st.spinner("Salvando pool da disciplina…"):
                    erro = substituir_professores_disciplina(id_disc, nome_disc, linhas)
                if erro:
                    st.error(erro)
                else:
                    registrar_log(
                        usuario["email"],
                        usuario["nome"],
                        f"Atualizou professores da disciplina {id_disc}",
                    )
                    st.success(
                        f"Pool da disciplina salvo ({len(linhas)} professor(es)). "
                        "Vínculos de ciclo incompatíveis com o novo papel foram alinhados."
                    )
                    st.rerun()

    if pool.empty:
        st.info("Associe ao menos um professor à disciplina para configurar os ciclos.")
        return

    st.subheader("Vínculos por ciclo")
    ciclos = ordenar_ciclos(ciclos_da_disciplina(df_ciclos, id_disc))
    if ciclos.empty:
        st.warning("Esta disciplina ainda não tem ciclos cadastrados.")
        return

    salas = salas_da_disciplina(id_disc)
    if not salas:
        st.info(
            "Nenhuma sala encontrada na entrância desta disciplina. "
            "Cadastre salas na entrância para vincular orientadores."
        )

    emails_pool = set(pool_mapa.keys())
    candidatos_ori = [
        info for info in pool_mapa.values() if papel_permite_orientador(info.get("papel", ""))
    ]
    candidatos_esp = [
        info for info in pool_mapa.values() if papel_permite_especialista(info.get("papel", ""))
    ]
    candidatos_ori = sorted(candidatos_ori, key=lambda x: x.get("nome", "").lower())
    candidatos_esp = sorted(candidatos_esp, key=lambda x: x.get("nome", "").lower())

    for _, ciclo in ciclos.iterrows():
        id_ciclo = normalizar_id(ciclo.get("ID_Ciclo", ""))
        nome_ciclo = str(ciclo.get("Nome_Ciclo", "")).strip() or id_ciclo
        if not id_ciclo:
            continue
        bloco = _bloco_professores_ciclo(df_prof, id_disc, id_ciclo)
        vinculos = _mapa_vinculos_ciclo(bloco)
        emails_vinculados = {v["email"] for v in vinculos.values() if v.get("email")}
        nomes_vinculados = {
            str(v.get("nome", "")).strip().lower()
            for v in vinculos.values()
            if str(v.get("nome", "")).strip()
        }

        pendentes = []
        for info in pool_mapa.values():
            email = info["email"]
            nome = str(info.get("nome", "")).strip().lower()
            if email in emails_vinculados or nome in nomes_vinculados:
                continue
            pendentes.append(str(info.get("nome") or email).strip())

        n_ori = sum(1 for v in vinculos.values() if v.get("orientador"))
        n_esp = sum(1 for v in vinculos.values() if v.get("especialista"))
        titulo = f"{nome_ciclo} · {n_ori} orientador(es) · {n_esp} especialista(s)"
        if pendentes:
            titulo = f"{titulo} · {len(pendentes)} pendente(s)"

        with st.expander(titulo, expanded=False):
            if pendentes:
                st.caption(
                    "Pendentes neste ciclo (no pool da disciplina, ainda sem vínculo): "
                    + ", ".join(pendentes)
                )
            else:
                st.caption("Todos os professores do pool já têm vínculo neste ciclo.")

            orfaos = []
            for chave, info in vinculos.items():
                email = str(info.get("email") or "").strip().lower()
                if email and email in emails_pool:
                    continue
                orfaos.append(info)

            st.markdown("**Orientadores** (obrigatório informar a sala)")
            if not candidatos_ori and not orfaos:
                st.caption("Nenhum professor com papel Orientador/Ambos nesta disciplina.")
            else:
                for p in candidatos_ori:
                    email = p["email"]
                    nome = p["nome"]
                    info = vinculos.get(email) or vinculos.get(nome.lower()) or {}
                    k_chk = f"cad_prof_ori_{id_disc}_{id_ciclo}_{email}"
                    k_sala = f"cad_prof_sala_{id_disc}_{id_ciclo}_{email}"
                    _seed(k_chk, bool(info.get("orientador")))
                    sala_atual = str(info.get("sala") or "")
                    opcoes_sala = list(salas)
                    if sala_atual and sala_atual not in opcoes_sala:
                        opcoes_sala = [sala_atual] + opcoes_sala
                    if not opcoes_sala:
                        opcoes_sala = [sala_atual] if sala_atual else [""]
                    _seed_opcao(
                        k_sala,
                        sala_atual if sala_atual in opcoes_sala else opcoes_sala[0],
                        opcoes_sala,
                    )
                    c1, c2 = st.columns([3, 2])
                    c1.checkbox(nome, key=k_chk)
                    c2.selectbox(
                        "Sala",
                        opcoes_sala,
                        key=k_sala,
                        label_visibility="collapsed",
                        disabled=not opcoes_sala or opcoes_sala == [""],
                    )
                for info in orfaos:
                    if not info.get("orientador"):
                        continue
                    email = str(info.get("email") or "").strip().lower()
                    nome = str(info.get("nome") or "").strip() or email or "Sem nome"
                    chave = email or nome.lower()
                    k_chk = f"cad_prof_ori_{id_disc}_{id_ciclo}_{chave}"
                    k_sala = f"cad_prof_sala_{id_disc}_{id_ciclo}_{chave}"
                    _seed(k_chk, True)
                    sala_atual = str(info.get("sala") or "")
                    opcoes_sala = list(salas)
                    if sala_atual and sala_atual not in opcoes_sala:
                        opcoes_sala = [sala_atual] + opcoes_sala
                    if not opcoes_sala:
                        opcoes_sala = [sala_atual] if sala_atual else [""]
                    _seed_opcao(
                        k_sala,
                        sala_atual if sala_atual in opcoes_sala else opcoes_sala[0],
                        opcoes_sala,
                    )
                    c1, c2 = st.columns([3, 2])
                    c1.checkbox(f"{nome} (fora do pool)", key=k_chk)
                    c2.selectbox(
                        "Sala",
                        opcoes_sala,
                        key=k_sala,
                        label_visibility="collapsed",
                        disabled=not opcoes_sala or opcoes_sala == [""],
                    )

            st.markdown("**Especialistas** (todas as salas)")
            if not candidatos_esp and not any(o.get("especialista") for o in orfaos):
                st.caption("Nenhum professor com papel Especialista/Ambos nesta disciplina.")
            else:
                for p in candidatos_esp:
                    email = p["email"]
                    nome = p["nome"]
                    info = vinculos.get(email) or vinculos.get(nome.lower()) or {}
                    k_chk = f"cad_prof_esp_{id_disc}_{id_ciclo}_{email}"
                    _seed(k_chk, bool(info.get("especialista")))
                    st.checkbox(nome, key=k_chk)
                for info in orfaos:
                    if not info.get("especialista"):
                        continue
                    email = str(info.get("email") or "").strip().lower()
                    nome = str(info.get("nome") or "").strip() or email or "Sem nome"
                    chave = email or nome.lower()
                    k_chk = f"cad_prof_esp_{id_disc}_{id_ciclo}_{chave}"
                    _seed(k_chk, True)
                    st.checkbox(f"{nome} (fora do pool)", key=k_chk)

            if st.button(
                f"Salvar vínculos — {nome_ciclo}",
                type="primary",
                key=f"cad_prof_salvar_{id_disc}_{id_ciclo}",
            ):
                linhas = []
                candidatos = []
                vistos = set()
                for p in candidatos_ori + candidatos_esp:
                    email = p["email"]
                    if email in vistos:
                        continue
                    vistos.add(email)
                    candidatos.append({"email": email, "nome": p["nome"], "chave": email})
                for info in orfaos:
                    email = str(info.get("email") or "").strip().lower()
                    nome = str(info.get("nome") or "").strip()
                    chave = email or nome.lower()
                    if chave in vistos:
                        continue
                    vistos.add(chave)
                    candidatos.append({"email": email, "nome": nome, "chave": chave})

                for c in candidatos:
                    email = c["email"]
                    nome = c["nome"]
                    chave = c.get("chave") or email or nome.lower()
                    if st.session_state.get(f"cad_prof_ori_{id_disc}_{id_ciclo}_{chave}"):
                        sala = str(
                            st.session_state.get(f"cad_prof_sala_{id_disc}_{id_ciclo}_{chave}", "")
                        ).strip()
                        if sala.lower() in {"", "nan", "none", "nat"}:
                            st.error(
                                f"Informe a sala do orientador **{nome}**. "
                                "Se a lista de salas estiver vazia, cadastre a entrância da disciplina."
                            )
                            return
                        linhas.append(
                            {
                                "Disciplina": nome_disc,
                                "Ciclo": nome_ciclo,
                                "ID_Disciplina": id_disc,
                                "ID_Ciclo": id_ciclo,
                                "Professor": nome,
                                "Email": email,
                                "Tipo": "Orientador",
                                "Sala": sala,
                            }
                        )
                    if st.session_state.get(f"cad_prof_esp_{id_disc}_{id_ciclo}_{chave}"):
                        linhas.append(
                            {
                                "Disciplina": nome_disc,
                                "Ciclo": nome_ciclo,
                                "ID_Disciplina": id_disc,
                                "ID_Ciclo": id_ciclo,
                                "Professor": nome,
                                "Email": email,
                                "Tipo": "Especialista",
                                "Sala": "",
                            }
                        )

                with st.spinner("Salvando vínculos…"):
                    erro = substituir_professores_ciclo(id_disc, id_ciclo, linhas)
                if erro:
                    st.error(erro)
                else:
                    registrar_log(
                        usuario["email"],
                        usuario["nome"],
                        f"Atualizou professores do ciclo {id_ciclo} ({id_disc})",
                    )
                    st.success(f"Vínculos do ciclo **{nome_ciclo}** salvos.")
                    st.rerun()
