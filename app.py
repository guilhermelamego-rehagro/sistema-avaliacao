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
    return cliente.open_by_key(st.secrets["planilhas"]["id_producao"])

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
            st.session_state["radio_lateral"] = "Painel Geral"
            st.session_state["escolha_menu"] = "Painel Geral"
            st.rerun()
        if col2.button("🚫 Moderar Comentários", use_container_width=True):
            st.session_state["radio_lateral"] = "Moderação de Comentários"
            st.session_state["escolha_menu"] = "Moderação de Comentários"
            st.rerun()
    else:
        if col1.button("👥 Avaliação de pares", use_container_width=True):
            st.session_state["radio_lateral"] = "Avaliação de pares"
            st.session_state["escolha_menu"] = "Avaliação de pares"
            st.rerun()
        if col2.button("📚 Avaliação do curso", use_container_width=True):
            st.session_state["radio_lateral"] = "Avaliação do curso"
            st.session_state["escolha_menu"] = "Avaliação do curso"
            st.rerun()
        if col3.button("📊 Meus resultados de pares", use_container_width=True):
            st.session_state["radio_lateral"] = "Meus resultados de pares"
            st.session_state["escolha_menu"] = "Meus resultados de pares"
            st.rerun()

    st.write("---")

    menu = st.sidebar.radio(
        "Selecione um módulo:", 
        opcoes_menu, 
        key="radio_lateral"
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
                        st.success("✅ Avaliações salvas com sucesso!")
                        st.rerun()

    # ------------------------------------------
    # MÓDULO 2: AVALIAÇÃO DO CURSO
    # ------------------------------------------
    elif menu == "Avaliação do curso" and perfil == "Aluno":
        st.header("📚 Avaliação do curso")
        
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
            
        abas = st.tabs(ciclos_disc['Nome_Ciclo'].tolist())
        
        for i, row_ciclo in ciclos_disc.reset_index().iterrows():
            with abas[i]:
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
                # Descobre em qual posição da lista a disciplina ativa está
                idx_padrao_disc = lista_disciplinas.index(disc_ativa_nome)

        disc_sel = st.selectbox("Selecione a Disciplina:", lista_disciplinas, index=idx_padrao_disc, key="geral_disc_sel")
        id_disc_sel = str(df_disc[df_disc['Nome_Disciplina'] == disc_sel].iloc[0]['ID_Disciplina']).strip()
        ciclos_filtrados = df_ciclos[df_ciclos['ID_Disciplina'].astype(str).str.strip() == id_disc_sel]
        lista_ciclos = ciclos_filtrados['Nome_Ciclo'].unique().tolist()
        
        if not lista_ciclos:
            st.warning("Nenhum ciclo cadastrado para esta disciplina.")
            st.stop()
            
        ciclo_sel = st.selectbox("Selecione o Ciclo:", lista_ciclos)
        id_ciclo_sel = str(ciclos_filtrados[ciclos_filtrados['Nome_Ciclo'] == ciclo_sel].iloc[0]['ID_Ciclo']).strip()
        
        entrancia_disc = df_entrancia[df_entrancia['ID_Disciplina'].astype(str).str.strip() == id_disc_sel]
        sala_sel = st.selectbox("Selecione a Sala:", ["Todas"] + sorted(entrancia_disc['Sala'].dropna().unique().astype(str).tolist()))
        def chave_ordenacao_geral(x):
            try:
                return (0, float(x)) # Se for número (ex: 1, 2, 10), ordena numericamente
            except ValueError:
                return (1, str(x))   # Se for texto (ex: 'A'), joga pro final e ordena alfabeticamente

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
        
        with aba_pendentes:
            st.subheader("Alunos que ainda não enviaram a avaliação")
            ja_votaram = df_aval[df_aval['ID_Ciclo'].astype(str).str.strip() == id_ciclo_sel]['Email_Avaliador'].str.lower().str.strip().unique().tolist()
            df_pendentes = df_alunos_esperados[~df_alunos_esperados['Email_Pessoal'].str.lower().str.strip().isin(ja_votaram)]
            
            if df_pendentes.empty:
                st.success("🎉 Nenhum aluno pendente para os filtros selecionados!")
            else:
                rel_pendentes = df_pendentes[['Nome_Completo', 'Email_Pessoal', 'Sala', 'Grupo']].rename(columns={'Nome_Completo': 'Nome', 'Email_Pessoal': 'E-mail'})
                st.write(f"Total pendente: **{len(rel_pendentes)}**")
                st.dataframe(rel_pendentes, use_container_width=True)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    rel_pendentes.to_excel(writer, index=False, sheet_name='Pendentes')
                st.download_button("📥 Baixar Lista de Pendentes (Excel)", data=buffer.getvalue(), file_name=f"pendentes_{ciclo_sel}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                
        with aba_resultados:
            st.subheader("Médias parciais calculadas para os alunos")
            votos_ciclo = df_aval[df_aval['ID_Ciclo'].astype(str).str.strip() == id_ciclo_sel]
            
            if votos_ciclo.empty:
                st.info("Nenhum voto registrado para este ciclo.")
            else:
                votos_ciclo['Nota'] = pd.to_numeric(votos_ciclo['Nota'], errors='coerce')
                df_medias = votos_ciclo.groupby('Email_Avaliado').agg(
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
                    rel_resultados = df_res_filtrados[['Nome', 'Email_Avaliado', 'Grupo', 'Media_Pares', 'Votos_Recebidos']].sort_values('Nome')
                    st.dataframe(rel_resultados, use_container_width=True)
                    
                    buffer_res = io.BytesIO()
                    with pd.ExcelWriter(buffer_res, engine='openpyxl') as writer:
                        rel_resultados.to_excel(writer, index=False, sheet_name='Resultados')
                    st.download_button("📥 Baixar Resultados Parciais (Excel)", data=buffer_res.getvalue(), file_name=f"resultados_{ciclo_sel}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ------------------------------------------
    # MÓDULO DO PROFESSOR: MODERAÇÃO DE COMENTÁRIOS (DESIGN CARDS + BUGFIX)
    # ------------------------------------------
    elif menu == "Moderação de Comentários" and perfil == "Professor":
        st.header("🎯 Painel de Moderação do Orientador")
        st.write("Por padrão, todos os feedbacks nascem **Aprovados** e visíveis aos alunos. Use as ações abaixo para ocultar (Ignorar) ou reativar comentários.")
        
        # Carrega todas as bases necessárias para os filtros em cascata
        df_disc = ler_aba("Disciplinas")
        df_ciclos = ler_aba("Ciclos")
        df_turmas = ler_aba("Entrancia_Turma")
        df_aval = ler_aba("Avaliacoes")
        
        # Cria explicitamente o mapeamento da linha real do gspread ANTES de qualquer filtro ou merge
        # O gspread é indexado em 1 e tem o cabeçalho, então a linha real é index + 2
        df_aval['Linha_Planilha'] = df_aval.index + 2

        # ---------------------------------------------------------
        # LÓGICA DE SELEÇÃO AUTOMÁTICA DA DISCIPLINA ATIVA
        # ---------------------------------------------------------
        lista_disciplinas = df_disc['Nome_Disciplina'].unique().tolist()
        idx_padrao_disc = 0 
        
        # AJUSTE AQUI: Se na sua planilha a coluna chamar 'Status', 'Ativa', etc.
        coluna_status = 'Status' if 'Status' in df_disc.columns else df_disc.columns[-1] # fallback para a última coluna caso mude o nome
        
        df_ativa = df_disc[df_disc[coluna_status].astype(str).str.strip().str.lower().isin(['ativa', 'ativo', 'sim', 's'])]
        if not df_ativa.empty:
            disc_ativa_nome = df_ativa.iloc[0]['Nome_Disciplina']
            if disc_ativa_nome in lista_disciplinas:
                idx_padrao_disc = lista_disciplinas.index(disc_ativa_nome)
        
        # ---------------------------------------------------------
        # FILTROS EM CASCATA (Disciplina -> Ciclo -> Sala -> Grupo)
        # ---------------------------------------------------------
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
                
            ciclo_sel = st.selectbox("Selecione o Ciclo:", lista_ciclos, key="mod_ciclo_sel")
            id_ciclo_sel = str(ciclos_filtrados[ciclos_filtrados['Nome_Ciclo'] == ciclo_sel].iloc[0]['ID_Ciclo']).strip()
            
        c_filt3, c_filt4 = st.columns(2)
        
        with c_filt3:
            entrancia_disc = df_turmas[df_turmas['ID_Disciplina'].astype(str).str.strip() == id_disc_sel]
            salas_disponiveis = ["Todas"] + sorted(entrancia_disc['Sala'].dropna().unique().astype(str).tolist())
            sala_sel = st.selectbox("Filtrar por Sala:", salas_disponiveis, key="mod_sala_sel")
            
        with c_filt4:
            # Converte para numérico onde for possível para ordenar corretamente, mantendo texto se houver
            def chave_ordenacao_grupo(x):
                try:
                    return (0, float(x))  # Se for número, ordena numericamente
                except ValueError:
                    return (1, str(x))    # Se for texto (ex: "A"), joga para o final e ordena alfabeticamente

            lista_grupos_ordenada = sorted(entrancia_disc['Grupo'].dropna().unique().astype(str).tolist(), key=chave_ordenacao_grupo)
            grupos_disponiveis = ["Todos"] + lista_grupos_ordenada
            grupo_sel = st.selectbox("Filtrar por Grupo:", grupos_disponiveis, key="mod_grupo_sel")

        # ---------------------------------------------------------
        # FILTRAGEM E PROCESSAMENTO DOS COMENTÁRIOS
        # ---------------------------------------------------------
        df_comentarios = df_aval[
            (df_aval['ID_Ciclo'].astype(str).str.strip() == id_ciclo_sel) & 
            (df_aval['Comentário'].astype(str).str.strip() != "")
        ].copy()
        
        if df_comentarios.empty:
            st.info(f"Nenhum comentário registrado para o ciclo '{ciclo_sel}'.")
        else:
            # Cruza com a Entrancia_Turma para descobrir a Sala e Grupo de cada aluno avaliado
            df_turmas_mapping = entrancia_disc[['Email_Pessoal', 'Sala', 'Grupo']].drop_duplicates().rename(columns={'Email_Pessoal': 'Email_Avaliado'})
            
            # Remove colunas duplicadas se já existirem antes do merge para evitar sufixos _x ou _y
            if 'Sala' in df_comentarios.columns: df_comentarios.drop(columns=['Sala'], inplace=True)
            if 'Grupo' in df_comentarios.columns: df_comentarios.drop(columns=['Grupo'], inplace=True)
                
            df_comentarios = pd.merge(df_comentarios, df_turmas_mapping, on='Email_Avaliado', how='left')
            
            # Aplica os filtros de Sala e Grupo na listagem
            if sala_sel != "Todas":
                df_comentarios = df_comentarios[df_comentarios['Sala'].astype(str).str.strip() == sala_sel]
            if grupo_sel != "Todos":
                df_comentarios = df_comentarios[df_comentarios['Grupo'].astype(str).str.strip() == grupo_sel]
                
            # ---------------------------------------------------------
            # EXIBIÇÃO EM FORMATO DE CARDS (BLOCO INTEGRAL)
            # ---------------------------------------------------------
            st.markdown("### 💬 Lista de Feedbacks Encontrados")
            st.write(f"Total nesta seleção: **{len(df_comentarios)}**")
            st.markdown("---")
            
            if df_comentarios.empty:
                st.warning("Nenhum comentário corresponde aos filtros de Sala/Grupo aplicados.")
            else:
                for idx, row in df_comentarios.iterrows():
                    # Identifica a linha real salva para não errar a edição no gspread
                    linha_real_gspread = int(row['Linha_Planilha'])
                    
                    status_atual = str(row.get('Moderação', '')).strip().lower()
                    is_ignorado = (status_atual == 'ignorar')
                    
                    # Definição de metadados do Card
                    sala_card = str(row.get('Sala', '-'))
                    grupo_card = str(row.get('Grupo', '-'))
                    avaliador = str(row.get('Nome', row.get('Nome_Avaliador', 'Avaliador')))
                    avaliado = str(row.get('Nome_Avaliado', 'Avaliado'))
                    comentario_texto = str(row.get('Comentário', ''))
                    
                    # Container visual para cada feedback
                    with st.container():
                        # Divisão interna do card: Corpo do texto (80%) | Status e Ação (20%)
                        col_corpo, col_acao = st.columns([4, 1])
                        
                        with col_corpo:
                            # Tag superior estilizada com os dados do aluno
                            st.markdown(f"**Sala {sala_card} • Grupo {grupo_card}** | `{avaliador}` ➔ `{avaliado}`")
                            st.markdown(f"➔ *\"{comentario_texto}\"*")
                        
                        with col_acao:
                            if is_ignorado:
                                st.error("🚫 Ocultado")
                                if st.button("🔄 Aprovar", key=f"btn_aprov_{linha_real_gspread}", use_container_width=True):
                                    with st.spinner("Atualizando..."):
                                        aba_real = planilha.worksheet("Avaliacoes")
                                        # Coluna 13 é a coluna 'Moderação'
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