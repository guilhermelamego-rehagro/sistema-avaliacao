"""Planejamento acadêmico: matriz, carrosséis, turmas e ofertas."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from domain.cadastros import carregar_disciplinas
from domain.planejamento import (
    COLUNAS_ITENS,
    ENCONTRO_OPCOES,
    NUMEROS_TRIMESTRE,
    STATUS_CARROSSEL,
    STATUS_MATRIZ,
    STATUS_OFERTA,
    STATUS_TRIMESTRE,
    STATUS_TURMA,
    TIPO_EXCECAO,
    TIPO_OFERTA,
    carregar_alunos_base,
    carregar_carrosseis,
    carregar_carrossel_itens,
    carregar_excecoes,
    carregar_matriz_itens,
    carregar_matrizes,
    carregar_oferta_turmas,
    carregar_ofertas,
    carregar_trimestres,
    carregar_turmas,
    carrossel_tem_ordem_propria,
    codigo_trimestre,
    criar_matriz_das_disciplinas,
    duplicar_matriz,
    encontro_sugerido_oferta,
    gerar_trimestres_do_ano,
    id_oferta_sugerido,
    importar_turmas_da_base,
    padronizar_nomenclatura_turmas,
    itens_da_matriz,
    nome_disciplina,
    normalizar_codigo_turma,
    normalizar_id_trimestre,
    parse_id_trimestre,
    proximo_id,
    remover_carrossel,
    remover_excecao,
    remover_matriz,
    remover_oferta,
    remover_turma,
    resumo_participantes,
    rotulo_disciplina,
    rotulo_trimestre,
    salvar_carrossel,
    salvar_excecao,
    salvar_matriz,
    salvar_oferta,
    salvar_trimestres,
    salvar_turma,
    sequencia_volta,
    trimestre_por_id,
    trilha_posicao,
    turmas_da_oferta,
)
from utils.disciplina import normalizar_id
from utils.logs import registrar_log


def _avisos():
    for msg in st.session_state.pop("pln_ok", []):
        st.success(msg)
    for msg in st.session_state.pop("pln_erro", []):
        st.error(msg)
    for msg in st.session_state.pop("pln_info", []):
        st.info(msg)


def _ok(msg: str):
    st.session_state.setdefault("pln_ok", []).append(msg)


def _erro(msg: str):
    st.session_state.setdefault("pln_erro", []).append(msg)


def _info(msg: str):
    st.session_state.setdefault("pln_info", []).append(msg)


def _bump(chave: str):
    st.session_state[chave] = int(st.session_state.get(chave, 0)) + 1


def _seed(chave: str, valor):
    if chave not in st.session_state:
        st.session_state[chave] = valor


def _seed_opcao(chave: str, valor, opcoes: list[str]):
    if not opcoes:
        return
    atual = st.session_state.get(chave)
    if atual not in opcoes:
        st.session_state[chave] = valor if valor in opcoes else opcoes[0]


def _opcoes_matriz(matrizes: pd.DataFrame) -> list[str]:
    opcoes = []
    for _, row in matrizes.iterrows():
        mid = normalizar_id(row["ID_Matriz"])
        if not mid:
            continue
        nome = str(row.get("Nome", "")).strip()
        ver = row.get("Versao", "")
        status = str(row.get("Status", "")).strip()
        rotulo = f"{mid} — {nome}" if nome else mid
        extras = []
        if ver not in ("", None):
            extras.append(f"v{ver}")
        if status:
            extras.append(status)
        if extras:
            rotulo = f"{rotulo} ({' · '.join(extras)})"
        opcoes.append(rotulo)
    return opcoes


def _id_de_rotulo(rotulo: str) -> str:
    return str(rotulo or "").split(" — ")[0].strip()


def _opcoes_posicao_seq(bloco: pd.DataFrame, discs: pd.DataFrame) -> list[tuple[int, str]]:
    saida = []
    if bloco is None or bloco.empty:
        return saida
    for _, row in bloco.sort_values("Ordem").iterrows():
        if pd.isna(row.get("Ordem")):
            continue
        ordem = int(row["Ordem"])
        id_disc = normalizar_id(row["ID_Disciplina"])
        enc = str(row.get("Encontro_Presencial_Sugerido", "Não"))
        extra = " · presencial" if enc == "Sim" else ""
        saida.append((ordem, f"{ordem} — {rotulo_disciplina(discs, id_disc)}{extra}"))
    return saida


def render(usuario: dict):
    st.header("Planejamento acadêmico")
    st.caption(
        "Cadastro da **matriz** (versão do currículo), dos **trimestres**, dos **carrosséis**, "
        "das **turmas** e das **ofertas**. Associar uma turma puxa os alunos ativos dela; "
        "exceções desvinculam ou incluem alguém pontualmente. "
        "O portal dos alunos **continua** usando a disciplina ativa e a Entrância — "
        "notas, ciclos e grupos não mudam nesta tela."
    )
    _avisos()

    discs = carregar_disciplinas()
    if discs.empty:
        st.warning("Cadastre disciplinas (menu Cadastro de disciplinas) antes de montar a matriz.")
        return

    secao = st.radio(
        "Seção",
        ["Matriz", "Trimestres", "Carrosséis", "Turmas", "Ofertas"],
        horizontal=True,
        key="pln_secao",
    )
    if secao == "Matriz":
        _render_matrizes(usuario, discs)
    elif secao == "Trimestres":
        _render_trimestres(usuario)
    elif secao == "Carrosséis":
        _render_carrosseis(usuario, discs)
    elif secao == "Turmas":
        _render_turmas(usuario, discs)
    else:
        _render_ofertas(usuario, discs)


def _render_matrizes(usuario: dict, discs: pd.DataFrame):
    st.subheader("Versões da matriz")
    st.caption(
        "A matriz é o **conjunto** e a ordem-padrão das disciplinas. Cada **versão** tem um nome "
        "(ex.: **Matriz GGA 2024**). Se mudar **quais** disciplinas entram (ex.: de 10 para 12), "
        "crie outra versão. Ordem diferente das **mesmas** disciplinas (caso da T04) se resolve no carrossel. "
        "Posições ímpares sugerem meio de semestre (sem encontro presencial); pares, fim de semestre."
    )
    chave = "pln_mat_df"
    ver_chave = "pln_mat_ver"
    if ver_chave not in st.session_state:
        st.session_state[ver_chave] = 0
    ver = int(st.session_state[ver_chave])
    if chave not in st.session_state:
        st.session_state[chave] = carregar_matrizes()
    df = st.session_state[chave].copy()
    itens = carregar_matriz_itens()

    _seed("pln_mat_nome_nova", "Matriz GGA 2024")
    st.text_input(
        "Nome da versão (para criar a partir das disciplinas)",
        key="pln_mat_nome_nova",
        placeholder="Ex.: Matriz GGA 2024",
    )
    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("Criar a partir das disciplinas cadastradas", width="stretch"):
        erro, novo_id = criar_matriz_das_disciplinas(st.session_state.get("pln_mat_nome_nova", ""))
        if erro:
            st.error(erro)
        else:
            registrar_log(usuario["email"], usuario["nome"], f"Criou matriz {novo_id} a partir das disciplinas")
            st.session_state[chave] = carregar_matrizes()
            _bump(ver_chave)
            _ok(f"Matriz {novo_id} criada. Ajuste a ordem se a sequência do carrossel for outra.")
            st.rerun()
    if c2.button("Nova matriz em branco", width="stretch"):
        novo = pd.DataFrame(
            [{"ID_Matriz": "", "Nome": "", "Versao": "", "Status": "inativa", "Observacao": ""}]
        )
        st.session_state[chave] = pd.concat([df, novo], ignore_index=True)
        _bump(ver_chave)
        st.rerun()

    if df.empty:
        st.info("Nenhuma matriz ainda. Use **Criar a partir das disciplinas cadastradas** para a versão atual.")
        return

    ids_disc = [normalizar_id(x) for x in discs["ID_Disciplina"].tolist() if normalizar_id(x)]
    rotulos_disc = {i: rotulo_disciplina(discs, i) for i in ids_disc}

    for idx, row in df.iterrows():
        id_atual = normalizar_id(row.get("ID_Matriz", ""))
        nome_atual = str(row.get("Nome", "")).strip() or "Nova matriz"
        status_atual = str(row.get("Status", "inativa")).strip()
        ver_atual = row.get("Versao", "")
        n_itens = 0 if not id_atual else len(itens_da_matriz(id_atual, itens))
        extras = [status_atual]
        if ver_atual not in ("", None):
            extras.insert(0, f"v{ver_atual}")
        extras.append(f"{n_itens} disciplinas")
        titulo = f"{id_atual or '—'} — {nome_atual} ({' · '.join(extras)})"

        with st.expander(titulo, expanded=status_atual == "vigente" and n_itens == 0):
            k = f"{idx}_{ver}"
            _seed(f"mat_id_{k}", id_atual)
            _seed(f"mat_nome_{k}", str(row.get("Nome", "")))
            _seed(f"mat_ver_{k}", int(ver_atual) if str(ver_atual).isdigit() else 1)
            _seed(f"mat_status_{k}", status_atual if status_atual in STATUS_MATRIZ else "inativa")
            _seed(f"mat_obs_{k}", str(row.get("Observacao", "")).replace("nan", ""))

            a, b, c = st.columns([2, 1, 1])
            a.text_input("Código", key=f"mat_id_{k}", placeholder="Ex.: MX1")
            b.number_input("Versão", min_value=1, step=1, key=f"mat_ver_{k}")
            c.selectbox("Status", STATUS_MATRIZ, key=f"mat_status_{k}")
            st.text_input(
                "Nome da versão",
                key=f"mat_nome_{k}",
                placeholder="Ex.: Matriz GGA 2024",
            )
            st.text_input("Observação", key=f"mat_obs_{k}")

            bloco = itens_da_matriz(id_atual, itens) if id_atual else pd.DataFrame(columns=COLUNAS_ITENS)
            visivel = bloco[["Ordem", "ID_Disciplina", "Encontro_Presencial_Sugerido"]].copy()
            if visivel.empty:
                visivel = pd.DataFrame(
                    {
                        "Ordem": pd.Series(dtype="Int64"),
                        "ID_Disciplina": pd.Series(dtype=str),
                        "Encontro_Presencial_Sugerido": pd.Series(dtype=str),
                    }
                )
            visivel["ID_Disciplina"] = visivel["ID_Disciplina"].map(
                lambda x: rotulos_disc.get(normalizar_id(x), rotulo_disciplina(discs, x))
            )
            opcoes_itens = list(dict.fromkeys([rotulos_disc[i] for i in ids_disc] + visivel["ID_Disciplina"].astype(str).tolist()))
            opcoes_itens = [o for o in opcoes_itens if o and o != "nan"]
            edited = st.data_editor(
                visivel,
                column_config={
                    "Ordem": st.column_config.NumberColumn("Ordem", min_value=1, step=1),
                    "ID_Disciplina": st.column_config.SelectboxColumn(
                        "Disciplina", options=opcoes_itens, required=True
                    ),
                    "Encontro_Presencial_Sugerido": st.column_config.SelectboxColumn(
                        "Encontro presencial (sugestão)",
                        options=list(ENCONTRO_OPCOES),
                        help="Herdado pela oferta; pode ser alterado em cada oferta.",
                    ),
                },
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                key=f"editor_mat_itens_{k}",
            )

            b1, b2, b3 = st.columns(3)
            if b1.button("Salvar matriz", type="primary", key=f"mat_save_{k}", width="stretch"):
                id_salvar = normalizar_id(st.session_state.get(f"mat_id_{k}", "")) or proximo_id(
                    carregar_matrizes()["ID_Matriz"], "MX"
                )
                itens_save = edited.copy()
                itens_save["ID_Disciplina"] = itens_save["ID_Disciplina"].map(_id_de_rotulo)
                itens_save["ID_Matriz"] = id_salvar
                if "Ordem" not in itens_save.columns:
                    itens_save["Ordem"] = range(1, len(itens_save) + 1)
                erro = salvar_matriz(
                    {
                        "ID_Matriz": id_salvar,
                        "Nome": st.session_state.get(f"mat_nome_{k}", ""),
                        "Versao": st.session_state.get(f"mat_ver_{k}", 1),
                        "Status": st.session_state.get(f"mat_status_{k}", "inativa"),
                        "Observacao": st.session_state.get(f"mat_obs_{k}", ""),
                    },
                    itens_save,
                )
                if erro:
                    st.error(erro)
                else:
                    registrar_log(usuario["email"], usuario["nome"], f"Salvou matriz {id_salvar}")
                    st.session_state[chave] = carregar_matrizes()
                    _bump(ver_chave)
                    _ok(f"Matriz {id_salvar} salva.")
                    st.rerun()
            if id_atual and b2.button("Nova versão a partir desta", key=f"mat_dup_{k}", width="stretch"):
                erro, novo_id = duplicar_matriz(id_atual)
                if erro:
                    st.error(erro)
                else:
                    registrar_log(usuario["email"], usuario["nome"], f"Duplicou matriz {id_atual} → {novo_id}")
                    st.session_state[chave] = carregar_matrizes()
                    _bump(ver_chave)
                    _ok(f"Versão {novo_id} criada como inativa. Edite o nome e a ordem e torne vigente quando for o caso.")
                    st.rerun()
            if b3.button("Remover matriz", key=f"mat_del_{k}", width="stretch"):
                if not id_atual:
                    restante = st.session_state[chave].drop(index=idx).reset_index(drop=True)
                    st.session_state[chave] = restante
                    _bump(ver_chave)
                    st.rerun()
                erro = remover_matriz(id_atual)
                if erro:
                    st.error(erro)
                else:
                    registrar_log(usuario["email"], usuario["nome"], f"Removeu matriz {id_atual}")
                    st.session_state[chave] = carregar_matrizes()
                    _bump(ver_chave)
                    _ok(f"Matriz {id_atual} removida.")
                    st.rerun()


def _rotulo_trimestre_oferta(row) -> str:
    """Rótulo legível do trimestre (sem repetir código interno e nome)."""
    id_tri = normalizar_id(row.get("ID_Trimestre", "")).replace("/", "-")
    ano, num = parse_id_trimestre(id_tri)
    if not (ano and num):
        ano = str(row.get("Ano", "")).strip()
        num = str(row.get("Numero", "")).strip()
    titulo = rotulo_trimestre(ano, num) if ano and num else str(row.get("Nome", "")).strip()
    status = str(row.get("Status", "")).strip()
    ini = row.get("Data_Inicio")
    fim = row.get("Data_Fim")
    extra = []
    if ini:
        extra.append(pd.Timestamp(ini).strftime("%d/%m/%Y") if not isinstance(ini, str) else str(ini))
    if fim:
        extra.append(pd.Timestamp(fim).strftime("%d/%m/%Y") if not isinstance(fim, str) else str(fim))
    rotulo = titulo
    if status:
        rotulo = f"{rotulo} · {status}"
    if extra:
        rotulo = f"{rotulo} ({' a '.join(extra)})"
    return rotulo


def _opcoes_trimestre(trimestres: pd.DataFrame) -> list[str]:
    return [_rotulo_trimestre_oferta(row) for _, row in trimestres.iterrows()]


def _id_trimestre_de_rotulo(rotulo: str, trimestres: pd.DataFrame) -> str:
    alvo = str(rotulo or "").strip()
    for _, row in trimestres.iterrows():
        if _rotulo_trimestre_oferta(row) == alvo:
            return normalizar_id(row["ID_Trimestre"]).replace("/", "-")
    prefixo = alvo.split(" · ", 1)[0].strip()
    if "/" in prefixo:
        ano, num = prefixo.split("/", 1)
        return codigo_trimestre(ano, num)
    return _id_de_rotulo(alvo).replace("/", "-")


def _render_trimestres(usuario: dict):
    st.subheader("Trimestres acadêmicos")
    st.caption(
        "O ano letivo tem **4 trimestres**: 2026/1, 2026/2, 2026/3 e 2026/4; no ano seguinte, 2027/1. "
        "Aqui ficam as datas de início e término das aulas. A oferta da disciplina aponta para um "
        "destes trimestres. As datas reais dos ciclos continuam no cadastro de ciclos."
    )
    chave = "pln_tri_df"
    if chave not in st.session_state:
        st.session_state[chave] = carregar_trimestres()
    df = st.session_state[chave].copy()

    c1, c2, _ = st.columns([1, 1, 2])
    _seed("pln_tri_ano_novo", 2026)
    c1.number_input("Ano para gerar", min_value=2020, max_value=2040, step=1, key="pln_tri_ano_novo")
    if c2.button("Gerar 4 trimestres do ano", width="stretch"):
        erro, n = gerar_trimestres_do_ano(int(st.session_state["pln_tri_ano_novo"]))
        if erro:
            st.error(erro)
        else:
            registrar_log(
                usuario["email"],
                usuario["nome"],
                f"Gerou trimestres de {st.session_state['pln_tri_ano_novo']}",
            )
            st.session_state[chave] = carregar_trimestres()
            if n:
                _ok(f"{n} trimestre(s) criado(s). Preencha as datas de aula e salve.")
            else:
                _info("Os 4 trimestres desse ano já existiam.")
            st.rerun()

    visivel = df[["Nome", "Ano", "Numero", "Data_Inicio", "Data_Fim", "Status"]].copy()
    if visivel.empty:
        visivel = pd.DataFrame(
            {
                "Nome": pd.Series(dtype=str),
                "Ano": pd.Series(dtype="Int64"),
                "Numero": pd.Series(dtype=str),
                "Data_Inicio": pd.Series(dtype="object"),
                "Data_Fim": pd.Series(dtype="object"),
                "Status": pd.Series(dtype=str),
            }
        )
    else:
        visivel["Numero"] = visivel["Numero"].map(
            lambda v: str(int(v)) if str(v).strip() not in {"", "nan", "None"} else ""
        )
    edited = st.data_editor(
        visivel,
        column_config={
            "Nome": st.column_config.TextColumn("Nome", help="Como aparece na oferta. Ex.: 2026/1"),
            "Ano": st.column_config.NumberColumn("Ano", min_value=2020, max_value=2040, step=1),
            "Numero": st.column_config.SelectboxColumn("Trimestre", options=NUMEROS_TRIMESTRE),
            "Data_Inicio": st.column_config.DateColumn("Início das aulas", format="DD/MM/YYYY"),
            "Data_Fim": st.column_config.DateColumn("Término das aulas", format="DD/MM/YYYY"),
            "Status": st.column_config.SelectboxColumn("Status", options=STATUS_TRIMESTRE),
        },
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key="editor_trimestres",
    )
    if st.button("Salvar trimestres", type="primary"):
        erro = salvar_trimestres(edited)
        if erro:
            st.error(erro)
        else:
            registrar_log(usuario["email"], usuario["nome"], "Atualizou trimestres acadêmicos")
            st.session_state[chave] = carregar_trimestres()
            _ok("Trimestres salvos.")
            st.rerun()


def _render_carrosseis(usuario: dict, discs: pd.DataFrame):
    st.subheader("Carrosséis")
    st.caption(
        "Um carrossel é a matriz **rodando no calendário**: um trimestre, uma posição. "
        "Turmas na **mesma volta** compartilham esta ordem e embarcam em pontos diferentes. "
        "Quem entra na última disciplina tem ela como 1ª e a primeira da volta como 2ª. "
        "Um segundo carrossel entra se a **ordem** for outra (ex.: T04 na passagem de 10 para 12) "
        "ou se vocês ligarem outra volta no mesmo trimestre. "
        "Nomeie pela matriz e pelo início (ex.: Matriz 2024 · início Avaliação Fiscal)."
    )
    matrizes = carregar_matrizes()
    if matrizes.empty:
        st.info("Crie uma matriz na aba anterior antes dos carrosséis.")
        return
    itens_matriz = carregar_matriz_itens()
    itens_carr = carregar_carrossel_itens()
    chave = "pln_carr_df"
    ver_chave = "pln_carr_ver"
    if ver_chave not in st.session_state:
        st.session_state[ver_chave] = 0
    ver = int(st.session_state[ver_chave])
    if chave not in st.session_state:
        st.session_state[chave] = carregar_carrosseis()
    df = st.session_state[chave].copy()

    if st.button("Novo carrossel", key="carr_novo"):
        novo = pd.DataFrame(
            [
                {
                    "ID_Carrossel": "",
                    "Nome": "",
                    "ID_Matriz": "",
                    "Posicao_Inicio": 1,
                    "Data_Inicio": None,
                    "Status": "ativo",
                }
            ]
        )
        st.session_state[chave] = pd.concat([df, novo], ignore_index=True)
        _bump(ver_chave)
        st.rerun()

    if df.empty:
        st.info("Nenhum carrossel cadastrado.")
        return

    opcoes_mat = _opcoes_matriz(matrizes)
    mapa_mat = {_id_de_rotulo(r): r for r in opcoes_mat}

    for idx, row in df.iterrows():
        k = f"{idx}_{ver}"
        id_atual = normalizar_id(row.get("ID_Carrossel", ""))
        nome_atual = str(row.get("Nome", "")).strip() or "Novo carrossel"
        status_atual = str(row.get("Status", "ativo"))
        with st.expander(f"{id_atual or '—'} — {nome_atual} ({status_atual})", expanded=not id_atual):
            _seed(f"carr_id_{k}", id_atual)
            _seed(f"carr_nome_{k}", str(row.get("Nome", "")).replace("nan", ""))
            id_mat_row = normalizar_id(row.get("ID_Matriz", ""))
            rotulo_mat_padrao = mapa_mat.get(id_mat_row, opcoes_mat[0] if opcoes_mat else "")
            _seed_opcao(f"carr_mat_{k}", rotulo_mat_padrao, opcoes_mat)
            _seed(f"carr_status_{k}", status_atual if status_atual in STATUS_CARROSSEL else "ativo")
            data_ini = row.get("Data_Inicio")
            _seed(f"carr_temdata_{k}", data_ini is not None and str(data_ini) not in {"", "NaT", "None"})
            if st.session_state.get(f"carr_temdata_{k}") and data_ini is not None:
                _seed(f"carr_data_{k}", data_ini)

            a, b = st.columns(2)
            a.text_input("Código", key=f"carr_id_{k}", placeholder="Ex.: CR1")
            b.selectbox("Status", STATUS_CARROSSEL, key=f"carr_status_{k}")
            st.text_input(
                "Nome",
                key=f"carr_nome_{k}",
                placeholder="Ex.: Matriz 2024 · início Avaliação Fiscal",
            )
            st.selectbox("Matriz", opcoes_mat, key=f"carr_mat_{k}")
            id_mat_sel = _id_de_rotulo(st.session_state.get(f"carr_mat_{k}", ""))
            seq_salva = sequencia_volta(
                id_atual,
                id_mat_sel,
                itens_carr=itens_carr,
                itens_matriz=itens_matriz,
                carrosseis=df,
            )
            if seq_salva.empty:
                st.warning("Esta matriz ainda não tem disciplinas. Salve a matriz com a ordem primeiro.")
                continue
            tem_custom = carrossel_tem_ordem_propria(id_atual, itens_carr)
            _seed(f"carr_custom_{k}", tem_custom)
            st.checkbox(
                "Esta volta usa outra ordem das mesmas disciplinas",
                key=f"carr_custom_{k}",
                help="Caso da T04: mesmas disciplinas da matriz, sequência diferente. "
                "Se faltar ou sobrar disciplina (10 vs 12), crie outra versão da matriz.",
            )
            ordem_editada = None
            if st.session_state.get(f"carr_custom_{k}"):
                rotulos_mat = [
                    rotulo_disciplina(discs, normalizar_id(x))
                    for x in itens_da_matriz(id_mat_sel, itens_matriz)["ID_Disciplina"]
                    if normalizar_id(x)
                ]
                visivel = seq_salva[["Ordem", "ID_Disciplina"]].copy()
                visivel["ID_Disciplina"] = visivel["ID_Disciplina"].map(
                    lambda x: rotulo_disciplina(discs, x)
                )
                visivel = visivel.rename(columns={"ID_Disciplina": "Disciplina"})
                edited = st.data_editor(
                    visivel,
                    column_config={
                        "Ordem": st.column_config.NumberColumn("Ordem nesta volta", min_value=1, step=1),
                        "Disciplina": st.column_config.SelectboxColumn(
                            "Disciplina", options=rotulos_mat, required=True
                        ),
                    },
                    hide_index=True,
                    width="stretch",
                    key=f"editor_carr_itens_{k}_{id_mat_sel}",
                )
                ordem_editada = edited.rename(columns={"Disciplina": "ID_Disciplina"}).copy()
                ordem_editada["ID_Disciplina"] = ordem_editada["ID_Disciplina"].map(_id_de_rotulo)
                seq_atual = ordem_editada
            else:
                seq_atual = seq_salva
                nomes = [
                    f"{int(r['Ordem'])}ª: {rotulo_disciplina(discs, r['ID_Disciplina'])}"
                    for _, r in seq_salva.iterrows()
                ]
                st.caption("Ordem desta volta (da matriz): " + " → ".join(nomes))

            posicoes = _opcoes_posicao_seq(seq_atual, discs)
            if not posicoes:
                st.warning("Esta matriz ainda não tem disciplinas. Salve a matriz com a ordem primeiro.")
                continue
            rotulos_pos = [p[1] for p in posicoes]
            ordem_atual = row.get("Posicao_Inicio")
            try:
                ordem_atual = int(ordem_atual)
            except (TypeError, ValueError):
                ordem_atual = posicoes[0][0]
            rotulo_pos = next((p[1] for p in posicoes if p[0] == ordem_atual), rotulos_pos[0])
            _seed_opcao(f"carr_pos_{k}", rotulo_pos, rotulos_pos)
            st.selectbox(
                "Disciplina em que esta volta começou",
                rotulos_pos,
                key=f"carr_pos_{k}",
                help="Todas as turmas deste carrossel usam esta ordem; cada uma entra numa posição.",
            )
            st.checkbox("Informar data de início desta volta", key=f"carr_temdata_{k}")
            if st.session_state.get(f"carr_temdata_{k}"):
                st.date_input("Data de início", key=f"carr_data_{k}", format="DD/MM/YYYY")

            s1, s2 = st.columns(2)
            if s1.button("Salvar carrossel", type="primary", key=f"carr_save_{k}", width="stretch"):
                id_salvar = normalizar_id(st.session_state.get(f"carr_id_{k}", "")) or proximo_id(
                    carregar_carrosseis()["ID_Carrossel"], "CR"
                )
                pos_txt = st.session_state.get(f"carr_pos_{k}", "1")
                try:
                    posicao = int(str(pos_txt).split("—")[0].strip())
                except ValueError:
                    posicao = 1
                data_val = None
                if st.session_state.get(f"carr_temdata_{k}"):
                    data_val = st.session_state.get(f"carr_data_{k}")
                erro = salvar_carrossel(
                    {
                        "ID_Carrossel": id_salvar,
                        "Nome": st.session_state.get(f"carr_nome_{k}", ""),
                        "ID_Matriz": id_mat_sel,
                        "Posicao_Inicio": posicao,
                        "Data_Inicio": data_val,
                        "Status": st.session_state.get(f"carr_status_{k}", "ativo"),
                    },
                    ordem_disciplinas=ordem_editada,
                )
                if erro:
                    st.error(erro)
                else:
                    registrar_log(usuario["email"], usuario["nome"], f"Salvou carrossel {id_salvar}")
                    st.session_state[chave] = carregar_carrosseis()
                    _bump(ver_chave)
                    _ok(f"Carrossel {id_salvar} salvo.")
                    st.rerun()
            if s2.button("Remover carrossel", key=f"carr_del_{k}", width="stretch"):
                if not id_atual:
                    st.session_state[chave] = st.session_state[chave].drop(index=idx).reset_index(drop=True)
                    _bump(ver_chave)
                    st.rerun()
                erro = remover_carrossel(id_atual)
                if erro:
                    st.error(erro)
                else:
                    registrar_log(usuario["email"], usuario["nome"], f"Removeu carrossel {id_atual}")
                    st.session_state[chave] = carregar_carrosseis()
                    _bump(ver_chave)
                    _ok(f"Carrossel {id_atual} removido.")
                    st.rerun()


def _render_turmas(usuario: dict, discs: pd.DataFrame):
    st.subheader("Turmas")
    st.caption(
        "Cada turma entra numa **posição** do carrossel. A trilha completa "
        "é calculada nesta volta — não precisa cadastrar célula a célula. "
        "O código fica com zero à esquerda (**T06**, não T6) para ordenar bem em tabela dinâmica."
    )
    carrosseis = carregar_carrosseis()
    if carrosseis.empty:
        st.info("Cadastre um carrossel antes das turmas.")
        return
    itens_carr = carregar_carrossel_itens()
    itens_matriz = carregar_matriz_itens()
    chave = "pln_tur_df"
    ver_chave = "pln_tur_ver"
    if ver_chave not in st.session_state:
        st.session_state[ver_chave] = 0
    ver = int(st.session_state[ver_chave])
    if chave not in st.session_state:
        st.session_state[chave] = carregar_turmas()
    df = st.session_state[chave].copy()

    opcoes_carr = []
    for _, row in carrosseis.iterrows():
        cid = normalizar_id(row["ID_Carrossel"])
        nome = str(row.get("Nome", "")).strip()
        opcoes_carr.append(f"{cid} — {nome}" if nome else cid)

    c1, c2 = st.columns([1, 2])
    if c1.button("Nova turma", key="tur_nova", width="stretch"):
        novo = pd.DataFrame(
            [{"ID_Turma": "", "ID_Carrossel": "", "Posicao_Entrada": 1, "Status": "ativo", "Observacao": ""}]
        )
        st.session_state[chave] = pd.concat([df, novo], ignore_index=True)
        _bump(ver_chave)
        st.rerun()
    with c2:
        carr_imp = st.selectbox(
            "Ao importar da Base_Alunos, associar ao carrossel:",
            opcoes_carr,
            key="tur_imp_carr",
        )
    if st.button("Importar turmas da Base_Alunos", key="tur_import"):
        erro, n = importar_turmas_da_base(_id_de_rotulo(carr_imp))
        if erro:
            st.error(erro)
        else:
            registrar_log(usuario["email"], usuario["nome"], f"Importou {n} turmas da Base_Alunos")
            st.session_state[chave] = carregar_turmas()
            _bump(ver_chave)
            if n:
                _ok(f"{n} turma(s) importada(s). Defina a posição de entrada de cada uma.")
            else:
                _info("Nenhuma turma nova na Base_Alunos.")
            st.rerun()
    if st.button("Padronizar nomenclatura na base (T06-07/2024 e T6 → T06)", key="tur_padronizar"):
        with st.spinner("Atualizando Turmas, Base_Alunos, Entrância e ofertas…"):
            avisos = padronizar_nomenclatura_turmas()
        registrar_log(usuario["email"], usuario["nome"], "Padronizou nomenclatura das turmas")
        st.session_state[chave] = carregar_turmas()
        _bump(ver_chave)
        if avisos:
            _ok("Nomenclatura atualizada: " + " · ".join(avisos))
        else:
            _info("Nada para atualizar: os códigos já estavam no formato T06.")
        st.rerun()

    if df.empty:
        st.info("Nenhuma turma cadastrada.")
        return

    for idx, row in df.iterrows():
        k = f"{idx}_{ver}"
        codigo = normalizar_codigo_turma(row.get("ID_Turma", ""))
        status = str(row.get("Status", "ativo"))
        with st.expander(f"{codigo or '—'} ({status})", expanded=not codigo):
            _seed(f"tur_id_{k}", codigo)
            id_carr_row = normalizar_id(row.get("ID_Carrossel", ""))
            rotulo_carr = next((o for o in opcoes_carr if _id_de_rotulo(o) == id_carr_row), opcoes_carr[0])
            _seed_opcao(f"tur_carr_{k}", rotulo_carr, opcoes_carr)
            _seed(f"tur_status_{k}", status if status in STATUS_TURMA else "ativo")
            _seed(f"tur_obs_{k}", str(row.get("Observacao", "")).replace("nan", ""))

            a, b = st.columns(2)
            a.text_input("Código da turma", key=f"tur_id_{k}", placeholder="Ex.: T06")
            b.selectbox("Status", STATUS_TURMA, key=f"tur_status_{k}")
            st.selectbox("Carrossel", opcoes_carr, key=f"tur_carr_{k}")
            id_carr_sel = _id_de_rotulo(st.session_state.get(f"tur_carr_{k}", ""))
            seq = sequencia_volta(
                id_carr_sel,
                itens_carr=itens_carr,
                itens_matriz=itens_matriz,
                carrosseis=carrosseis,
            )
            posicoes = _opcoes_posicao_seq(seq, discs)
            if not posicoes:
                st.warning("Este carrossel ainda não tem disciplinas na volta.")
                continue
            rotulos_pos = [p[1] for p in posicoes]
            try:
                ordem_atual = int(row.get("Posicao_Entrada"))
            except (TypeError, ValueError):
                ordem_atual = posicoes[0][0]
            rotulo_pos = next((p[1] for p in posicoes if p[0] == ordem_atual), rotulos_pos[0])
            _seed_opcao(f"tur_pos_{k}", rotulo_pos, rotulos_pos)
            st.selectbox(
                "Posição de entrada (1ª disciplina desta turma)",
                rotulos_pos,
                key=f"tur_pos_{k}",
            )
            st.text_input("Observação", key=f"tur_obs_{k}")

            try:
                pos_sel = int(str(st.session_state.get(f"tur_pos_{k}", "1")).split("—")[0].strip())
            except ValueError:
                pos_sel = 1
            trilha = trilha_posicao(id_carr_sel, pos_sel)
            if trilha:
                nomes = [f"{p['passo']}ª: {p['Nome']}" for p in trilha]
                st.caption("Trilha: " + " → ".join(nomes))
                if trilha[0]["ordem_matriz"] == len(trilha) and len(trilha) > 1:
                    st.caption(
                        f"Esta turma entra na última desta volta ({trilha[0]['Nome']}); "
                        f"a 2ª disciplina é a primeira da volta ({trilha[1]['Nome']})."
                    )

            s1, s2 = st.columns(2)
            if s1.button("Salvar turma", type="primary", key=f"tur_save_{k}", width="stretch"):
                erro, avisos = salvar_turma(
                    {
                        "ID_Turma": st.session_state.get(f"tur_id_{k}", ""),
                        "ID_Carrossel": id_carr_sel,
                        "Posicao_Entrada": pos_sel,
                        "Status": st.session_state.get(f"tur_status_{k}", "ativo"),
                        "Observacao": st.session_state.get(f"tur_obs_{k}", ""),
                    },
                    id_anterior=codigo,
                )
                if erro:
                    st.error(erro)
                else:
                    codigo_salvo = normalizar_codigo_turma(st.session_state.get(f"tur_id_{k}", ""))
                    registrar_log(usuario["email"], usuario["nome"], f"Salvou turma {codigo_salvo}")
                    st.session_state[chave] = carregar_turmas()
                    _bump(ver_chave)
                    extra = f" Também atualizei: {' · '.join(avisos)}." if avisos else ""
                    _ok(f"Turma {codigo_salvo} salva.{extra}")
                    st.rerun()
            if s2.button("Remover turma", key=f"tur_del_{k}", width="stretch"):
                if not codigo:
                    st.session_state[chave] = st.session_state[chave].drop(index=idx).reset_index(drop=True)
                    _bump(ver_chave)
                    st.rerun()
                erro = remover_turma(codigo)
                if erro:
                    st.error(erro)
                else:
                    registrar_log(usuario["email"], usuario["nome"], f"Removeu turma {codigo}")
                    st.session_state[chave] = carregar_turmas()
                    _bump(ver_chave)
                    _ok(f"Turma {codigo} removida.")
                    st.rerun()


def _render_ofertas(usuario: dict, discs: pd.DataFrame):
    st.subheader("Ofertas")
    st.caption(
        "A oferta é a disciplina em um **trimestre acadêmico** (2026/1, 2026/2…). "
        "As datas de aula vêm do cadastro de trimestres; as datas reais dos ciclos continuam em Ciclos. "
        "Marque as turmas para puxar os alunos ativos. "
        "**Regular** segue o carrossel; **Especial** cobre reposição e casos fora do relógio."
    )
    carrosseis = carregar_carrosseis()
    turmas = carregar_turmas()
    trimestres = carregar_trimestres()
    if trimestres.empty:
        st.info("Cadastre os trimestres (seção Trimestres) antes de criar ofertas. Ex.: gerar 2026/1 a 2026/4.")
        return
    chave = "pln_ofe_df"
    ver_chave = "pln_ofe_ver"
    if ver_chave not in st.session_state:
        st.session_state[ver_chave] = 0
    ver = int(st.session_state[ver_chave])
    if chave not in st.session_state:
        st.session_state[chave] = carregar_ofertas()
    df = st.session_state[chave].copy()
    vinculos = carregar_oferta_turmas()

    if st.button("Nova oferta", key="ofe_nova"):
        novo = pd.DataFrame(
            [
                {
                    "ID_Oferta": "",
                    "ID_Carrossel": "",
                    "ID_Matriz": "",
                    "ID_Disciplina": "",
                    "ID_Trimestre": "",
                    "Ano": "",
                    "Trimestre": "",
                    "Tipo": "Regular",
                    "Status": "Planejada",
                    "Data_Prevista_Inicio": None,
                    "Data_Prevista_Fim": None,
                    "Encontro_Presencial": "Não",
                    "Observacao": "",
                }
            ]
        )
        st.session_state[chave] = pd.concat([df, novo], ignore_index=True)
        _bump(ver_chave)
        st.rerun()

    if df.empty:
        st.info("Nenhuma oferta. Crie o card do trimestre e associe as turmas.")
        return

    opcoes_tri = _opcoes_trimestre(trimestres)
    opcoes_carr = ["(nenhum — oferta especial)"]
    for _, row in carrosseis.iterrows():
        cid = normalizar_id(row["ID_Carrossel"])
        nome = str(row.get("Nome", "")).strip()
        opcoes_carr.append(f"{cid} — {nome}" if nome else cid)
    ids_disc_todos = [normalizar_id(x) for x in discs["ID_Disciplina"].tolist() if normalizar_id(x)]
    rotulos_todos = [rotulo_disciplina(discs, i) for i in ids_disc_todos]
    turmas_ids = [normalizar_codigo_turma(t) for t in turmas["ID_Turma"].tolist() if normalizar_codigo_turma(t)]

    ordem_status = {"Ativa": 0, "Planejada": 1, "Encerrada": 2}
    indices = sorted(
        df.index.tolist(),
        key=lambda i: (
            ordem_status.get(str(df.loc[i].get("Status", "")), 9),
            str(df.loc[i].get("ID_Trimestre", "")),
        ),
    )

    for idx in indices:
        row = df.loc[idx]
        k = f"{idx}_{ver}"
        id_atual = normalizar_id(row.get("ID_Oferta", ""))
        id_disc = normalizar_id(row.get("ID_Disciplina", ""))
        status = str(row.get("Status", "Planejada"))
        tipo = str(row.get("Tipo", "Regular"))
        id_tri = normalizar_id_trimestre(
            row.get("Ano"),
            row.get("Trimestre"),
            row.get("ID_Trimestre"),
        )
        rotulo_tri = rotulo_trimestre(*parse_id_trimestre(id_tri)) if id_tri else ""
        nome_disc = nome_disciplina(discs, id_disc) if id_disc else "Nova oferta"
        n_turmas = len(turmas_da_oferta(id_atual, vinculos)) if id_atual else 0
        titulo = f"{id_atual or '—'} — {nome_disc}"
        extras = [x for x in [tipo, status, rotulo_tri, f"{n_turmas} turmas"] if x]
        titulo = f"{titulo} ({' · '.join(extras)})"

        with st.expander(titulo, expanded=status == "Ativa" or not id_atual):
            _seed(f"ofe_id_{k}", id_atual)
            _seed(f"ofe_tipo_{k}", tipo if tipo in TIPO_OFERTA else "Regular")
            _seed(f"ofe_status_{k}", status if status in STATUS_OFERTA else "Planejada")
            rotulo_tri_padrao = next(
                (o for o in opcoes_tri if _id_trimestre_de_rotulo(o, trimestres) == id_tri),
                opcoes_tri[0] if opcoes_tri else "",
            )
            _seed_opcao(f"ofe_tri_{k}", rotulo_tri_padrao, opcoes_tri)
            id_carr_row = normalizar_id(row.get("ID_Carrossel", ""))
            rotulo_carr = next(
                (o for o in opcoes_carr if _id_de_rotulo(o) == id_carr_row),
                opcoes_carr[0],
            )
            _seed_opcao(f"ofe_carr_{k}", rotulo_carr, opcoes_carr)
            enc_salvo = str(row.get("Encontro_Presencial", "")).strip()
            _seed(f"ofe_obs_{k}", str(row.get("Observacao", "")).replace("nan", ""))

            a, b, c = st.columns(3)
            a.text_input("Código da oferta", key=f"ofe_id_{k}", placeholder="Ex.: 2026T1-AVF")
            b.selectbox("Tipo", TIPO_OFERTA, key=f"ofe_tipo_{k}")
            c.selectbox("Status", STATUS_OFERTA, key=f"ofe_status_{k}")
            st.selectbox("Trimestre acadêmico", opcoes_tri, key=f"ofe_tri_{k}")
            id_tri_sel = _id_trimestre_de_rotulo(st.session_state.get(f"ofe_tri_{k}", ""), trimestres)
            tri_sel = trimestre_por_id(id_tri_sel, trimestres)
            if tri_sel is not None:
                ini_txt = ""
                fim_txt = ""
                if tri_sel.get("Data_Inicio"):
                    ini_txt = pd.Timestamp(tri_sel["Data_Inicio"]).strftime("%d/%m/%Y")
                if tri_sel.get("Data_Fim"):
                    fim_txt = pd.Timestamp(tri_sel["Data_Fim"]).strftime("%d/%m/%Y")
                if ini_txt or fim_txt:
                    st.caption(f"Aulas deste trimestre: **{ini_txt or '—'}** a **{fim_txt or '—'}** (cadastro de trimestres).")
                else:
                    st.caption("Este trimestre ainda não tem datas de aula. Preencha na seção Trimestres.")
            st.selectbox("Carrossel", opcoes_carr, key=f"ofe_carr_{k}")

            tipo_sel = st.session_state.get(f"ofe_tipo_{k}", "Regular")
            carr_sel_rotulo = st.session_state.get(f"ofe_carr_{k}", "")
            id_carr_sel = "" if carr_sel_rotulo.startswith("(nenhum") else _id_de_rotulo(carr_sel_rotulo)

            opcoes_disc = rotulos_todos
            if tipo_sel == "Regular" and id_carr_sel:
                bloco = sequencia_volta(id_carr_sel)
                ids_mat = [normalizar_id(x) for x in bloco["ID_Disciplina"].tolist() if normalizar_id(x)]
                if ids_mat:
                    opcoes_disc = [rotulo_disciplina(discs, i) for i in ids_mat]
            rotulo_disc_padrao = rotulo_disciplina(discs, id_disc) if id_disc else (opcoes_disc[0] if opcoes_disc else "")
            if rotulo_disc_padrao not in opcoes_disc and opcoes_disc:
                rotulo_disc_padrao = opcoes_disc[0]
            _seed_opcao(f"ofe_disc_{k}", rotulo_disc_padrao, opcoes_disc)
            st.selectbox("Disciplina", opcoes_disc, key=f"ofe_disc_{k}")
            id_disc_sel = _id_de_rotulo(st.session_state.get(f"ofe_disc_{k}", ""))

            sugestao = encontro_sugerido_oferta(id_carr_sel, id_disc_sel) if id_carr_sel else "Não"
            enc_padrao = enc_salvo if enc_salvo in ENCONTRO_OPCOES else sugestao
            _seed_opcao(f"ofe_enc_{k}", enc_padrao, list(ENCONTRO_OPCOES))
            st.selectbox(
                "Encontro presencial nesta oferta",
                ENCONTRO_OPCOES,
                key=f"ofe_enc_{k}",
                help=f"Sugestão desta volta: {sugestao}. A data real do encontro continua no cadastro da disciplina/ciclos.",
            )
            _seed(
                f"ofe_link_{k}",
                str(row.get("Link_Plataforma", "")).replace("nan", "").replace("None", ""),
            )
            st.text_input(
                "Link da disciplina na plataforma (Canvas)",
                key=f"ofe_link_{k}",
                placeholder="https://rehagro.instructure.com/courses/3283",
                help="URL do curso no Canvas desta oferta. Os alunos verão o atalho no menu.",
            )
            st.text_input("Observação", key=f"ofe_obs_{k}")

            st.markdown("**Turmas nesta oferta**")
            if not turmas_ids:
                st.info("Cadastre turmas na aba Turmas para associá-las aqui.")
            associadas = set(turmas_da_oferta(id_atual, vinculos)) if id_atual else set()
            cols = st.columns(4)
            for i, codigo_t in enumerate(turmas_ids):
                chave_t = f"ofe_t_{k}_{codigo_t}"
                _seed(chave_t, codigo_t in associadas)
                cols[i % 4].checkbox(codigo_t, key=chave_t)

            turmas_marcadas = [t for t in turmas_ids if st.session_state.get(f"ofe_t_{k}_{t}")]
            if id_atual and st.checkbox("Mostrar alunos puxados", key=f"ofe_ver_alunos_{k}"):
                resumo = resumo_participantes(id_atual)
                partes = [f"**{resumo['total']} alunos** ativos puxados"]
                if resumo["por_turma"]:
                    partes.append(
                        ", ".join(f"{t}: {n}" for t, n in resumo["por_turma"].items())
                    )
                if resumo["desvinculados"]:
                    partes.append(f"{resumo['desvinculados']} desvinculado(s)")
                if resumo["incluidos"]:
                    partes.append(f"{resumo['incluidos']} inclusão(ões)")
                st.info(" · ".join(partes))
                if not resumo["alunos"].empty:
                    with st.expander("Ver alunos desta oferta", expanded=False):
                        st.dataframe(
                            resumo["alunos"][["Nome_Aluno", "Email_Aluno", "Turma", "Origem"]],
                            hide_index=True,
                            width="stretch",
                        )

            s1, s2 = st.columns(2)
            if s1.button("Salvar oferta", type="primary", key=f"ofe_save_{k}", width="stretch"):
                id_salvar = normalizar_id(st.session_state.get(f"ofe_id_{k}", ""))
                if not id_salvar:
                    id_salvar = id_oferta_sugerido(
                        id_tri_sel,
                        id_disc_sel,
                        carregar_ofertas()["ID_Oferta"],
                    )
                erro = salvar_oferta(
                    {
                        "ID_Oferta": id_salvar,
                        "ID_Carrossel": id_carr_sel,
                        "ID_Disciplina": id_disc_sel,
                        "ID_Trimestre": id_tri_sel,
                        "Tipo": st.session_state.get(f"ofe_tipo_{k}"),
                        "Status": st.session_state.get(f"ofe_status_{k}"),
                        "Encontro_Presencial": st.session_state.get(f"ofe_enc_{k}"),
                        "Link_Plataforma": st.session_state.get(f"ofe_link_{k}", ""),
                        "Observacao": st.session_state.get(f"ofe_obs_{k}", ""),
                    },
                    turmas_marcadas,
                )
                if erro:
                    st.error(erro)
                else:
                    registrar_log(usuario["email"], usuario["nome"], f"Salvou oferta {id_salvar}")
                    st.session_state[chave] = carregar_ofertas()
                    _bump(ver_chave)
                    _ok(f"Oferta {id_salvar} salva com {len(turmas_marcadas)} turma(s).")
                    st.rerun()
            if s2.button("Remover oferta", key=f"ofe_del_{k}", width="stretch"):
                if not id_atual:
                    st.session_state[chave] = st.session_state[chave].drop(index=idx).reset_index(drop=True)
                    _bump(ver_chave)
                    st.rerun()
                erro = remover_oferta(id_atual)
                if erro:
                    st.error(erro)
                else:
                    registrar_log(usuario["email"], usuario["nome"], f"Removeu oferta {id_atual}")
                    st.session_state[chave] = carregar_ofertas()
                    _bump(ver_chave)
                    _ok(f"Oferta {id_atual} removida.")
                    st.rerun()

            if id_atual:
                _render_excecoes(usuario, id_atual, k)


def _render_excecoes(usuario: dict, id_oferta: str, k: str):
    st.markdown("**Exceções desta oferta**")
    st.caption("Desvincular tira um aluno da turma associada. Incluir traz alguém que não veio com a turma.")
    alunos = carregar_alunos_base()
    excecoes = carregar_excecoes()
    excecoes = excecoes[excecoes["ID_Oferta"].map(normalizar_id) == normalizar_id(id_oferta)]
    if not excecoes.empty:
        for i, ex in excecoes.iterrows():
            c1, c2 = st.columns([4, 1])
            c1.write(
                f"{ex['Tipo']}: **{ex['Nome_Aluno'] or ex['Email_Aluno']}** "
                f"({ex['Email_Aluno']})"
                + (f" — {ex['Motivo']}" if str(ex['Motivo']).strip() else "")
            )
            if c2.button("Desfazer", key=f"ex_del_{k}_{i}"):
                remover_excecao(id_oferta, ex["Email_Aluno"])
                registrar_log(
                    usuario["email"],
                    usuario["nome"],
                    f"Removeu exceção {ex['Email_Aluno']} da oferta {id_oferta}",
                )
                _ok("Exceção desfeita. O aluno volta à regra da turma.")
                st.rerun()

    opcoes_alunos = []
    mapa_email = {}
    if not alunos.empty:
        for _, aluno in alunos.sort_values("Nome_Completo").iterrows():
            rotulo = f"{aluno['Nome_Completo']} ({aluno['Turma_Norm']}) — {aluno['Email_Limpo']}"
            opcoes_alunos.append(rotulo)
            mapa_email[rotulo] = (
                str(aluno["Email_Limpo"]),
                str(aluno["Nome_Completo"]),
            )
    if not opcoes_alunos:
        st.caption("Não há alunos na Base_Alunos para montar a lista de exceções.")
        return
    escolhido = st.selectbox("Aluno", opcoes_alunos, key=f"ex_aluno_{k}")
    tipo_ex = st.selectbox("Ação", TIPO_EXCECAO, key=f"ex_tipo_{k}")
    motivo = st.text_input("Motivo", key=f"ex_motivo_{k}", placeholder="Ex.: trancamento, reposição…")
    if st.button("Aplicar exceção", key=f"ex_add_{k}"):
        email, nome = mapa_email.get(escolhido, ("", ""))
        erro = salvar_excecao(
            {
                "ID_Oferta": id_oferta,
                "Email_Aluno": email,
                "Nome_Aluno": nome,
                "Tipo": tipo_ex,
                "Motivo": motivo,
            }
        )
        if erro:
            st.error(erro)
        else:
            registrar_log(
                usuario["email"],
                usuario["nome"],
                f"{tipo_ex} {email} na oferta {id_oferta}",
            )
            _ok(f"{tipo_ex} aplicado a {nome or email}.")
            st.rerun()
