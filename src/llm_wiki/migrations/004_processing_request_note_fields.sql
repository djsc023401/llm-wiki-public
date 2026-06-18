alter table processing_requests
  add column if not exists input_mode text not null default 'file-path',
  add column if not exists note_id text,
  add column if not exists source_revision_id text,
  add column if not exists target_note_id text;

alter table processing_requests
  alter column file_path drop not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'processing_requests_input_mode_check'
  ) then
    alter table processing_requests
      add constraint processing_requests_input_mode_check
      check (input_mode in ('file-path', 'db-note', 'snapshot'));
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'processing_requests_note_id_fkey'
  ) then
    alter table processing_requests
      add constraint processing_requests_note_id_fkey
      foreign key (note_id) references notes(id) on delete set null;
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'processing_requests_source_revision_id_fkey'
  ) then
    alter table processing_requests
      add constraint processing_requests_source_revision_id_fkey
      foreign key (source_revision_id) references note_revisions(id) on delete set null;
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'processing_requests_target_note_id_fkey'
  ) then
    alter table processing_requests
      add constraint processing_requests_target_note_id_fkey
      foreign key (target_note_id) references notes(id) on delete set null;
  end if;
end $$;

create index if not exists processing_requests_input_mode_status_idx
  on processing_requests (input_mode, status, created_at);

create index if not exists processing_requests_note_revision_idx
  on processing_requests (note_id, source_revision_id);

create unique index if not exists processing_requests_active_note_revision_unique
  on processing_requests (note_id, source_revision_id)
  where input_mode = 'db-note'
    and status in ('queued', 'running', 'needs_sync')
    and note_id is not null
    and source_revision_id is not null;
