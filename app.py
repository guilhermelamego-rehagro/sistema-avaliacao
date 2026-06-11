import streamlit as st
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo

# 1. Configurações Iniciais da Página
st.set_page_config(page_title="Portal de Avaliações - Rehagro", page_icon="🎓", layout="centered")

# Customização de Cores Avançada via CSS (Garante o texto verde nos sliders e componentes)
st.markdown("""
    <style>
        div[data-testid="stSlider"] div[role="slider"] div {
        color: #004D28 !important;
        font-weight: bold !important;
        font-size: 18px !important;
        
    }
    /* Garante que os números de referência (0 e 10) abaixo do slider fiquem em verde */
    div[data-testid="stSlider"] label, div[data-testid="stSlider"] span {
        color: #004D28 !important;
    }

    /* NOVO: Faz a setinha do menu lateral (celular) ficar verde e pulsar */
    button[data-testid="stSidebarCollapseButton"] {
        background-color: #004D28 !important;
        color: white !important;
        border-radius: 50% !important;
        border: 2px solid #B38F36 !important; /* Detalhe em dourado */
        animation: pulsar 2s infinite !important;
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
    return cliente.open_by_key("1miHasJXm7Gs5GwQxP0T2w6kbUipnesXSV90taXVbqtg")

# Conecta ao banco de dados (Variável Global)
planilha = conectar_planilha()

# 3. Leitura com Cache (Deixa o app incrivelmente rápido)
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
st.sidebar.image("logo.png", use_container_width=True) 
st.sidebar.title("Menu do Aluno")

# Inicializa sessão
if "aluno_logado" not in st.session_state:
    st.session_state["aluno_logado"] = None

# ==========================================
# TELA DE LOGIN
# ==========================================
if not st.session_state["aluno_logado"]:
    st.title("Bem-vindo ao Portal de Avaliações")
    st.write("Digite seu e-mail cadastrado para acessar seus módulos.")

    with st.form("formulario_login", clear_on_submit=False):
        email_input = st.text_input("E-mail Rehagro:")

        botao_acessar = st.form_submit_button("Acessar Portal", type="primary")
    
   if botao_acessar:
        if email_input:
            email_formatado = email_input.strip().lower()
            
            with st.spinner("Autenticando..."):
                df_alunos = ler_aba("Base_Alunos")
                aluno = df_alunos[(df_alunos['Email_Pessoal'].str.lower() == email_formatado) & 
                                  (df_alunos['Status_Geral'].str.strip() == 'Ativo')]
                
                if aluno.empty:
                    st.error("E-mail não encontrado ou cadastro inativo.")
                else:
                    nome_aluno = aluno.iloc[0]['Nome_Completo']
                    st.session_state["aluno_logado"] = {"email": email_formatado, "nome": nome_aluno}
                    registrar_log(email_formatado, nome_aluno, "Acessou o portal")
                    st.rerun()

# ==========================================
# ÁREA LOGADA
# ==========================================
else:
    aluno = st.session_state["aluno_logado"]
    opcoes_menu = ["Avaliação de pares", "Avaliação do curso", "Meus resultados de pares"]
    if "radio_lateral" not in st.session_state:
        st.session_state["radio_lateral"] = opcoes_menu[0]
        
    if "escolha_menu" not in st.session_state:
        st.session_state["escolha_menu"] = opcoes_menu[0]
    st.write(f"### Bem-vindo, {aluno['nome']}!")
    st.write("Escolha um módulo abaixo ou use o menu lateral:")
    
    col1, col2, col3 = st.columns(3)

    if col1.button("👥 Avaliação de pares", use_container_width=True):
        st.session_state["radio_lateral"] = opcoes_menu[0]
        st.session_state["escolha_menu"] = opcoes_menu[0]
        st.rerun()
    if col2.button("📚 Avaliação do curso", use_container_width=True):
        st.session_state["radio_lateral"] = opcoes_menu[1]
        st.session_state["escolha_menu"] = opcoes_menu[1]
        st.rerun()
    if col3.button("📊 Meus resultados de pares", use_container_width=True):
        st.session_state["radio_lateral"] = opcoes_menu[2]
        st.session_state["escolha_menu"] = opcoes_menu[2]
        st.rerun()

    st.write("---")

    indice_atual = opcoes_menu.index(st.session_state["escolha_menu"])
    
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
    if menu == "Avaliação de pares":
        st.header("👥 Avaliação de pares")
        
        # Puxa os dados (agora é instantâneo por causa do cache)
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
                
                # LAYOUT AJUSTADO: Nota em cima, comentário embaixo (sem colunas)
                nota = st.radio("Nota (0 a 5):", [0, 1, 2, 3, 4, 5], horizontal=True, key=f"n_{index}")
                coment = st.text_area("Feedback (opcional):", placeholder="Escreva seu feedback aqui...", key=f"c_{index}")
                
                respostas_pares[colega['Email_Pessoal']] = {"nome": colega['Nome_Completo'], "nota": nota, "coment": coment}

            if st.form_submit_button("Enviar Avaliação de Pares", type="primary", use_container_width=True):
                with st.spinner("Salvando notas..."):
                    aba_avaliacoes = planilha.worksheet("Avaliacoes")
                    dados_inserir = []
                    agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
                    for email_aval, d in respostas_pares.items():
                        dados_inserir.append([agora, id_ciclo, nome_disc, nome_ciclo, email_aval, d['nome'], meu_grupo, d['nota'], aluno['email'], aluno['nome'], d['coment'], "", ""])
                    aba_avaliacoes.append_rows(dados_inserir)
                    registrar_log(aluno['email'], aluno['nome'], f"Enviou avaliação pares - {nome_ciclo}")
                    
                    # Limpa o cache para atualizar a planilha em tempo real
                    ler_aba.clear() 
                    st.success("✅ Avaliações salvas com sucesso!")
                    st.rerun()

    # ------------------------------------------
    # MÓDULO 2: AVALIAÇÃO DO CURSO
    # ------------------------------------------
    elif menu == "Avaliação do curso":
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
            ae = col1.radio("Auto Estudo", [0,1,2,3,4,5], index=5, horizontal=True)
            av = col2.radio("Aulas ao Vivo", [0,1,2,3,4,5], index=5, horizontal=True)
            ap = col1.radio("Aplicabilidade", [0,1,2,3,4,5], index=5, horizontal=True)
            su = col2.radio("Suporte", [0,1,2,3,4,5], index=5, horizontal=True)
            
            st.write("---")
            st.write("**Avaliação da Didática dos Professores (0 a 5)**")
            notas_prof = {}
            for p in professores:
                notas_prof[p] = st.radio(f"Professor(a): {p}", [0,1,2,3,4,5], index=5, horizontal=True)
                
            st.write("---")
            # NPS AJUSTADO: Valor padrão (value) setado para 10
            nps = st.slider("Em uma escala de 0 a 10, qual a probabilidade de recomendar este curso?", min_value=0, max_value=10, value=10)
            
            st.write("---")
            que_bom = st.text_area("Que Bom que... (Opcional)")
            que_pena = st.text_area("Que Pena que... (Opcional)")
            que_tal = st.text_area("Que Tal se... (Opcional)")
            
            if st.form_submit_button("Enviar Avaliação do Curso", type="primary", use_container_width=True):
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
                    
                    # Limpa o cache para atualizar a planilha
                    ler_aba.clear()
                    st.success("✅ Avaliação do curso salva!")
                    st.rerun()

    # ------------------------------------------
    # MÓDULO 3: MEUS RESULTADOS (BOLETIM)
    # ------------------------------------------
    elif menu == "Meus resultados de pares":
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
