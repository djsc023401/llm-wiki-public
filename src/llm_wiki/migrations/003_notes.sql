create table if not exists notes (
  id text primary key,
  kind text not null default 'inbox',
  status text not null default 'draft',
  title text not null,
  slug text not null,
  body_markdown text not null default '',
  metadata jsonb not null default '{}'::jsonb,
  parent_id text references notes(id) on delete set null,
  source_note_id text references notes(id) on delete set null,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  deleted_at timestamptz,
  constraint notes_kind_check check (
    kind in ('inbox', 'source', 'topic', 'entity', 'archive', 'log', 'template')
  ),
  constraint notes_status_check check (
    status in ('draft', 'active', 'archived', 'deleted', 'needs_review')
  ),
  constraint notes_version_check check (version >= 1),
  constraint notes_kind_slug_unique unique (kind, slug)
);

create index if not exists notes_kind_status_updated_idx
  on notes (kind, status, updated_at desc);

create index if not exists notes_parent_idx
  on notes (parent_id);

create index if not exists notes_source_note_idx
  on notes (source_note_id);

create index if not exists notes_metadata_gin_idx
  on notes using gin (metadata);

create table if not exists note_revisions (
  id text primary key,
  note_id text not null references notes(id) on delete cascade,
  version integer not null,
  title text not null,
  body_markdown text not null,
  metadata jsonb not null default '{}'::jsonb,
  change_source text not null default 'web',
  request_id text references processing_requests(id) on delete set null,
  created_by text,
  created_at timestamptz not null default now(),
  constraint note_revisions_version_check check (version >= 1),
  constraint note_revisions_change_source_check check (
    change_source in ('web', 'worker', 'import', 'export', 'operator', 'test')
  ),
  constraint note_revisions_note_version_unique unique (note_id, version)
);

create index if not exists note_revisions_note_version_idx
  on note_revisions (note_id, version desc);

create index if not exists note_revisions_request_idx
  on note_revisions (request_id);

create table if not exists note_links (
  id text primary key,
  from_note_id text not null references notes(id) on delete cascade,
  to_note_id text references notes(id) on delete set null,
  target_text text not null,
  link_type text not null default 'wiki',
  created_at timestamptz not null default now(),
  constraint note_links_type_check check (
    link_type in ('wiki', 'source_ref', 'topic_suggestion', 'entity_suggestion')
  )
);

create index if not exists note_links_from_idx
  on note_links (from_note_id);

create index if not exists note_links_to_idx
  on note_links (to_note_id);

create table if not exists note_assets (
  id text primary key,
  note_id text not null references notes(id) on delete cascade,
  object_key text not null,
  file_name text not null,
  content_type text,
  sha256 text,
  size_bytes bigint,
  created_at timestamptz not null default now(),
  constraint note_assets_note_object_unique unique (note_id, object_key)
);

create index if not exists note_assets_note_idx
  on note_assets (note_id);

create table if not exists export_jobs (
  id text primary key,
  status text not null default 'queued',
  scope text not null default 'changed-notes',
  note_id text references notes(id) on delete set null,
  content_commit_sha text,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  processed_at timestamptz,
  constraint export_jobs_status_check check (
    status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')
  ),
  constraint export_jobs_scope_check check (
    scope in ('changed-notes', 'full', 'note-id')
  )
);

create index if not exists export_jobs_status_created_idx
  on export_jobs (status, created_at);

create index if not exists export_jobs_note_idx
  on export_jobs (note_id);
