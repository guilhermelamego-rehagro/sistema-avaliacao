import streamlit as st
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import io

# 1. Configurações Iniciais da Página
st.set_page_config(page_title="Portal de Avaliações - Rehagro", page_icon="🎓", layout="centered")

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

# 2. Conexão com o Google Sheets
@st.cache_resource(ttl=600)
def conectar_planilha():
    escopo = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    info_credenciais = st.secrets["gcp_service_account"]
    credenciais = ServiceAccountCredentials.from_json_keyfile_dict(info_credenciais, escopo)
    cliente = gspread.authorize(credenciais)
    return cliente.open_by_key(st.secrets["planilhas"]["id_teste"])

# Conecta ao banco de dados (Variável Global)
planilha = conectar_planilha()

# 3. Leitura com Cache
@st.cache_data(ttl=300)
def ler_aba(nome_aba):
    return pd.DataFrame(planilha.worksheet(nome_aba).get_all_records())

def registrar_log(email, nome, acao):
    try:
        aba_log = planilha.worksheet("Log_Acessos")
        agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
        aba_log.append_row([agora, email, nome, acao])
    except:
        pass

# Interface Lateral
st.sidebar.image("logo.png", width=200) 
st.sidebar.title("Menu do Sistema")

# Inicializa sessão
if "aluno_logado" not in st.session_state:
    st.session_state["aluno_logado"] = None

# ==========================================
# TELA DE LOGIN (EM DUAS ETAPAS)
# ==========================================
if not st.session_state["aluno_logado"]:
    st.title("Bem-vindo ao Portal de Avaliações")
    
    if "etapa_login" not in st.session_state:
        st.session_state["etapa_login"] = "email"
    if "dados_usuario_temp" not in st.session_state:
        st.session_state["dados_usuario_temp"] = None

    # ---- ETAPA 1: DIGITAR O E-MAIL ----
    if st.session_state["etapa_login"] == "email":
        st.write("Digite seu e-mail cadastrado para acessar seus módulos.")
        with st.form("form_login_email"):
            email_input = st.text_input("E-mail Rehagro:", key="input_email_usuario")
            avancar = st.form_submit_button("Avançar", type="primary", use_container_width=True)
        
        if avancar:
            if email_input:
                email_formatado = email_input.strip().lower()
                
                with st.spinner("Verificando usuário..."):
                    df_alunos = ler_aba("Base_Alunos")
                    aluno = df_alunos[
                        (df_alunos['Email_Pessoal'].str.strip().str.lower() == email_formatado) & 
                        (df_alunos['Status_Geral'].str.strip().str.lower() == 'ativo')
                    ]
                    
                    if aluno.empty:
                        st.error("E-mail não encontrado ou cadastro inativo.")
                    else:
                        perfil_usuario = str(aluno.iloc[0].get('Perfil', 'Aluno')).strip()
                        
                        if perfil_usuario == "Professor":
                            st.session_state["dados_usuario_temp"] = aluno.iloc[0].to_dict()
                            st.session_state["dados_usuario_temp"]["email_formatado"] = email_formatado
                            st.session_state["etapa_login"] = "senha"
                            st.rerun()
                        else:
                            nome_aluno = aluno.iloc[0]['Nome_Completo']
                            st.session_state["aluno_logado"] = {"email": email_formatado, "nome": nome_aluno, "perfil": perfil_usuario}
                            registrar_log(email_formatado, nome_aluno, f"Acessou como {perfil_usuario}")
                            st.rerun()

    # ---- ETAPA 2: PEDIR A SENHA (APENAS PROFESSOR) ----
    elif st.session_state["etapa_login"] == "senha":
        professor = st.session_state["dados_usuario_temp"]
        st.write(f"Olá, Professor(a) **{professor['Nome_Completo']}**! Identificamos seu perfil.")
        with st.form("form_login_senha"):
            senha_input = st.text_input("Digite sua senha de acesso:", type="password", key="input_senha_professor")
        
            col_b1, col_b2 = st.columns(2)
            btn_voltar = col_b2.form_submit_button("Voltar", width="stretch")
            btn_acessar = col_b1.form_submit_button("Acessar Portal", type="primary", width="stretch")

        if btn_voltar:
            st.session_state["etapa_login"] = "email"
            st.session_state["dados_usuario_temp"] = None
            st.rerun()
        
        if btn_acessar:
            senha_cadastrada = str(professor.get('Senha', '')).strip()
            
            if senha_input.strip() == senha_cadastrada:
                st.session_state["aluno_logado"] = {
                    "email": professor["email_formatado"], 
                    "nome": professor["Nome_Completo"], 
                    "perfil": "Professor"
                }
                registrar_log(professor["email_formatado"], professor["Nome_Completo"], "Acessou como Professor")
                del st.session_state["etapa_login"]
                del st.session_state["dados_usuario_temp"]
                st.rerun()
            else:
                st.error("🔒 Senha incorreta. Tente novamente.")

# ==========================================
# ÁREA LOGADA
# ==========================================
else:
    aluno = st.session_state["aluno_logado"]
    perfil = aluno.get("perfil", "Aluno")

    if perfil == "Professor":
        opcoes_menu = ["Painel Geral", "Moderação de Comentários"]
        st.sidebar.title("Menu do Professor")
    else:
        opcoes_menu = ["Avaliação de pares", "Avaliação do curso", "Meus resultados de pares"]
        st.sidebar.title("Menu do Aluno")

    if "radio_lateral" not in st.session_state:
        st.session_state["radio_lateral"] = opcoes_menu[0]
        
    if "escolha_menu" not in st.session_state:
        st.session_state["escolha_menu"] = opcoes_menu[0]
        
    st.write(f"### Bem-vindo, {aluno['nome']}!")
    st.write("Escolha um módulo abaixo ou use o menu lateral:")
    
    col1, col2, col3 = st.columns(3)
    if perfil == "Professor":
        if col1.button("👨‍🏫 Painel Geral", use_container_width=True):
            st.session_state["escolha_menu"] = "Painel Geral"
            st.rerun()
        if col2.button("🚫 Moderar Comentários", use_container_width=True):
            st.session_state["escolha_menu"] = "Moderação de Comentários"
            st.rerun()
    else:
        if col1.button("👥 Avaliação de pares", use_container_width=True):
            st.session_state["escolha_menu"] = "Avaliação de pares"
            st.rerun()
        if col2.button("📚 Avaliação do curso", use_container_width=True):
            st.session_state["escolha_menu"] = "Avaliação do curso"
            st.rerun()
        if col3.button("📊 Meus resultados de pares", use_container_width=True):
            st.session_state["escolha_menu"] = "Meus resultados de pares"
            st.rerun()

    st.write("---")

    menu = st.sidebar.radio(
        "Selecione um módulo:", 
        opcoes_menu, 
        index=opcoes_menu.index(st.session_state["escolha_menu"])
    )
    if menu != st.session_state["escolha_menu"]:
        st.session_state["escolha_menu"] = menu
        st.rerun()
            
    hoje = pd.to_datetime(datetime.now(ZoneInfo("America/Sao_Paulo"))).normalize().tz_localize(None)

    # ------------------------------------------
    # MÓDULO 1: AVALIAÇÃO DE PARES
    # ------------------------------------------
    if menu == "Avaliação de pares" and perfil == "Aluno":
        st.header("👥 Avaliação de pares")
        
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

            if st.form_submit_button("Enviar Avaliação de Pares", type="primary", use_container_width=True):
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
                        
                        ler_aba.clear() 
                        st.session_state["escolha_menu"] = "Avaliação do curso"
                        st.session_state["sucesso_redirecionamento"] = f"✅ Suas avaliações de pares para o **{nome_ciclo}** foram salvas! Por favor, responda agora à Avaliação do Curso abaixo."
                        st.rerun()

    # ------------------------------------------
    # MÓDULO 2: AVALIAÇÃO DO CURSO
    # ------------------------------------------
    elif menu == "Avaliação do curso" and perfil == "Aluno":
        st.markdown("<div style='position:relative'><input type='text' autofocus style='opacity:0; position:absolute; top:0; left:0; height:1px; width:1px;'></div>", unsafe_allow_html=True)
        st.header("📚 Avaliação do curso")
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
            
            if st.form_submit_button("Enviar Avaliação do Curso", type="primary", use_container_width=True):
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
                        
                        ler_aba.clear()
                        st.success("✅ Avaliação do curso salva!")
                        st.rerun()

    # ------------------------------------------
    # MÓDULO 3: MEUS RESULTADOS (BOLETIM)
    # ------------------------------------------
    elif menu == "Meus resultados de pares" and perfil == "Aluno":
        st.header("📊 Meus resultados de pares")
        
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
        
        # 1. Padrão de segurança: se nada for achado, seleciona o último ciclo cronológico
        idx_padrao_boletim = len(lista_nomes_ciclos) - 1 if lista_nomes_ciclos else 0
        
        # 2. Critério A: Verificar se existe algum ciclo ativo hoje por data ou status
        ciclo_hoje = ciclos_disc[(ciclos_disc['Status'].str.lower() == 'ativo') | 
                                 ((hoje >= ciclos_disc['Data início']) & (hoje <= ciclos_disc['Data fim']))]
        
        if not ciclo_hoje.empty:
            nome_ativo_hoje = ciclo_hoje.iloc[0]['Nome_Ciclo']
            if nome_ativo_hoje in lista_nomes_ciclos:
                idx_padrao_boletim = lista_nomes_ciclos.index(nome_ativo_hoje)
        else:
            # 3. Critério B: Se nenhum está ativo hoje, busca o último ciclo cronológico que de fato possui avaliações recebidas para este aluno
            recebidas_todas = df_aval[df_aval['Email_Avaliado'].str.lower().str.strip() == aluno['email']]
            if not recebidas_todas.empty:
                ids_com_nota = recebidas_todas['ID_Ciclo'].astype(str).str.strip().unique()
                ciclos_com_nota = ciclos_disc[ciclos_disc['ID_Ciclo'].astype(str).str.strip().isin(ids_com_nota)]
                if not ciclos_com_nota.empty:
                    ultimo_ciclo_com_nota = ciclos_com_nota.iloc[-1]['Nome_Ciclo']
                    if ultimo_ciclo_com_nota in lista_nomes_ciclos:
                        idx_padrao_boletim = lista_nomes_ciclos.index(ultimo_ciclo_com_nota)

        # Criamos o seletor com o index calculado de forma inteligente
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
    elif menu == "Painel Geral" and perfil == "Professor":
        st.header("👨‍🏫 Painel de Controle do Professor")
        
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
        idx_padrao_ciclo = 0 # Fallback caso falte dados
        
        try:
            # Pega o dia de hoje sem fuso horário para bater com o padrão gravado
            hoje_atual = pd.to_datetime(datetime.now(ZoneInfo("America/Sao_Paulo"))).normalize().tz_localize(None)
            df_ciclos_copy = ciclos_filtrados.copy()
            
            df_ciclos_copy['Data início'] = pd.to_datetime(df_ciclos_copy['Data início'], format='%d/%m/%Y', errors='coerce')
            df_ciclos_copy['Data fim'] = pd.to_datetime(df_ciclos_copy['Data fim'], format='%d/%m/%Y', errors='coerce')
            
            cond_status = df_ciclos_copy['Status'].astype(str).str.lower().str.strip() == 'ativo'
            cond_data = ((hoje_atual >= df_ciclos_copy['Data início']) & (hoje_atual <= df_ciclos_copy['Data fim']))
            
            ciclo_hoje = df_ciclos_copy[cond_status | cond_data]
            if not ciclo_hoje.empty:
                nome_ativo_hoje = ciclo_hoje.iloc[0]['Nome_Ciclo']
                if nome_ativo_hoje in lista_ciclos:
                    idx_padrao_ciclo = opcoes_ciclos.index(nome_ativo_hoje)
            else:
                if lista_ciclos:
                    # Se não há ciclo explícito hoje, pré-seleciona o último ciclo da lista
                    idx_padrao_ciclo = len(opcoes_ciclos) - 1
        except Exception:
            idx_padrao_ciclo = 0
            
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
                st.dataframe(rel_pendentes, use_container_width=True)
                
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
                    df_res_filtrados['Media_Pares'] = df_res_filtrados['Media_Pares'].round(1)
                    
                    # Exibição visual limpa ordenada por ciclo e nome do aluno
                    rel_resultados = df_res_filtrados[['Nome', 'Ciclo', 'Grupo', 'Media_Pares', 'Votos_Recebidos']].sort_values(['Ciclo', 'Nome'])
                    st.dataframe(rel_resultados, use_container_width=True)
                    
                    buffer_res = io.BytesIO()
                    with pd.ExcelWriter(buffer_res, engine='openpyxl') as writer:
                        df_res_filtrados[['Nome', 'Email_Avaliado', 'Ciclo', 'Grupo', 'Media_Pares', 'Votos_Recebidos']].to_excel(writer, index=False, sheet_name='Resultados')
                    st.download_button("📥 Baixar Resultados Parciais (Excel)", data=buffer_res.getvalue(), file_name=f"resultados_{ciclo_sel}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    
    # =========================================================
    # MÓDULO DO PROFESSOR: MODERAÇÃO DE COMENTÁRIOS
    # =========================================================
    elif menu == "Moderação de Comentários" and perfil == "Professor":
        st.header("🎯 Painel de Moderação do Orientador")
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
            idx_padrao_ciclo_mod = 0
            
            try:
                hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
                df_ciclos_copy = ciclos_filtrados.copy()
                for col in ['Data início', 'Data fim']:
                    if col in df_ciclos_copy.columns:
                        df_ciclos_copy[col] = pd.to_datetime(df_ciclos_copy[col], errors='coerce').dt.date
                
                cond_status = df_ciclos_copy['Status'].astype(str).str.lower().str.strip() == 'ativo' if 'Status' in df_ciclos_copy.columns else False
                cond_data = ((hoje >= df_ciclos_copy['Data início']) & (hoje <= df_ciclos_copy['Data fim'])) if ('Data início' in df_ciclos_copy.columns and 'Data fim' in df_ciclos_copy.columns) else False
                
                ciclo_hoje = df_ciclos_copy[cond_status | cond_data]
                if not ciclo_hoje.empty:
                    nome_ativo_hoje = ciclo_hoje.iloc[0]['Nome_Ciclo']
                    if nome_ativo_hoje in lista_ciclos:
                        idx_padrao_ciclo_mod = opcoes_ciclos_mod.index(nome_ativo_hoje)
                else:
                    if lista_ciclos:
                        idx_padrao_ciclo_mod = len(opcoes_ciclos_mod) - 1
            except Exception:
                idx_padrao_ciclo_mod = 0
                
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
                                if st.button("🔄 Aprovar", key=f"btn_aprov_{linha_real_gspread}", use_container_width=True):
                                    with st.spinner("Atualizando..."):
                                        aba_real = planilha.worksheet("Avaliacoes")
                                        aba_real.update_cell(linha_real_gspread, 13, "Aprovado")
                                        ler_aba.clear()
                                        st.toast("Status alterado para Aprovado!")
                                        st.rerun()
                            else:
                                st.success("✅ Visível")
                                if st.button("🗑️ Ignorar", key=f"btn_ign_{linha_real_gspread}", use_container_width=True):
                                    with st.spinner("Atualizando..."):
                                        aba_real = planilha.worksheet("Avaliacoes")
                                        aba_real.update_cell(linha_real_gspread, 13, "Ignorar")
                                        ler_aba.clear()
                                        st.toast("Status alterado para Ignorar!")
                                        st.rerun()
                                        
                    st.markdown("<hr style='margin: 0.5em 0px; border-color: rgba(49, 51, 63, 0.2);'>", unsafe_allow_html=True)
