create table if not exists chat_sessions (
  id text primary key,
  title text not null default '대화',
  status text not null default 'active',
  source text not null default 'web',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint chat_sessions_status_check check (status in ('active', 'archived', 'deleted'))
);

create table if not exists chat_turns (
  id text primary key,
  session_id text not null references chat_sessions(id) on delete cascade,
  turn_index integer not null,
  query text not null,
  answer text not null default '',
  answer_mode text not null default '',
  answer_refs jsonb not null default '[]'::jsonb,
  items jsonb not null default '[]'::jsonb,
  followups jsonb not null default '[]'::jsonb,
  meta jsonb not null default '{}'::jsonb,
  error_message text,
  created_at timestamptz not null default now(),
  constraint chat_turns_turn_index_check check (turn_index >= 1),
  constraint chat_turns_session_turn_index_key unique (session_id, turn_index)
);

create index if not exists chat_sessions_status_updated_idx
  on chat_sessions (status, updated_at desc, id desc);

create index if not exists chat_turns_session_index_idx
  on chat_turns (session_id, turn_index);
