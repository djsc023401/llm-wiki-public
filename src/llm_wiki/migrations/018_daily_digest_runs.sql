create table if not exists daily_digest_runs (
  id text primary key,
  digest_date date not null,
  channel text not null,
  status text not null default 'queued',
  scheduled_for timestamptz not null,
  sent_at timestamptz,
  last_attempt_at timestamptz,
  attempt_count integer not null default 0,
  error_message text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint daily_digest_runs_channel_check check (
    channel in ('pwa', 'telegram')
  ),
  constraint daily_digest_runs_status_check check (
    status in ('queued', 'sending', 'sent', 'failed')
  ),
  constraint daily_digest_runs_attempt_count_check check (
    attempt_count >= 0
  )
);

create unique index if not exists daily_digest_runs_date_channel_unique_idx
  on daily_digest_runs (digest_date, channel);

create index if not exists daily_digest_runs_status_idx
  on daily_digest_runs (status, scheduled_for);
