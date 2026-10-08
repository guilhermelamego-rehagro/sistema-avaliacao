-- =============================================================================
-- Boletins calculados (nota até agora e situação final de cada aluno)
-- Execute no SQL Editor do projeto de TESTE e, na implantação, no de PRODUÇÃO.
-- Tabelas independentes das planilhas: guardam só o resultado do cálculo, que o
-- app refaz no primeiro acesso do dia da equipe e quando alguém pede recálculo.
-- =============================================================================

-- Um boletim calculado por aluno e disciplina (substituído a cada cálculo).
create table if not exists public.boletim_calculado (
  id_disciplina text not null,
  email text not null,
  dados jsonb not null default '{}'::jsonb,
  calculado_em timestamptz not null default now(),
  primary key (id_disciplina, email)
);

-- Quando terminou o último cálculo completo da disciplina.
create table if not exists public.boletim_calculo (
  id_disciplina text primary key,
  concluido_em timestamptz not null default now(),
  alunos integer not null default 0,
  calculado_por text not null default ''
);

-- Só o service_role (servidor do app) acessa; nenhuma política pública.
alter table public.boletim_calculado enable row level security;
alter table public.boletim_calculo enable row level security;
