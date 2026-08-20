"""Rotas, seções do menu lateral e compatibilidade com nomes legados."""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

# Rotas primeiro: outros módulos importam estes nomes no carregamento.
# Se domain/auth forem importados aqui, o ciclo quebra o login (ImportError).

# --- Rotas internas (estáveis no código) ---
ROTA_INICIO = "inicio"

# Aluno — avaliar
ROTA_PARES_AVALIAR = "pares_avaliar"
ROTA_CURSO_AVALIAR = "curso_avaliar"

# Aluno — desempenho
ROTA_FREQ_AULAS = "freq_aulas"
ROTA_FREQ_DAILIES = "freq_dailies"
ROTA_RESULTADOS_PARES = "resultados_pares"
ROTA_AVALIACAO_GRUPO_ALUNO = "avaliacao_grupo_aluno"
ROTA_MINHAS_NOTAS = "minhas_notas"

# Professor orientador
ROTA_PARES_ACOMP = "pares_acompanhamento"
ROTA_MODERACAO = "moderacao"
ROTA_ORIENTADOR = "orientador"
ROTA_LANCAR_BANCA = "lancar_banca"
ROTA_ANOTACOES_DAILY = "anotacoes_daily"
ROTA_ORDEM_APRESENTACAO = "ordem_apresentacao"
ROTA_FREQ_CONTROLE = "freq_controle"
ROTA_FREQ_PROGRAMACAO = "freq_programacao"
ROTA_FREQ_DAILIES_PROF = "freq_dailies_prof"
ROTA_IMPORT_CANVAS = "import_canvas"
ROTA_LIBERAR_NOTAS = "liberar_notas"

# Coordenador
ROTA_COORD_CONFIG = "coord_config"
ROTA_COORD_COMPONENTES = "coord_componentes"
ROTA_COORD_CONFERIR = "coord_conferir"
ROTA_COORD_DISCIPLINAS = "coord_disciplinas"
ROTA_COORD_CICLOS = "coord_ciclos"
ROTA_COORD_PROFESSORES = "coord_professores"
ROTA_COORD_PLANEJAMENTO = "coord_planejamento"
ROTA_FREQ_ENCONTRO = "freq_encontro"

ROTAS_LAYOUT_LARGO = frozenset(
    {
        ROTA_FREQ_CONTROLE,
        ROTA_FREQ_PROGRAMACAO,
        ROTA_FREQ_DAILIES_PROF,
        ROTA_FREQ_ENCONTRO,
        ROTA_ORIENTADOR,
        ROTA_COORD_CONFERIR,
        ROTA_COORD_DISCIPLINAS,
        ROTA_COORD_CICLOS,
        ROTA_COORD_PROFESSORES,
        ROTA_COORD_PLANEJAMENTO,
        ROTA_PARES_ACOMP,
        ROTA_LANCAR_BANCA,
        ROTA_ANOTACOES_DAILY,
        ROTA_ORDEM_APRESENTACAO,
        ROTA_COORD_CONFIG,
    }
)

LEGACY_ROUTES: dict[str, str] = {
    "Painel Geral": ROTA_PARES_ACOMP,
    "Componentes de Avaliação": ROTA_COORD_COMPONENTES,
    "Avaliação de Grupo": ROTA_LANCAR_BANCA,
    "Avaliação de pares": ROTA_PARES_AVALIAR,
    "Avaliação do curso": ROTA_CURSO_AVALIAR,
    "Meus resultados de pares": ROTA_RESULTADOS_PARES,
    "Minhas Notas": ROTA_MINHAS_NOTAS,
    "Avaliação do grupo": ROTA_AVALIACAO_GRUPO_ALUNO,
    "Minha Frequência": ROTA_FREQ_AULAS,
    "Minhas Dailies": ROTA_FREQ_DAILIES,
    "Avaliações de pares": ROTA_PARES_ACOMP,
    "Moderação de Comentários": ROTA_MODERACAO,
    "Controle de Frequência": ROTA_FREQ_CONTROLE,
    "Controle de dailies": ROTA_FREQ_DAILIES_PROF,
    "Cadastro de Avaliações": ROTA_COORD_COMPONENTES,
    "Configurações do Coordenador": ROTA_COORD_CONFIG,
    "Janela de entregas": ROTA_COORD_CONFIG,
    "Janela de avaliação da banca": ROTA_COORD_CONFIG,
    "Ordem de apresentação": ROTA_ORDEM_APRESENTACAO,
    "Conferência de Entregas": ROTA_COORD_CONFERIR,
    "Conferir entregas": ROTA_COORD_CONFERIR,
    "Conferir notas grupos": ROTA_COORD_CONFERIR,
    "Avaliação do Orientador": ROTA_ORIENTADOR,
    "Avaliação de Entregas": ROTA_LANCAR_BANCA,
    "Importar Canvas": ROTA_IMPORT_CANVAS,
}


@dataclass(frozen=True)
class ItemMenu:
    rota: str
    rotulo: str


@dataclass(frozen=True)
class SecaoMenu:
    titulo: str | None
    itens: tuple[ItemMenu, ...]


def normalizar_rota(rota: str | None) -> str:
    if not rota:
        return ROTA_INICIO
    return LEGACY_ROUTES.get(rota, rota)


def rota_padrao(usuario: dict, perfil: str) -> str:
    if perfil == "Aluno":
        return ROTA_INICIO
    if perfil == "Secretaria":
        return ROTA_FREQ_CONTROLE
    if perfil == "Professor":
        return ROTA_FREQ_PROGRAMACAO
    return ROTA_INICIO


def pode_gerenciar_liberacao_notas(usuario: dict) -> bool:
    from auth.supabase_auth import professor_e_orientador, usuario_e_coordenador

    if professor_e_orientador(usuario):
        return True
    if usuario.get("perfil") == "Professor" and usuario_e_coordenador(usuario):
        return bool(st.session_state.get("modo_coordenador", False))
    return False


def _item_liberacao_notas() -> ItemMenu:
    return ItemMenu(ROTA_LIBERAR_NOTAS, "Liberação de notas finais")


def _secoes_aluno() -> list[SecaoMenu]:
    return [
        SecaoMenu(None, (ItemMenu(ROTA_INICIO, "Calendário"),)),
        SecaoMenu(
            "Avaliar",
            (
                ItemMenu(ROTA_PARES_AVALIAR, "Pares — avaliar"),
                ItemMenu(ROTA_CURSO_AVALIAR, "Avaliação do curso"),
            ),
        ),
        SecaoMenu(
            "Meu desempenho e participação",
            (
                ItemMenu(ROTA_FREQ_AULAS, "Frequência nas aulas"),
                ItemMenu(ROTA_FREQ_DAILIES, "Presença nas dailies"),
                ItemMenu(ROTA_RESULTADOS_PARES, "Resultados de pares"),
                ItemMenu(ROTA_AVALIACAO_GRUPO_ALUNO, "Avaliação do grupo"),
                ItemMenu(ROTA_MINHAS_NOTAS, "Minhas notas (boletim)"),
            ),
        ),
    ]


def _secoes_professor_orientador(usuario: dict, modo_coordenador: bool) -> list[SecaoMenu]:
    from auth.supabase_auth import professor_e_orientador

    itens_avaliacoes: list[ItemMenu] = []
    if professor_e_orientador(usuario):
        itens_avaliacoes.append(ItemMenu(ROTA_ORDEM_APRESENTACAO, "Ordem de apresentação"))
    itens_avaliacoes.append(ItemMenu(ROTA_LANCAR_BANCA, "Lançar notas da banca"))
    if professor_e_orientador(usuario) or modo_coordenador:
        itens_avaliacoes.append(ItemMenu(ROTA_ANOTACOES_DAILY, "Anotações da daily"))
    itens_avaliacoes.extend(
        [
            ItemMenu(ROTA_ORIENTADOR, "Avaliação do orientador"),
            ItemMenu(ROTA_PARES_ACOMP, "Avaliação de pares"),
            ItemMenu(ROTA_MODERACAO, "Moderação de comentários"),
        ]
    )
    if professor_e_orientador(usuario):
        itens_avaliacoes.append(_item_liberacao_notas())

    secoes: list[SecaoMenu] = [
        SecaoMenu(None, (ItemMenu(ROTA_FREQ_PROGRAMACAO, "Calendário"),)),
        SecaoMenu("Avaliações do ciclo", tuple(itens_avaliacoes)),
        SecaoMenu(
            "Presença",
            (
                ItemMenu(ROTA_FREQ_CONTROLE, "Controle de frequência"),
                ItemMenu(ROTA_FREQ_DAILIES_PROF, "Controle de dailies"),
                ItemMenu(ROTA_FREQ_ENCONTRO, "Presença no encontro presencial"),
            ),
        ),
        SecaoMenu(
            "Integrações",
            (ItemMenu(ROTA_IMPORT_CANVAS, "Importar Canvas"),),
        ),
    ]
    if modo_coordenador:
        itens_coord: list[ItemMenu] = [
            ItemMenu(ROTA_COORD_CONFIG, "Janela de avaliação da banca"),
            ItemMenu(ROTA_COORD_PLANEJAMENTO, "Planejamento acadêmico"),
            ItemMenu(ROTA_COORD_DISCIPLINAS, "Cadastro de disciplinas"),
            ItemMenu(ROTA_COORD_CICLOS, "Cadastro de ciclos"),
            ItemMenu(ROTA_COORD_PROFESSORES, "Cadastro de professores"),
            ItemMenu(ROTA_COORD_COMPONENTES, "Componentes da disciplina"),
            ItemMenu(ROTA_COORD_CONFERIR, "Conferir notas grupos"),
        ]
        if not professor_e_orientador(usuario):
            itens_coord.append(ItemMenu(ROTA_FREQ_DAILIES_PROF, "Controle de dailies"))
            itens_coord.append(ItemMenu(ROTA_FREQ_ENCONTRO, "Presença no encontro presencial"))
            itens_coord.append(_item_liberacao_notas())
        secoes.insert(
            0,
            SecaoMenu("Coordenação", tuple(itens_coord)),
        )
    return secoes


def _secoes_especialista() -> list[SecaoMenu]:
    return [
        SecaoMenu(None, (ItemMenu(ROTA_FREQ_PROGRAMACAO, "Calendário"),)),
        SecaoMenu(
            "Avaliações do ciclo",
            (ItemMenu(ROTA_LANCAR_BANCA, "Lançar notas da banca"),),
        ),
    ]


def _secoes_secretaria() -> list[SecaoMenu]:
    return [
        SecaoMenu(
            "Presença",
            (
                ItemMenu(ROTA_FREQ_PROGRAMACAO, "Programação de aulas e dailies"),
                ItemMenu(ROTA_FREQ_CONTROLE, "Controle de frequência"),
                ItemMenu(ROTA_FREQ_ENCONTRO, "Presença no encontro presencial"),
            ),
        ),
    ]


def secoes_menu(usuario: dict, perfil: str) -> list[SecaoMenu]:
    if perfil == "Aluno":
        return _secoes_aluno()
    if perfil == "Secretaria":
        return _secoes_secretaria()
    if perfil == "Professor":
        tipo = usuario.get("tipo_professor") or "Orientador"
        if tipo == "Especialista":
            return _secoes_especialista()
        modo = bool(st.session_state.get("modo_coordenador", False))
        return _secoes_professor_orientador(usuario, modo)
    return [SecaoMenu(None, (ItemMenu(ROTA_INICIO, "Início"),))]


def rotas_permitidas(secoes: list[SecaoMenu]) -> list[str]:
    rotas: list[str] = []
    for secao in secoes:
        for item in secao.itens:
            rotas.append(item.rota)
    return rotas


def titulo_sidebar(perfil: str, usuario: dict) -> str:
    if perfil == "Aluno":
        return "Menu do aluno"
    if perfil == "Secretaria":
        return "Menu da secretaria"
    if perfil == "Professor":
        tipo = usuario.get("tipo_professor") or "Orientador"
        if tipo == "Especialista":
            return "Menu do especialista"
        return "Menu do professor"
    return "Menu"


def renderizar_sidebar(usuario: dict, perfil: str) -> str:
    """Desenha o menu lateral e retorna a rota selecionada."""
    st.sidebar.title(titulo_sidebar(perfil, usuario))

    if perfil == "Professor":
        from auth.supabase_auth import usuario_e_coordenador

        tipo = usuario.get("tipo_professor") or "Orientador"
        st.sidebar.caption(f"Tipo de professor: **{tipo}**")
        if usuario_e_coordenador(usuario):
            modo = st.sidebar.toggle(
                "Modo coordenador",
                value=bool(st.session_state.get("modo_coordenador", False)),
                key="toggle_modo_coordenador",
            )
            st.session_state["modo_coordenador"] = modo

    secoes = secoes_menu(usuario, perfil)
    permitidas = rotas_permitidas(secoes)
    padrao = rota_padrao(usuario, perfil)

    rota_atual = normalizar_rota(st.session_state.get("escolha_menu"))
    if rota_atual not in permitidas:
        rota_atual = padrao
        st.session_state["escolha_menu"] = padrao

    for secao in secoes:
        rotas_secao = {item.rota for item in secao.itens}
        destino = (
            st.sidebar.expander(secao.titulo, expanded=rota_atual in rotas_secao)
            if secao.titulo
            else st.sidebar.container()
        )
        with destino:
            for item in secao.itens:
                ativo = item.rota == rota_atual
                if st.button(
                    item.rotulo,
                    key=f"nav_{item.rota}",
                    width="stretch",
                    type="primary" if ativo else "secondary",
                ):
                    if item.rota != rota_atual:
                        st.session_state["escolha_menu"] = item.rota
                        st.rerun()

    return rota_atual


def ir_para(rota: str):
    st.session_state["escolha_menu"] = rota
    st.rerun()
