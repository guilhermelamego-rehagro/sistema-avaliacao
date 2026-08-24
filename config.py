"""Constantes e esquemas das abas do sistema."""

# Abas novas na planilha de avaliações
ABAS_AVALIACAO = {
    "Avaliacao_Orientador": [
        "Data",
        "ID_Ciclo",
        "Nome_Ciclo",
        "ID_Disciplina",
        "Email_Aluno",
        "Nome_Aluno",
        "Grupo",
        "Email_Orientador",
        "Nota",
        "Tipo",
    ],
    "Avaliacao_Grupo": [
        "Data",
        "ID_Ciclo",
        "Nome_Ciclo",
        "ID_Disciplina",
        "Sala",
        "Grupo",
        "Nota_Apresentacao",
        "Nota_Conteudo",
        "Nota_Total",
        "Comentario",
        "Email_Avaliador",
        "Nome_Avaliador",
        "Tipo",
    ],
    "Atividades_Individuais": [
        "ID_Disciplina",
        "Semana",
        "Atividade",
        "Email_Aluno",
        "Nome_Aluno",
        "Nota",
        "Origem",
        "Data_Importacao",
    ],
    "Config_Componentes": [
        "ID_Componente",
        "ID_Disciplina",
        "Nome",
        "Tipo",
        "Peso",
        "Ordem",
        "ID_Ciclo",
        "Ativo",
    ],
    "Config_Entregas": [
        "ID_Disciplina",
        "ID_Ciclo",
        "Data_Inicio",
        "Data_Fim",
        "Email_Professor",
        "Data_Atualizacao",
    ],
    "Ordem_Apresentacao": [
        "ID_Disciplina",
        "ID_Ciclo",
        "Sala",
        "Grupo",
        "Ordem",
    ],
    "Config_Liberacao_Notas": [
        "ID_Disciplina",
        "Liberado",
        "Data_Atualizacao",
        "Email_Responsavel",
        "Nome_Responsavel",
    ],
    "Encontro_Presencial_Datas": [
        "ID_Disciplina",
        "Data",
        "Descricao",
        "Ativo",
    ],
    "Presenca_Encontro": [
        "ID_Disciplina",
        "Data",
        "Email_Aluno",
        "Nome_Aluno",
        "Sala",
        "Grupo",
        "Status",
        "Email_Lancador",
        "Nome_Lancador",
        "Data_Lancamento",
    ],
    "Config_Professores_Disciplina": [
        "Disciplina",
        "ID_Disciplina",
        "Professor",
        "Email",
        "Papel",
    ],
    "Anotacoes_Daily": [
        "Data",
        "ID_Disciplina",
        "ID_Ciclo",
        "Nome_Ciclo",
        "Sala",
        "Grupo",
        "Texto",
        "Email_Orientador",
        "Nome_Orientador",
        "Data_Atualizacao",
    ],
    "Matrizes": [
        "ID_Matriz",
        "Nome",
        "Versao",
        "Status",
        "Observacao",
    ],
    "Matriz_Itens": [
        "ID_Matriz",
        "Ordem",
        "ID_Disciplina",
        "Encontro_Presencial_Sugerido",
    ],
    "Carrosseis": [
        "ID_Carrossel",
        "Nome",
        "ID_Matriz",
        "Posicao_Inicio",
        "Data_Inicio",
        "Status",
    ],
    "Carrossel_Itens": [
        "ID_Carrossel",
        "Ordem",
        "ID_Disciplina",
    ],
    "Turmas": [
        "ID_Turma",
        "ID_Carrossel",
        "Posicao_Entrada",
        "Status",
        "Observacao",
    ],
    "Trimestres": [
        "ID_Trimestre",
        "Ano",
        "Numero",
        "Nome",
        "Data_Inicio",
        "Data_Fim",
        "Status",
    ],
    "Ofertas": [
        "ID_Oferta",
        "ID_Carrossel",
        "ID_Matriz",
        "ID_Disciplina",
        "ID_Trimestre",
        "Ano",
        "Trimestre",
        "Tipo",
        "Status",
        "Data_Prevista_Inicio",
        "Data_Prevista_Fim",
        "Encontro_Presencial",
        "Link_Plataforma",
        "Observacao",
    ],
    "Oferta_Turmas": [
        "ID_Oferta",
        "ID_Turma",
    ],
    "Oferta_Excecoes": [
        "ID_Oferta",
        "Email_Aluno",
        "Nome_Aluno",
        "Tipo",
        "Motivo",
    ],
}

# Aba nova na planilha de frequência
ABAS_FREQUENCIA = {
    "Calendario_Aulas": [
        "Data",
        "ID_Disciplina",
        "Disciplina",
        "Categoria",
        "Detalhe",
    ],
    "Calendario_Dailies": [
        "Data",
        "ID_Disciplina",
        "Disciplina",
    ],
    "Calendario_Unificado": [
        "Data",
        "ID_Disciplina",
        "Disciplina",
        "Tipo",
        "Conta_Presenca",
        "Conta_Nota_Daily",
        "Presencial",
        "Descricao",
    ],
    "Calendario_Institucional": [
        "Data",
        "Tipo",
        "Nome",
        "Origem",
        "Ativo",
    ],
}

# Modelo padrão ao cadastrar disciplina (4 ciclos + entrega final + dailies + atividades)
PESOS_PADRAO = [
    ("Ciclo 1", 7.5, 1),
    ("Ciclo 2", 7.5, 2),
    ("Ciclo 3", 7.5, 3),
    ("Ciclo 4", 7.5, 4),
    ("Entrega Final", 50.0, 5),
    ("Reuniões diárias", 10.0, 6),
    ("Atividades individuais", 10.0, 7),
]

CICLOS_PADRAO = [
    ("Ciclo 1", 1),
    ("Ciclo 2", 2),
    ("Ciclo 3", 3),
    ("Ciclo 4", 4),
]

CICLO_ENTREGA_FINAL = ("Entrega Final", 5)

TIPOS_COMPONENTE = [
    "Ciclo",
    "Entrega_Final",
    "Reuniao_Diaria",
    "Atividade_Individual",
]

TIPOS_COMPONENTE_LABEL = {
    "Ciclo": "Ciclo",
    "Entrega_Final": "Entrega final",
    "Reuniao_Diaria": "Reunião diária",
    "Atividade_Individual": "Avaliação individual",
}

PESO_ORIENTADOR = 0.60
PESO_PARES = 0.40
MINUTOS_PRESENCA = 30

ICONE_STATUS_PRESENCA = {
    "Presente": "✅",
    "Falta": "❌",
    "Conectado": "⏳",
    "Ajuste": "✏️",
    "Futuro": "📅",
}
