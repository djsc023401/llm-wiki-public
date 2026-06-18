create table if not exists suggestion_decisions (
  id text primary key,
  source_note_id text not null references notes(id) on delete cascade,
  suggestion_kind text not null,
  suggestion_key text not null,
  candidate text not null default '',
  status text not null default 'dismissed',
  reason text,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint suggestion_decisions_kind_check check (
    suggestion_kind in ('topic', 'entity', 'tag', 'time')
  ),
  constraint suggestion_decisions_status_check check (
    status in ('dismissed')
  ),
  constraint suggestion_decisions_unique unique (
    source_note_id, suggestion_kind, suggestion_key
  )
);

create index if not exists suggestion_decisions_source_status_idx
  on suggestion_decisions (source_note_id, status, updated_at desc);
