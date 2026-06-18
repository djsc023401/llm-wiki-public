create table if not exists note_feedback (
  id text primary key,
  note_id text not null references notes(id) on delete cascade,
  note_version integer,
  feedback_type text not null,
  body_markdown text not null,
  status text not null default 'open',
  reprocess_note_id text references notes(id) on delete set null,
  reprocess_request_id text references processing_requests(id) on delete set null,
  created_by text,
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  constraint note_feedback_type_check check (
    feedback_type in ('correction', 'change', 'additional_info', 'ai_error', 'low_priority')
  ),
  constraint note_feedback_status_check check (
    status in ('open', 'queued', 'applied', 'dismissed')
  )
);

create index if not exists note_feedback_note_created_idx
  on note_feedback (note_id, created_at desc);

create index if not exists note_feedback_note_status_idx
  on note_feedback (note_id, status, created_at desc);

create index if not exists note_feedback_reprocess_request_idx
  on note_feedback (reprocess_request_id);

create unique index if not exists processing_requests_active_target_note_unique
  on processing_requests (target_note_id)
  where input_mode = 'db-note'
    and status in ('queued', 'running')
    and target_note_id is not null;
