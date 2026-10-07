-- =============================================================================
-- Relatório de notas finais para a secretaria (retrato estático por disciplina)
-- Execute no SQL Editor do projeto de TESTE e, na implantação, no de PRODUÇÃO.
-- Tabelas independentes das planilhas: nada do Sheets é lido ou alterado.
-- =============================================================================

-- Um retrato por disciplina, publicado na liberação da nota final e substituído
-- a cada atualização publicada pelos professores.
create table if not exists public.relatorio_secretaria (
  id_disciplina text primary key,
  nome_disciplina text not null default '',
  colunas jsonb not null default '[]'::jsonb,
  linhas jsonb not null default '[]'::jsonb,
  legendas jsonb not null default '[]'::jsonb,
  gerado_em timestamptz not null default now(),
  gerado_por_email text not null default '',
  gerado_por_nome text not null default ''
);

-- Histórico do que mudou entre um retrato e o seguinte (um registro por aluno e campo).
create table if not exists public.relatorio_secretaria_log (
  id bigint generated always as identity primary key,
  id_disciplina text not null,
  email text not null default '',
  nome text not null default '',
  turma text not null default '',
  campo text not null,
  antes text not null default '',
  depois text not null default '',
  alterado_em timestamptz not null default now(),
  alterado_por_email text not null default '',
  alterado_por_nome text not null default ''
);

create index if not exists relatorio_secretaria_log_disc_idx
  on public.relatorio_secretaria_log (id_disciplina, alterado_em desc);

-- Só o service_role (servidor do app) acessa; nenhuma política pública.
alter table public.relatorio_secretaria enable row level security;
alter table public.relatorio_secretaria_log enable row level security;
