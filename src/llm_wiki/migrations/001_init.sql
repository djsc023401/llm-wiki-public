create table if not exists schema_migrations (
  version text primary key,
  applied_at timestamptz not null default now()
);

create table if not exists processing_requests (
  id text primary key,
  source text not null,
  operation text not null,
  repo_full_name text not null,
  branch text not null default 'main',
  commit_sha text,
  file_path text not null,
  content_hash text,
  content_snapshot text,
  sensitivity text not null default 'private',
  status text not null,
  branch_name text,
  pr_url text,
  error_message text,
  attempts integer not null default 0,
  locked_by text,
  locked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  processed_at timestamptz,
  constraint processing_requests_status_check check (
    status in ('queued', 'running', 'needs_sync', 'succeeded', 'failed', 'cancelled')
  )
);

create index if not exists processing_requests_status_created_idx
  on processing_requests (status, created_at);

create table if not exists processing_attachments (
  id text primary key,
  request_id text not null references processing_requests(id) on delete cascade,
  object_key text not null,
  file_name text not null,
  content_type text,
  size_bytes bigint,
  sha256 text,
  created_at timestamptz not null default now()
);

create index if not exists processing_attachments_request_idx
  on processing_attachments (request_id);

create table if not exists worker_state (
  key text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);
