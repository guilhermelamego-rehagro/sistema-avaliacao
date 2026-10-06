-- =============================================================================
-- Painel de feedback do aluno (um registro por aluno e ciclo)
-- Execute no SQL Editor do projeto de TESTE e, na implantação, no de PRODUÇÃO.
-- Tabela independente das planilhas: nada do Sheets é lido ou alterado.
-- =============================================================================

create table if not exists public.feedback_ciclo (
  id bigint generated always as identity primary key,
  email text not null,
  id_disciplina text not null default '',
  id_ciclo text not null,
  nome_ciclo text not null default '',
  -- Retrato do feedback no momento da publicação (métricas, faixas e textos).
  conteudo jsonb not null default '{}'::jsonb,
  mensagem text not null default '',
  -- Indicação de conversa 1x1: só a equipe docente vê.
  um_a_um boolean not null default false,
  publicado_em timestamptz,
  autor_email text not null default '',
  autor_nome text not null default '',
  atualizado_em timestamptz not null default now(),
  constraint feedback_ciclo_unico unique (email, id_ciclo)
);

create index if not exists feedback_ciclo_ciclo_idx
  on public.feedback_ciclo (id_ciclo);

create index if not exists feedback_ciclo_aluno_idx
  on public.feedback_ciclo (email)
  where publicado_em is not null;

-- Só o service_role (servidor do app) acessa; nenhuma política pública.
alter table public.feedback_ciclo enable row level security;
