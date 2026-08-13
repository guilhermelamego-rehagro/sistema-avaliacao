import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import io
import re

from auth.supabase_auth import (
    SENHA_MINIMA,
    fazer_login,
    fazer_logout,
    professor_e_orientador,
    trocar_senha,
    usuario_e_coordenador,
    validar_senha,
)
from data.sheets import (
    ler_aba,
    ler_aba_frequencia,
    limpar_cache_planilhas,
    planilha,
    preparar_ambiente_planilhas,
)
from domain.ciclos import indice_ciclo_padrao, obter_disciplina_ativa
from domain.notas import calcular_nota_pares
from domain.presenca import calcular_matriz_dailies, calcular_matriz_presencas, carregar_base_presenca, compilar_grid_frequencia
from utils.logs import registrar_log, registrar_log_acesso
from navigation import (
    LEGACY_ROUTES,
    ROTA_COORD_COMPONENTES,
    ROTA_COORD_CONFIG,
    ROTA_COORD_CONFERIR,
    ROTA_CURSO_AVALIAR,
    ROTA_FREQ_AULAS,
    ROTA_FREQ_CONTROLE,
    ROTA_FREQ_DAILIES,
    ROTA_IMPORT_CANVAS,
    ROTA_INICIO,
    ROTA_LANCAR_BANCA,
    ROTA_LIBERAR_NOTAS,
    ROTA_MINHAS_NOTAS,
    ROTA_MODERACAO,
    ROTA_ORIENTADOR,
    ROTA_PARES_ACOMP,
    ROTA_PARES_AVALIAR,
    ROTA_RESULTADOS_PARES,
    pode_gerenciar_liberacao_notas,
    renderizar_sidebar,
    rota_padrao,
)
from views import aluno_minhas_notas, prof_avaliacao_grupo, prof_avaliacao_orientador
from views import prof_config_componentes, prof_coordenador, prof_coordenador_entregas, prof_import_canvas
from views import home_aluno, prof_liberacao_notas

# 1. Configurações Iniciais da Página
st.set_page_config(page_title="Portal de Avaliações - Rehagro", page_icon="🎓", layout="wide")

# Customização de Cores Avançada via CSS
st.markdown("""
    <style>
        div[data-testid="stSlider"] div[role="slider"] div {
            color: #004D28 !important;
            font-weight: bold !important;
            font-size: 18px !important;
        }
        div[data-testid="stSlider"] label, div[data-testid="stSlider"] span {
            color: #004D28 !important;
        }
        button[data-testid="stSidebarCollapseButton"] {
            background-color: #004D28 !important;
            color: white !important;
            border-radius: 50% !important;
            border: 2px solid #B38F36 !important;
            width: 40px !important;
            height: 40px !important;
        }
    </style>
""", unsafe_allow_html=True)

# Interface Lateral
st.sidebar.image("logo.png", width=200)

if "usuario_logado" not in st.session_state:
    st.session_state["usuario_logado"] = None

# ==========================================
# TELA DE LOGIN (SUPABASE)
# ==========================================
if not st.session_state["usuario_logado"]:
    _, centro_login, _ = st.columns([1, 1.2, 1])
    with centro_login:
        st.title("Bem-vindo ao Portal de Avaliações")
        st.caption("Acesse com seu e-mail institucional e senha.")

        with st.form("form_login"):
            email_input = st.text_input("E-mail:")
            senha_input = st.text_input("Senha:", type="password")
            entrar = st.form_submit_button("Entrar", type="primary", width="stretch")

    if entrar:
        if not email_input or not senha_input:
            st.error("Informe e-mail e senha.")
        else:
            with st.spinner("Autenticando..."):
                usuario, erro = fazer_login(email_input, senha_input)
            if erro:
                st.error(erro)
            else:
                registrar_log(usuario["email"], usuario["nome"], f"Acessou como {usuario['perfil']}")
                st.session_state["escolha_menu"] = rota_padrao(usuario, usuario["perfil"])
                st.session_state["modo_coordenador"] = False
                st.rerun()

# ==========================================
# TROCA OBRIGATÓRIA DE SENHA (1º ACESSO)
# ==========================================
elif st.session_state["usuario_logado"].get("deve_trocar_senha"):
    usuario = st.session_state["usuario_logado"]
    _, centro_senha, _ = st.columns([1, 1.2, 1])
    with centro_senha:
        st.title("Defina sua nova senha")
        st.info(
            f"Olá, **{usuario['nome']}**! Por segurança, troque a senha temporária "
            f"antes de continuar. Mínimo de {SENHA_MINIMA} caracteres."
        )

        with st.form("form_trocar_senha"):
            nova_senha = st.text_input("Nova senha:", type="password")
            confirmar = st.text_input("Confirmar nova senha:", type="password")
            salvar = st.form_submit_button("Salvar e continuar", type="primary", width="stretch")

    if salvar:
        if nova_senha != confirmar:
            st.error("As senhas não coincidem.")
        else:
            erro = validar_senha(nova_senha)
            if erro:
                st.error(erro)
            else:
                erro_troca = trocar_senha(nova_senha)
                if erro_troca:
                    st.error(erro_troca)
                else:
                    registrar_log(usuario["email"], usuario["nome"], "Trocou senha no primeiro acesso")
                    st.success("Senha atualizada com sucesso!")
                    st.rerun()

# ==========================================
# ÁREA LOGADA
# ==========================================
else:
    aluno = st.session_state["usuario_logado"]
    perfil = aluno.get("perfil", "Aluno")
    preparar_ambiente_planilhas()

    st.sidebar.write(f"**{aluno['nome']}**")
    st.sidebar.caption(f"{aluno['email']} · {perfil}")
    if usuario_e_coordenador(aluno):
        st.sidebar.caption("Função: **Coordenador**")
    if st.sidebar.button("Sair", width="stretch"):
        registrar_log(aluno["email"], aluno["nome"], "Logout")
        fazer_logout()
        st.rerun()

    if st.session_state.get("escolha_menu") in LEGACY_ROUTES:
        st.session_state["escolha_menu"] = LEGACY_ROUTES[st.session_state["escolha_menu"]]

    menu = renderizar_sidebar(aluno, perfil)

    hoje = pd.to_datetime(datetime.now(ZoneInfo("America/Sao_Paulo"))).normalize().tz_localize(None)

    if menu == ROTA_INICIO and perfil == "Aluno":
        home_aluno.render(aluno)

    # ------------------------------------------
    # MÓDULO 1: AVALIAÇÃO DE PARES
    # ------------------------------------------
    elif menu == ROTA_PARES_AVALIAR and perfil == "Aluno":
        st.header("Pares — avaliar")
        
        df_disc = ler_aba("Disciplinas")
        df_ciclos = ler_aba("Ciclos")
        df_entrancia = ler_aba("Entrancia_Turma")
        df_aval = ler_aba("Avaliacoes")
        
        disc_ativa = df_disc[df_disc['Status'].str.lower() == 'ativo']
        if disc_ativa.empty:
            st.warning("Não há nenhuma disciplina ativa no momento.")
            st.stop()
            
        id_disc = str(disc_ativa.iloc[0]['ID_Disciplina']).strip()
        nome_disc = str(disc_ativa.iloc[0]['Nome_Disciplina']).strip()
        
        df_ciclos['Data início'] = pd.to_datetime(df_ciclos['Data início'], format='%d/%m/%Y', errors='coerce')
        df_ciclos['Data fim'] = pd.to_datetime(df_ciclos['Data fim'], format='%d/%m/%Y', errors='coerce')
        
        ciclos_disc = df_ciclos[df_ciclos['ID_Disciplina'].astype(str).str.strip() == id_disc]
        ciclo_ativo = ciclos_disc[(ciclos_disc['Status'].str.lower() == 'ativo') | 
                                  ((hoje >= ciclos_disc['Data início']) & (hoje <= ciclos_disc['Data fim']))]
        
        if ciclo_ativo.empty:
            st.warning("Não há nenhum ciclo de avaliação aberto para você hoje.")
            st.stop()
            
        id_ciclo = str(ciclo_ativo.iloc[0]['ID_Ciclo']).strip()
        nome_ciclo = str(ciclo_ativo.iloc[0]['Nome_Ciclo']).strip()
        
        ja_avaliou = not df_aval[(df_aval['ID_Ciclo'].astype(str).str.strip() == id_ciclo) & 
                                 (df_aval['Email_Avaliador'].astype(str).str.lower().str.strip() == aluno['email'])].empty
        if ja_avaliou:
            st.success(f"Você já enviou suas avaliações de pares para o **{nome_ciclo}**! Obrigado.")
            st.stop()
            
        meu_vinculo = df_entrancia[(df_entrancia['Email_Pessoal'].str.lower().str.strip() == aluno['email']) & 
                                   (df_entrancia['ID_Disciplina'].astype(str).str.strip() == id_disc)]
        if meu_vinculo.empty:
            st.error("Não encontramos seu vínculo de grupo nesta disciplina.")
            st.stop()
            
        meu_grupo = str(meu_vinculo.iloc[0]['Grupo'])
        colegas = df_entrancia[(df_entrancia['Grupo'].astype(str) == meu_grupo) & 
                               (df_entrancia['ID_Disciplina'].astype(str).str.strip() == id_disc) & 
                               (df_entrancia['Email_Pessoal'].str.lower().str.strip() != aluno['email'])]

        st.info(f"**Disciplina:** {nome_disc} | **Avaliação:** {nome_ciclo} | **Seu Grupo:** {meu_grupo}")
        if colegas.empty:
            st.warning("Não há outros colegas registrados no seu grupo para avaliar.")
            st.stop()

        respostas_pares = {}
        with st.form("form_pares"):
            for index, colega in colegas.iterrows():
                st.write("---")
                st.subheader(f"👤 {colega['Nome_Completo']}")
                
                nota = st.radio("Nota (0 a 5):", [0, 1, 2, 3, 4, 5], index=None, horizontal=True, key=f"n_{index}")
                coment = st.text_area("Feedback (opcional):", placeholder="Escreva seu feedback aqui...", key=f"c_{index}")
                
                respostas_pares[colega['Email_Pessoal']] = {"nome": colega['Nome_Completo'], "nota": nota, "coment": coment}

            if st.form_submit_button("Enviar Avaliação de Pares", type="primary", width="stretch"):
                notas_vazias = [d['nome'] for d in respostas_pares.values() if d['nota'] is None]
                if notas_vazias:
                    st.error("⚠️ Por favor, selecione uma nota para todos os colegas antes de enviar.")
                else:
                    with st.spinner("Salvando notas..."):
                        aba_avaliacoes = planilha.worksheet("Avaliacoes")
                        dados_inserir = []
                        agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
                        for email_aval, d in respostas_pares.items():
                            dados_inserir.append([agora, id_ciclo, nome_disc, nome_ciclo, email_aval, d['nome'], meu_grupo, d['nota'], aluno['email'], aluno['nome'], d['coment'], "", ""])
                        aba_avaliacoes.append_rows(dados_inserir)
                        registrar_log(aluno['email'], aluno['nome'], f"Enviou avaliação pares - {nome_ciclo}")
                        
                        limpar_cache_planilhas()
                        st.session_state["escolha_menu"] = ROTA_CURSO_AVALIAR
                        st.session_state["sucesso_redirecionamento"] = f"✅ Suas avaliações de pares para o **{nome_ciclo}** foram salvas! Por favor, responda agora à Avaliação do Curso abaixo."
                        st.rerun()

    # ------------------------------------------
    # MÓDULO 2: AVALIAÇÃO DO CURSO
    # ------------------------------------------
    elif menu == ROTA_CURSO_AVALIAR and perfil == "Aluno":
        st.markdown("<div style='position:relative'><input type='text' autofocus style='opacity:0; position:absolute; top:0; left:0; height:1px; width:1px;'></div>", unsafe_allow_html=True)
        st.header("Avaliação do curso")
        if "sucesso_redirecionamento" in st.session_state:
            st.success(st.session_state["sucesso_redirecionamento"])
            del st.session_state["sucesso_redirecionamento"]
        
        df_disc = ler_aba("Disciplinas")
        df_ciclos = ler_aba("Ciclos")
        df_entrancia = ler_aba("Entrancia_Turma")
        df_respostas = ler_aba("Respostas_Curso") 
        df_prof = ler_aba("Config_Professores") 
        
        df_ciclos['Data início'] = pd.to_datetime(df_ciclos['Data início'], format='%d/%m/%Y', errors='coerce')
        df_ciclos['Data fim'] = pd.to_datetime(df_ciclos['Data fim'], format='%d/%m/%Y', errors='coerce')
        ciclo_ativo = df_ciclos[(df_ciclos['Status'].str.lower() == 'ativo') | ((hoje >= df_ciclos['Data início']) & (hoje <= df_ciclos['Data fim']))]
        
        if ciclo_ativo.empty:
            st.warning("Não há nenhuma avaliação de curso aberta para hoje.")
            st.stop()
            
        id_ciclo = str(ciclo_ativo.iloc[0]['ID_Ciclo']).strip()
        nome_ciclo = str(ciclo_ativo.iloc[0]['Nome_Ciclo']).strip()
        id_disc = str(ciclo_ativo.iloc[0]['ID_Disciplina']).strip()
        nome_disc = str(df_disc[df_disc['ID_Disciplina'].astype(str).str.strip() == id_disc].iloc[0]['Nome_Disciplina'])
        
        if not df_respostas.empty:
            ja_avaliou = not df_respostas[(df_respostas['ID do Ciclo'].astype(str).str.strip() == id_ciclo) & 
                                          (df_respostas['Email do Aluno'].str.lower().str.strip() == aluno['email'])].empty
            if ja_avaliou:
                st.success(f"Você já enviou sua avaliação de curso para o **{nome_ciclo}**. Obrigado!")
                st.stop()
        
        meu_vinculo = df_entrancia[(df_entrancia['Email_Pessoal'].str.lower().str.strip() == aluno['email']) & (df_entrancia['ID_Disciplina'].astype(str).str.strip() == id_disc)]
        sala_aluno = str(meu_vinculo.iloc[0]['Sala']).strip() if not meu_vinculo.empty else ""
        
        professores = []
        prof_ciclo = df_prof[df_prof['ID_Ciclo'].str.lower().str.strip() == id_ciclo.lower()]
        for _, row in prof_ciclo.iterrows():
            tipo = str(row['Tipo']).strip()
            sala_prof = str(row['Sala']).strip()
            if tipo == "Orientador" and sala_prof != sala_aluno:
                continue
            professores.append(str(row['Professor']).strip())

        st.info(f"**Avaliação:** {nome_ciclo} | **Disciplina:** {nome_disc}")
        
        with st.form("form_curso"):
            st.write("**Métricas Gerais (0 a 5)**")
            col1, col2 = st.columns(2)
            ae = col1.radio("Auto Estudo", [0,1,2,3,4,5], index=None, horizontal=True)
            av = col2.radio("Aulas ao Vivo", [0,1,2,3,4,5], index=None, horizontal=True)
            ap = col1.radio("Aplicabilidade", [0,1,2,3,4,5], index=None, horizontal=True)
            su = col2.radio("Suporte", [0,1,2,3,4,5], index=None, horizontal=True)
            
            st.write("---")
            st.write("**Avaliação da Didática dos Professores (0 a 5)**")
            notas_prof = {}
            for p in professores:
                notas_prof[p] = st.radio(f"Professor(a): {p}", [0,1,2,3,4,5], index=None, horizontal=True)
                
            st.write("---")
            nps = st.slider("Em uma escala de 0 a 10, qual a probabilidade de recomendar este curso?", min_value=0, max_value=10, value=10)
            
            st.write("---")
            que_bom = st.text_area("Que Bom que... (Opcional)")
            que_pena = st.text_area("Que Pena que... (Opcional)")
            que_tal = st.text_area("Que Tal se... (Opcional)")
            
            if st.form_submit_button("Enviar Avaliação do Curso", type="primary", width="stretch"):
                valores_gerais = [ae, av, ap, su]
                valores_prof = list(notas_prof.values())
                
                if None in valores_gerais or None in valores_prof:
                    st.error("⚠️ Por favor, avalie todas as métricas e professores antes de enviar.")
                else:
                    with st.spinner("Salvando avaliação..."):
                        aba_resp = planilha.worksheet("Respostas_Curso")
                        agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
                        linhas = []
                        
                        itens_gerais = [("Auto Estudo", ae), ("Aulas ao Vivo", av), ("Aplicabilidade", ap), ("Suporte", su), 
                                        ("NPS", nps), ("Que Bom", que_bom), ("Que Pena", que_pena), ("Que Tal", que_tal)]
                        for item, val in itens_gerais:
                            linhas.append([agora, aluno['email'], aluno['nome'], nome_disc, nome_ciclo, id_ciclo, item, "", val])
                        
                        for p, val in notas_prof.items():
                            linhas.append([agora, aluno['email'], aluno['nome'], nome_disc, nome_ciclo, id_ciclo, "Didática Professor", p, val])
                            
                        aba_resp.append_rows(linhas)
                        registrar_log(aluno['email'], aluno['nome'], f"Enviou avaliação curso - {nome_ciclo}")
                        
                        limpar_cache_planilhas()
                        st.success("✅ Avaliação do curso salva!")
                        st.rerun()

    # ------------------------------------------
    # MÓDULO 3: MEUS RESULTADOS (BOLETIM)
    # ------------------------------------------
    elif menu == ROTA_RESULTADOS_PARES and perfil == "Aluno":
        st.header("Resultados de pares")
        
        df_disc = ler_aba("Disciplinas")
        df_ciclos = ler_aba("Ciclos")
        df_aval = ler_aba("Avaliacoes")
        
        disc_ativa = df_disc[df_disc['Status'].str.lower() == 'ativo']
        if disc_ativa.empty:
            st.warning("Não há disciplinas ativas para exibir resultados.")
            st.stop()
        id_disc = str(disc_ativa.iloc[0]['ID_Disciplina']).strip()
        nome_disc = str(disc_ativa.iloc[0]['Nome_Disciplina']).strip()
        
        df_ciclos['Data início'] = pd.to_datetime(df_ciclos['Data início'], format='%d/%m/%Y', errors='coerce')
        df_ciclos['Data fim'] = pd.to_datetime(df_ciclos['Data fim'], format='%d/%m/%Y', errors='coerce')
        ciclos_disc = df_ciclos[df_ciclos['ID_Disciplina'].astype(str).str.strip() == id_disc]
        ciclo_ativo_hoje = ciclos_disc[(ciclos_disc['Status'].str.lower() == 'ativo') | ((hoje >= ciclos_disc['Data início']) & (hoje <= ciclos_disc['Data fim']))]
        
        if not ciclo_ativo_hoje.empty:
            id_ativo = str(ciclo_ativo_hoje.iloc[0]['ID_Ciclo']).strip()
            nome_ativo = str(ciclo_ativo_hoje.iloc[0]['Nome_Ciclo']).strip()
            
            votou_ativo = not df_aval[(df_aval['ID_Ciclo'].astype(str).str.strip() == id_ativo) & 
                                      (df_aval['Email_Avaliador'].str.lower().str.strip() == aluno['email'])].empty
            
            if not votou_ativo:
                registrar_log(aluno['email'], aluno['nome'], f"Acesso bloqueado boletim ({nome_ativo})")
                st.error(f"**Acesso Bloqueado!** O {nome_ativo} está aberto. Você precisa registrar sua avaliação de pares antes de acessar as suas notas.")
                st.stop()
                
        registrar_log(aluno['email'], aluno['nome'], "Visualizou painel de resultados")
            
        st.info(f"**Disciplina Consolidada:** {nome_disc}")
        if ciclos_disc.empty:
            st.warning("Nenhum ciclo cadastrado.")
            st.stop()
            
        # ---------------------------------------------------------
        # INTELIGÊNCIA DE SELEÇÃO DO CICLO PADRÃO
        # ---------------------------------------------------------
        lista_nomes_ciclos = ciclos_disc['Nome_Ciclo'].tolist()
        idx_padrao_boletim = indice_ciclo_padrao(ciclos_disc, lista_nomes_ciclos)
        ciclo_boletim_sel = st.selectbox("Selecione o Ciclo para visualizar as notas:", lista_nomes_ciclos, index=idx_padrao_boletim)
        
        # Resgatamos a linha correspondente ao ciclo escolhido pelo usuário
        row_ciclo = ciclos_disc[ciclos_disc['Nome_Ciclo'] == ciclo_boletim_sel].iloc[0]
        
        # ---------------------------------------------------------
        # RENDERIZAÇÃO DOS RESULTADOS DO CICLO SELECIONADO
        # ---------------------------------------------------------
        st.markdown(f"### 📋 Detalhes do {ciclo_boletim_sel}")
        cid = str(row_ciclo['ID_Ciclo']).strip()
        cnome = str(row_ciclo['Nome_Ciclo']).strip()
        
        notas_ciclo = df_aval[df_aval['ID_Ciclo'].astype(str).str.strip() == cid]
        realizou = not notas_ciclo[notas_ciclo['Email_Avaliador'].str.lower().str.strip() == aluno['email']].empty
        multiplicador = 2 if realizou else 1
        
        recebidas = notas_ciclo[notas_ciclo['Email_Avaliado'].str.lower().str.strip() == aluno['email']]
        
        if recebidas.empty:
            st.write("⏳ Os resultados para este ciclo ainda não foram processados ou você não recebeu avaliações.")
        else:
            notas_numericas = pd.to_numeric(recebidas['Nota'], errors='coerce').dropna()
            media = notas_numericas.mean() if not notas_numericas.empty else 0
            nota_final = media * multiplicador
            
            c1, c2 = st.columns(2)
            c1.metric("Média dos Pares", f"{media:.1f}")
            c2.metric("Nota Final Recebida", f"{nota_final:.1f}", f"Multiplicador x{multiplicador}")
            
            if realizou:
                st.success("✅ Você realizou a avaliação dos seus colegas. Sua média foi multiplicada por 2.")
            else:
                st.error("❌ Você não enviou sua avaliação de pares. Sua nota sofreu penalidade (Multiplicador x1).")
                
            st.write("---")
            st.write("**Feedbacks Recebidos no Ciclo:**")
            if 'Moderação' in recebidas.columns:
                recebidas = recebidas[recebidas['Moderação'].str.lower().str.strip() != 'ignorar']
            
            comentarios = recebidas['Comentário'].dropna().astype(str)
            comentarios = comentarios[comentarios.str.strip() != ""]
            
            if comentarios.empty:
                st.write("*Nenhum feedback em texto registrado para você neste ciclo.*")
            else:
                for c in comentarios:
                    st.info(f'"{c}"')

    # ------------------------------------------
    # MÓDULO DO PROFESSOR: PAINEL GERAL
    # ------------------------------------------
    elif menu == ROTA_PARES_ACOMP and perfil == "Professor" and professor_e_orientador(aluno):
        st.header("Pares — acompanhamento")
        
        df_disc = ler_aba("Disciplinas")
        df_ciclos = ler_aba("Ciclos")
        df_entrancia = ler_aba("Entrancia_Turma")
        df_aval = ler_aba("Avaliacoes")
        
        lista_disciplinas = df_disc['Nome_Disciplina'].unique().tolist()
        idx_padrao_disc = 0 
        
        coluna_status = 'Status'
        
        df_ativa = df_disc[df_disc[coluna_status].astype(str).str.strip().str.lower().isin(['ativa', 'ativo', 'sim', 's'])]
        if not df_ativa.empty:
            disc_ativa_nome = df_ativa.iloc[0]['Nome_Disciplina']
            if disc_ativa_nome in lista_disciplinas:
                idx_padrao_disc = lista_disciplinas.index(disc_ativa_nome)

        disc_sel = st.selectbox("Selecione a Disciplina:", lista_disciplinas, index=idx_padrao_disc, key="geral_disc_sel")
        id_disc_sel = str(df_disc[df_disc['Nome_Disciplina'] == disc_sel].iloc[0]['ID_Disciplina']).strip()
        ciclos_filtrados = df_ciclos[df_ciclos['ID_Disciplina'].astype(str).str.strip() == id_disc_sel]
        lista_ciclos = ciclos_filtrados['Nome_Ciclo'].unique().tolist()
        
        if not lista_ciclos:
            st.warning("Nenhum ciclo cadastrado para esta disciplina.")
            st.stop()
            
        # ---------------------------------------------------------
        # SUPORTE AO FILTRO "TODOS" + SELEÇÃO SE INICIANDO NO CICLO ATUAL
        # ---------------------------------------------------------
        opcoes_ciclos = ["Todos"] + lista_ciclos
        idx_padrao_ciclo = indice_ciclo_padrao(ciclos_filtrados, lista_ciclos) + 1
        ciclo_sel = st.selectbox("Selecione o Ciclo:", opcoes_ciclos, index=idx_padrao_ciclo, key="geral_ciclo_sel")
        
        # Mapeamento do escopo de IDs de ciclos alvos baseados na seleção
        if ciclo_sel == "Todos":
            ids_ciclo_alvo = ciclos_filtrados['ID_Ciclo'].astype(str).str.strip().tolist()
            ciclos_alvo = ciclos_filtrados.copy()
        else:
            ids_ciclo_alvo = [str(ciclos_filtrados[ciclos_filtrados['Nome_Ciclo'] == ciclo_sel].iloc[0]['ID_Ciclo']).strip()]
            ciclos_alvo = ciclos_filtrados[ciclos_filtrados['Nome_Ciclo'] == ciclo_sel]
        
        # ---------------------------------------------------------
        # FILTROS ADICIONAIS (SALA, GRUPO, NOME)
        # ---------------------------------------------------------
        entrancia_disc = df_entrancia[df_entrancia['ID_Disciplina'].astype(str).str.strip() == id_disc_sel]
        sala_sel = st.selectbox("Selecione a Sala:", ["Todas"] + sorted(entrancia_disc['Sala'].dropna().unique().astype(str).tolist()))
        
        def chave_ordenacao_geral(x):
            try:
                return (0, float(x)) 
            except ValueError:
                return (1, str(x))   

        lista_grupos_geral = sorted(entrancia_disc['Grupo'].dropna().unique().astype(str).tolist(), key=chave_ordenacao_geral)
        grupo_sel = st.selectbox("Selecione o Grupo/Turma:", ["Todos"] + lista_grupos_geral)
        nome_busca = st.text_input("Buscar Aluno por Nome:")
        
        df_alunos_esperados = entrancia_disc.copy()
        if sala_sel != "Todas":
            df_alunos_esperados = df_alunos_esperados[df_alunos_esperados['Sala'].astype(str) == sala_sel]
        if grupo_sel != "Todos":
            df_alunos_esperados = df_alunos_esperados[df_alunos_esperados['Grupo'].astype(str) == grupo_sel]
        if nome_busca:
            df_alunos_esperados = df_alunos_esperados[df_alunos_esperados['Nome_Completo'].str.contains(nome_busca, case=False, na=False)]
            
        aba_pendentes, aba_resultados = st.tabs(["⏳ Alunos Pendentes", "📊 Prévia de Resultados"])
        
        # ---------------------------------------------------------
        # ABA PENDENTES (Retirada a coluna E-mail)
        # ---------------------------------------------------------
        with aba_pendentes:
            st.subheader("Alunos que ainda não enviaram a avaliação")
            
            df_pendentes_list = []
            for _, c_row in ciclos_alvo.iterrows():
                cid = str(c_row['ID_Ciclo']).strip()
                cnome = str(c_row['Nome_Ciclo']).strip()
                
                ja_votaram = df_aval[df_aval['ID_Ciclo'].astype(str).str.strip() == cid]['Email_Avaliador'].str.lower().str.strip().unique().tolist()
                df_p = df_alunos_esperados[~df_alunos_esperados['Email_Pessoal'].str.lower().str.strip().isin(ja_votaram)].copy()
                df_p['Ciclo'] = cnome
                df_pendentes_list.append(df_p)
                
            if df_pendentes_list:
                df_pendentes = pd.concat(df_pendentes_list, ignore_index=True)
            else:
                df_pendentes = pd.DataFrame()
            
            if df_pendentes.empty:
                st.success("🎉 Nenhum aluno pendente para os filtros selecionados!")
            else:
                # REQUISITO 1: Removido 'Email_Pessoal' do dataframe visual exposto na tela
                rel_pendentes = df_pendentes[['Nome_Completo', 'Ciclo', 'Sala', 'Grupo']].rename(columns={'Nome_Completo': 'Nome'})
                st.write(f"Total pendente: **{len(rel_pendentes)}**")
                st.dataframe(rel_pendentes, width="stretch")
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    # Mantemos o e-mail no Excel baixado para controle de envio/cobrança do professor
                    df_pendentes[['Nome_Completo', 'Email_Pessoal', 'Ciclo', 'Sala', 'Grupo']].to_excel(writer, index=False, sheet_name='Pendentes')
                st.download_button("📥 Baixar Lista de Pendentes (Excel)", data=buffer.getvalue(), file_name=f"pendentes_{ciclo_sel}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                
        # ---------------------------------------------------------
        # ABA RESULTADOS (Utilizando a coluna nativa 'Ciclo')
        # ---------------------------------------------------------
        with aba_resultados:
            st.subheader("Médias parciais calculadas para os alunos")
            votos_ciclo = df_aval[df_aval['ID_Ciclo'].astype(str).str.strip().isin(ids_ciclo_alvo)].copy()
            
            if votos_ciclo.empty:
                st.info("Nenhum voto registrado para os critérios selecionados.")
            else:
                votos_ciclo['Nota'] = pd.to_numeric(votos_ciclo['Nota'], errors='coerce')
                
                # Agrupamento dinâmico que funciona tanto para um ciclo individual quanto para "Todos"
                df_medias = votos_ciclo.groupby(['Email_Avaliado', 'Ciclo']).agg(
                    Nome=('Nome_Avaliado', 'first'),
                    Grupo=('Grupo', 'first'),
                    Media_Pares=('Nota', 'mean'),
                    Votos_Recebidos=('Nota', 'count')
                ).reset_index()
                
                df_res_filtrados = df_medias[df_medias['Email_Avaliado'].str.lower().str.strip().isin(df_alunos_esperados['Email_Pessoal'].str.lower().str.strip())]
                
                if df_res_filtrados.empty:
                    st.warning("Nenhum resultado para os filtros aplicados.")
                else:
                    mapa_ciclo_id = dict(
                        zip(
                            ciclos_filtrados['Nome_Ciclo'].astype(str),
                            ciclos_filtrados['ID_Ciclo'].astype(str).str.strip(),
                        )
                    )
                    votaram_por_ciclo = {}
                    for cid in ids_ciclo_alvo:
                        emails = (
                            votos_ciclo[votos_ciclo['ID_Ciclo'].astype(str).str.strip() == cid]['Email_Avaliador']
                            .astype(str)
                            .str.lower()
                            .str.strip()
                            .unique()
                            .tolist()
                        )
                        votaram_por_ciclo[cid] = set(emails)

                    df_res_filtrados = df_res_filtrados.copy()
                    df_res_filtrados['ID_Ciclo'] = df_res_filtrados['Ciclo'].map(mapa_ciclo_id)

                    def _detalhar_pares(row):
                        cid = str(row['ID_Ciclo']).strip()
                        email = str(row['Email_Avaliado']).lower().strip()
                        realizou = email in votaram_por_ciclo.get(cid, set())
                        nota_final = calcular_nota_pares(row['Media_Pares'], realizou)
                        return pd.Series({
                            'Enviou': 'Sim' if realizou else 'Não',
                            'Nota_Final_Pares': round(nota_final, 1),
                        })

                    df_res_filtrados[['Enviou', 'Nota_Final_Pares']] = df_res_filtrados.apply(_detalhar_pares, axis=1)
                    df_res_filtrados['Media_Pares'] = df_res_filtrados['Media_Pares'].round(1)
                    
                    rel_resultados = df_res_filtrados[
                        ['Nome', 'Ciclo', 'Grupo', 'Media_Pares', 'Enviou', 'Nota_Final_Pares']
                    ].rename(columns={
                        'Media_Pares': 'Nota dos pares',
                        'Nota_Final_Pares': 'Nota final (pares)',
                    }).sort_values(['Ciclo', 'Nome'])
                    st.dataframe(rel_resultados, width="stretch")
                    
                    buffer_res = io.BytesIO()
                    with pd.ExcelWriter(buffer_res, engine='openpyxl') as writer:
                        df_res_filtrados[
                            ['Nome', 'Email_Avaliado', 'Ciclo', 'Grupo', 'Media_Pares', 'Enviou', 'Nota_Final_Pares', 'Votos_Recebidos']
                        ].rename(columns={
                            'Media_Pares': 'Nota dos pares',
                            'Nota_Final_Pares': 'Nota final (pares)',
                        }).to_excel(writer, index=False, sheet_name='Resultados')
                    st.download_button("📥 Baixar Resultados Parciais (Excel)", data=buffer_res.getvalue(), file_name=f"resultados_{ciclo_sel}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    
    # =========================================================
    # MÓDULO DO PROFESSOR: MODERAÇÃO DE COMENTÁRIOS
    # =========================================================
    elif menu == ROTA_MODERACAO and perfil == "Professor" and professor_e_orientador(aluno):
        st.header("Moderação de comentários")
        st.write("Por padrão, todos os feedbacks nascem **Aprovados** e visíveis aos alunos. Use as ações abaixo para ocultar (Ignorar) ou reativar comentários.")
        
        df_disc = ler_aba("Disciplinas")
        df_ciclos = ler_aba("Ciclos")
        df_turmas = ler_aba("Entrancia_Turma")
        df_aval = ler_aba("Avaliacoes")
        
        df_aval['Linha_Planilha'] = df_aval.index + 2

        lista_disciplinas = df_disc['Nome_Disciplina'].unique().tolist()
        idx_padrao_disc = 0 
        
        coluna_status = 'Status' if 'Status' in df_disc.columns else df_disc.columns[-1]
        
        df_ativa = df_disc[df_disc[coluna_status].astype(str).str.strip().str.lower().isin(['ativa', 'ativo', 'sim', 's'])]
        if not df_ativa.empty:
            disc_ativa_nome = df_ativa.iloc[0]['Nome_Disciplina']
            if disc_ativa_nome in lista_disciplinas:
                idx_padrao_disc = lista_disciplinas.index(disc_ativa_nome)
        
        st.markdown("### 🔍 Filtros de Seleção")
        c_filt1, c_filt2 = st.columns(2)
        
        with c_filt1:
            disc_sel = st.selectbox("Selecione a Disciplina:", lista_disciplinas, index=idx_padrao_disc, key="mod_disc_sel")
            id_disc_sel = str(df_disc[df_disc['Nome_Disciplina'] == disc_sel].iloc[0]['ID_Disciplina']).strip()
            
        with c_filt2:
            ciclos_filtrados = df_ciclos[df_ciclos['ID_Disciplina'].astype(str).str.strip() == id_disc_sel]
            lista_ciclos = ciclos_filtrados['Nome_Ciclo'].unique().tolist()
            
            if not lista_ciclos:
                st.warning("Nenhum ciclo cadastrado para esta disciplina.")
                st.stop()
                
            opcoes_ciclos_mod = ["Todos"] + lista_ciclos
            idx_padrao_ciclo_mod = indice_ciclo_padrao(ciclos_filtrados, lista_ciclos) + 1
            ciclo_sel = st.selectbox("Selecione o Ciclo:", opcoes_ciclos_mod, index=idx_padrao_ciclo_mod, key="mod_ciclo_sel")
            
            if ciclo_sel == "Todos":
                ids_ciclo_alvo = ciclos_filtrados['ID_Ciclo'].astype(str).str.strip().tolist()
            else:
                ids_ciclo_alvo = [str(ciclos_filtrados[ciclos_filtrados['Nome_Ciclo'] == ciclo_sel].iloc[0]['ID_Ciclo']).strip()]
        
        c_filt3, c_filt4 = st.columns(2)
        
        with c_filt3:
            entrancia_disc = df_turmas[df_turmas['ID_Disciplina'].astype(str).str.strip() == id_disc_sel]
            salas_disponiveis = ["Todas"] + sorted(entrancia_disc['Sala'].dropna().unique().astype(str).tolist())
            sala_sel = st.selectbox("Filtrar por Sala:", salas_disponiveis, key="mod_sala_sel")
            
        with c_filt4:
            def chave_ordenacao_grupo(x):
                try:
                    return (0, float(x))
                except ValueError:
                    return (1, str(x))

            lista_grupos_ordenada = sorted(entrancia_disc['Grupo'].dropna().unique().astype(str).tolist(), key=chave_ordenacao_grupo)
            grupos_disponiveis = ["Todos"] + lista_grupos_ordenada
            grupo_sel = st.selectbox("Filtrar por Grupo:", grupos_disponiveis, key="mod_grupo_sel")

        nome_busca_mod = st.text_input("🔍 Buscar Feedback por Nome do Aluno (Avaliador ou Avaliado):", key="mod_nome_busca")

        # ---------------------------------------------------------
        # FILTRAGEM DOS COMENTÁRIOS (BUGFIX DO NOME DO CICLO ADICIONADO AQUI)
        # ---------------------------------------------------------
        df_comentarios = df_aval[
            (df_aval['ID_Ciclo'].astype(str).str.strip().isin(ids_ciclo_alvo)) & 
            (df_aval['Comentário'].astype(str).str.strip() != "")
        ].copy()
        
        if df_comentarios.empty:
            st.info("Nenhum comentário registrado para a seleção realizada.")
        else:
            # BUGFIX: Cruza com os ciclos para obter o 'Nome_Ciclo' antes do mapeamento visual
            df_ciclos_nomes = df_ciclos[['ID_Ciclo', 'Nome_Ciclo']].drop_duplicates().copy()
            df_ciclos_nomes['ID_Ciclo'] = df_ciclos_nomes['ID_Ciclo'].astype(str).str.strip()
            df_comentarios['ID_Ciclo'] = df_comentarios['ID_Ciclo'].astype(str).str.strip()
            df_comentarios = pd.merge(df_comentarios, df_ciclos_nomes, on='ID_Ciclo', how='left')

            df_turmas_mapping = entrancia_disc[['Email_Pessoal', 'Sala', 'Grupo']].drop_duplicates().rename(columns={'Email_Pessoal': 'Email_Avaliado'})
            
            if 'Sala' in df_comentarios.columns: df_comentarios.drop(columns=['Sala'], inplace=True)
            if 'Grupo' in df_comentarios.columns: df_comentarios.drop(columns=['Grupo'], inplace=True)
                
            df_comentarios = pd.merge(df_comentarios, df_turmas_mapping, on='Email_Avaliado', how='left')
            
            if sala_sel != "Todas":
                df_comentarios = df_comentarios[df_comentarios['Sala'].astype(str).str.strip() == sala_sel]
            if grupo_sel != "Todos":
                df_comentarios = df_comentarios[df_comentarios['Grupo'].astype(str).str.strip() == grupo_sel]
                
            if nome_busca_mod:
                cond_nome_reg = df_comentarios['Nome'].astype(str).str.contains(nome_busca_mod, case=False, na=False) if 'Nome' in df_comentarios.columns else False
                cond_aval_real = df_comentarios['Nome_Avaliador'].astype(str).str.contains(nome_busca_mod, case=False, na=False) if 'Nome_Avaliador' in df_comentarios.columns else False
                cond_avaliado = df_comentarios['Nome_Avaliado'].astype(str).str.contains(nome_busca_mod, case=False, na=False) if 'Nome_Avaliado' in df_comentarios.columns else False
                df_comentarios = df_comentarios[cond_nome_reg | cond_aval_real | cond_avaliado]

            # ---------------------------------------------------------
            # EXIBIÇÃO EM FORMATO DE CARDS
            # ---------------------------------------------------------
            st.markdown("### 💬 Lista de Feedbacks Encontrados")
            st.write(f"Total nesta seleção: **{len(df_comentarios)}**")
            st.markdown("---")
            
            if df_comentarios.empty:
                st.warning("Nenhum comentário corresponde aos filtros aplicados.")
            else:
                for idx, row in df_comentarios.iterrows():
                    linha_real_gspread = int(row['Linha_Planilha'])
                    status_atual = str(row.get('Moderação', '')).strip().lower()
                    is_ignorado = (status_atual == 'ignorar')
                    
                    sala_card = str(row.get('Sala', '-'))
                    grupo_card = str(row.get('Grupo', '-'))
                    ciclo_card = str(row.get('Nome_Ciclo', '-')) # Agora vai capturar corretamente ex: "Ciclo 1"
                    avaliador = str(row.get('Nome', row.get('Nome_Avaliador', 'Avaliador')))
                    avaliado = str(row.get('Nome_Avaliado', 'Avaliado'))
                    comentario_texto = str(row.get('Comentário', ''))
                    
                    with st.container():
                        col_corpo, col_acao = st.columns([4, 1])
                        
                        with col_corpo:
                            st.markdown(f"**{ciclo_card} • Sala {sala_card} • Grupo {grupo_card}** | `{avaliador}` ➔ `{avaliado}`")
                            st.markdown(f"➔ *\"{comentario_texto}\"*")
                        
                        with col_acao:
                            if is_ignorado:
                                st.error("🚫 Ocultado")
                                if st.button("🔄 Aprovar", key=f"btn_aprov_{linha_real_gspread}", width="stretch"):
                                    with st.spinner("Atualizando..."):
                                        aba_real = planilha.worksheet("Avaliacoes")
                                        aba_real.update_cell(linha_real_gspread, 13, "Aprovado")
                                        limpar_cache_planilhas()
                                        st.toast("Status alterado para Aprovado!")
                                        st.rerun()
                            else:
                                st.success("✅ Visível")
                                if st.button("🗑️ Ignorar", key=f"btn_ign_{linha_real_gspread}", width="stretch"):
                                    with st.spinner("Atualizando..."):
                                        aba_real = planilha.worksheet("Avaliacoes")
                                        aba_real.update_cell(linha_real_gspread, 13, "Ignorar")
                                        limpar_cache_planilhas()
                                        st.toast("Status alterado para Ignorar!")
                                        st.rerun()
                                        
                    st.markdown("<hr style='margin: 0.5em 0px; border-color: rgba(49, 51, 63, 0.2);'>", unsafe_allow_html=True)
                   
    # =========================================================
    # NOVAS TELAS: MINHA FREQUÊNCIA (ALUNO)
    # =========================================================
    elif menu == ROTA_FREQ_AULAS and perfil == "Aluno":
        # 1. Puxar qual é a disciplina do momento e registrar o log
        id_ativa, nome_ativa = obter_disciplina_ativa()
        registrar_log_acesso(aluno['email'], aluno['nome'], "Visualizou Frequência")
        
        st.header(f"Frequência nas aulas: {nome_ativa}")
        try:
            dfs_presenca = carregar_base_presenca()
            df_frequencia = calcular_matriz_presencas(aluno['email'], dfs_cache=dfs_presenca)
        except Exception as exc:
            if "429" in str(exc):
                st.warning(
                    "O Google Sheets está temporariamente sobrecarregado. "
                    "Aguarde cerca de 1 minuto e recarregue a página."
                )
                st.stop()
            raise
        
        # Filtra para mostrar APENAS os dados da disciplina ativa
        if not df_frequencia.empty and id_ativa:
            df_frequencia = df_frequencia[df_frequencia['ID_Disciplina'] == id_ativa]
            
        if df_frequencia.empty:
            st.warning("Nenhum calendário de aulas configurado para esta disciplina atual.")
        else:
            df_vivido = df_frequencia[df_frequencia['Status_Tecnico'] != 'Futuro']
            df_futuro = df_frequencia[df_frequencia['Status_Tecnico'] == 'Futuro']
            
            total_vivido = len(df_vivido)
            presencas_vividas = len(df_vivido[df_vivido['Status_Aluno'] == 'Presente'])
            pct_atual = (presencas_vividas / total_vivido * 100) if total_vivido > 0 else 100.0
            
            total_geral = len(df_frequencia)
            presencas_projetadas = presencas_vividas + len(df_futuro)
            pct_projetada = (presencas_projetadas / total_geral * 100) if total_geral > 0 else 100.0
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Frequência Atual (Realizada)", f"{pct_atual:.1f}%")
            c2.metric("Frequência Projetada*", f"{pct_projetada:.1f}%")
            
            if pct_projetada < 75.0: 
                c3.error("⚠️ Risco de Reprovação (< 75%)")
            else: 
                c3.success("✅ Situação Regular")
            
            st.caption("ℹ️ *A frequência projetada considera uma presença em 100% das próximas aulas.*")
                
            st.subheader("📋 Histórico Detalhado")
            df_visao = df_vivido[['Data', 'Status_Aluno']].copy()
            df_visao['Data'] = df_visao['Data'].dt.strftime('%d/%m/%Y')
            
            # Adiciona os Emojis visualmente limpos
            df_visao['Situação'] = df_visao['Status_Aluno'].apply(lambda x: "✅ Presente" if x == "Presente" else "❌ Falta")
            
            # Mantém apenas as colunas Data e Situação (Remove Minutos e Disciplina)
            st.dataframe(df_visao[['Data', 'Situação']], width="stretch", hide_index=True)

    # =========================================================
    # NOVAS TELAS: MINHAS DAILIES (ALUNO)
    # =========================================================
    elif menu == ROTA_FREQ_DAILIES and perfil == "Aluno":
        id_ativa, nome_ativa = obter_disciplina_ativa()
        registrar_log_acesso(aluno['email'], aluno['nome'], "Visualizou Dailies")
        
        st.header(f"Participação nas dailies: {nome_ativa}")
        try:
            dfs_presenca = carregar_base_presenca()
            df_dailies = calcular_matriz_dailies(aluno['email'], dfs_cache=dfs_presenca)
        except Exception as exc:
            if "429" in str(exc):
                st.warning(
                    "O Google Sheets está temporariamente sobrecarregado. "
                    "Aguarde cerca de 1 minuto e recarregue a página."
                )
                st.stop()
            raise
        
        if not df_dailies.empty and id_ativa:
            df_dailies = df_dailies[df_dailies['ID_Disciplina'] == id_ativa]
            
        if df_dailies.empty:
            st.warning("Nenhuma Daily agendada para esta disciplina atual.")
        else:
            df_vivido = df_dailies[df_dailies['Status_Tecnico'] != 'Futuro']
            df_futuro = df_dailies[df_dailies['Status_Tecnico'] == 'Futuro']
            
            total_vivido = len(df_vivido)
            pontos = len(df_vivido[df_vivido['Status_Aluno'] == 'Presente'])
            pct_atual = (pontos / total_vivido * 100) if total_vivido > 0 else 100.0
            
            total_geral = len(df_dailies)
            pontos_projetados = pontos + len(df_futuro)
            pct_projetada = (pontos_projetados / total_geral * 100) if total_geral > 0 else 100.0
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Nota Atual de Dailies", f"{pct_atual:.1f}%")
            c2.metric("Projeção de Nota Dailies*", f"{pct_projetada:.1f}%")
            if pct_projetada < 75.0: c3.error("⚠️ Baixa Participação")
            else: c3.success("✅ Ótima Participação")

            st.caption("ℹ️ *A nota projetada considera uma presença em 100% das próximas reuniões de orientação de projetos.*")
            
            st.subheader("📋 Histórico")
            df_visao = df_vivido[['Data', 'Status_Aluno']].copy()
            df_visao['Data'] = df_visao['Data'].dt.strftime('%d/%m/%Y')
            df_visao['Presença Reunião'] = df_visao['Status_Aluno'].apply(lambda x: "✅ Participou" if x == "Presente" else "❌ Faltou")
            
            st.dataframe(df_visao[['Data', 'Presença Reunião']], width="stretch", hide_index=True)

    # =========================================================
    # NOVAS TELAS: CONTROLE DE FREQUÊNCIA (PROFESSOR & SECRETARIA)
    # =========================================================
    elif menu == ROTA_FREQ_CONTROLE and (
        perfil == "Secretaria" or (perfil == "Professor" and professor_e_orientador(aluno))
    ):
        st.header("Controle de frequência")
        df_entrancia = ler_aba("Entrancia_Turma")
        df_disciplinas = ler_aba("Disciplinas")
        df_alunos_base = ler_aba("Base_Alunos") # Puxa para pegar a Turma_Ingresso
        
        lista_opcoes = df_disciplinas.apply(lambda x: f"{x['ID_Disciplina']} - {x['Nome_Disciplina']}", axis=1).tolist()
        idx_ativo = 0
        ativas = df_disciplinas[df_disciplinas['Status'] == 'Ativo']
        if not ativas.empty:
            id_ativo = ativas.iloc[0]['ID_Disciplina']
            for i, val in enumerate(lista_opcoes):
                if val.startswith(id_ativo): idx_ativo = i; break
                    
        disc_sel = st.selectbox("Selecione a Disciplina para análise:", lista_opcoes, index=idx_ativo)
        id_disciplina_sel = disc_sel.split(" - ")[0]
        
        # Filtra os alunos da disciplina e traz a coluna Turma_Ingresso
        alunos_turma = df_entrancia[df_entrancia['ID_Disciplina'] == id_disciplina_sel].copy()
        alunos_turma = pd.merge(alunos_turma, df_alunos_base[['Email_Pessoal', 'Turma_Ingresso']], on='Email_Pessoal', how='left')

        with st.spinner("Compilando frequência..."):
            memoria_cache = carregar_base_presenca()
            memoria_cache["entrancia"] = df_entrancia
            df_resumo, df_raw = compilar_grid_frequencia(
                id_disciplina_sel, alunos_turma, memoria_cache
            )

        if not df_raw.empty:
            datas_unicas = df_raw[['Data_Sort', 'Data_Visual']].drop_duplicates().sort_values('Data_Sort')
            colunas_datas_ordenadas = datas_unicas['Data_Visual'].tolist()
            
            df_pivot = df_raw.pivot(index="Email_Cru", columns="Data_Visual", values="Status").reset_index().fillna("-")
            df_final = pd.merge(df_resumo, df_pivot, on="Email_Cru", how="left")
            
            def ordenacao_natural(lista):
                converte = lambda texto: int(texto) if str(texto).isdigit() else str(texto).lower()
                chave = lambda chave: [converte(c) for c in re.split('([0-9]+)', str(chave))]
                return sorted(lista, key=chave)

            turmas_opcoes = ordenacao_natural(df_final['Turma'].unique())
            salas_opcoes = ordenacao_natural(df_final['Sala'].unique())
            grupos_opcoes = ordenacao_natural(df_final['Grupo'].unique())

            st.markdown("---")
            c1, c2, c3 = st.columns(3)
            turma_filtro = c1.multiselect("Filtrar por Turma:", turmas_opcoes)
            sala_filtro = c2.multiselect("Filtrar por Sala:", salas_opcoes)
            grupo_filtro = c3.multiselect("Filtrar por Grupo:", grupos_opcoes)
            
            c4, c5 = st.columns(2)
            nome_busca = c4.text_input("Buscar por Nome do Aluno:")
            faixa_projetada = c5.slider("Filtrar por % Projetada:", min_value=0.0, max_value=100.0, value=(0.0, 100.0), format="%.0f%%")
            
            if turma_filtro: df_final = df_final[df_final['Turma'].isin(turma_filtro)]
            if sala_filtro: df_final = df_final[df_final['Sala'].isin(sala_filtro)]
            if grupo_filtro: df_final = df_final[df_final['Grupo'].isin(grupo_filtro)]
            if nome_busca: df_final = df_final[df_final['Nome'].str.contains(nome_busca, case=False, na=False)]
            
            df_final = df_final[(df_final['% Projetado'] >= faixa_projetada[0]) & (df_final['% Projetado'] <= faixa_projetada[1])]
            
            if df_final.empty:
                st.warning("Nenhum aluno encontrado com esses filtros.")
            else:
                df_final = df_final.set_index("Nome")
                cols_fixas = ["Turma", "Sala", "Grupo", "% Realizado", "% Projetado"]
                cols_finais = cols_fixas + [c for c in colunas_datas_ordenadas if c in df_final.columns]
                df_final = df_final[cols_finais]
                
                # --- EXPORTAÇÃO EXCEL ---
                st.markdown("<br>", unsafe_allow_html=True)
                df_excel = df_final.copy()
                # Substitui os ícones por Letras
                df_excel = df_excel.replace({"✅": "P", "❌": "F", "⏳": "C", "✏️": "A"})
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    df_excel.to_excel(writer, index=True, sheet_name='Frequencia')
                
                col_exp, _ = st.columns([1, 2])
                col_exp.download_button(
                    label="📥 Exportar Dados para Excel (.xlsx)",
                    data=buffer.getvalue(),
                    file_name=f"Controle_Frequencia_{id_disciplina_sel}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch"
                )
                # -------------------------

                config_colunas = {
                    "% Realizado": st.column_config.NumberColumn("% Realizado", format="%.1f %%"),
                    "% Projetado": st.column_config.NumberColumn("% Projetado", format="%.1f %%")
                }
                st.caption("Legenda na tela: ✅ Presente | ❌ Falta | ⏳ Conectado (<30min) | ✏️ Ajuste Manual")
                st.dataframe(df_final, width="stretch", column_config=config_colunas)
        else:
            st.info("Nenhuma aula registrada ainda para esta disciplina.")

    # =========================================================
    # MÓDULO ALUNO: MINHAS NOTAS
    # =========================================================
    elif menu == ROTA_MINHAS_NOTAS and perfil == "Aluno":
        aluno_minhas_notas.render(aluno)

    # =========================================================
    # MÓDULO PROFESSOR: COMPONENTES DE AVALIAÇÃO
    # =========================================================
    elif menu == ROTA_COORD_COMPONENTES and perfil == "Professor" and usuario_e_coordenador(aluno) and st.session_state.get("modo_coordenador"):
        prof_config_componentes.render(aluno)

    # =========================================================
    # MÓDULO COORDENADOR: CONFIGURAÇÕES
    # =========================================================
    elif menu == ROTA_COORD_CONFIG and perfil == "Professor" and usuario_e_coordenador(aluno) and st.session_state.get("modo_coordenador"):
        prof_coordenador.render(aluno)

    # =========================================================
    # MÓDULO COORDENADOR: CONFERÊNCIA DE ENTREGAS
    # =========================================================
    elif menu == ROTA_COORD_CONFERIR and perfil == "Professor" and usuario_e_coordenador(aluno) and st.session_state.get("modo_coordenador"):
        prof_coordenador_entregas.render(aluno)

    # =========================================================
    # MÓDULO PROFESSOR: AVALIAÇÃO DO ORIENTADOR
    # =========================================================
    elif menu == ROTA_ORIENTADOR and perfil == "Professor" and professor_e_orientador(aluno):
        prof_avaliacao_orientador.render(aluno)

    # =========================================================
    # MÓDULO PROFESSOR: AVALIAÇÃO DE ENTREGAS
    # =========================================================
    elif menu == ROTA_LANCAR_BANCA and perfil == "Professor":
        prof_avaliacao_grupo.render(aluno)

    elif menu == ROTA_LIBERAR_NOTAS and perfil == "Professor" and pode_gerenciar_liberacao_notas(aluno):
        prof_liberacao_notas.render(aluno)

    # =========================================================
    # MÓDULO PROFESSOR: IMPORTAR CANVAS
    # =========================================================
    elif menu == ROTA_IMPORT_CANVAS and perfil == "Professor" and professor_e_orientador(aluno):
        prof_import_canvas.render(aluno)