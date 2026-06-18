create table if not exists time_items (
  id text primary key,
  note_id text references notes(id) on delete set null,
  source_note_id text references notes(id) on delete set null,
  source_suggestion_key text,
  kind text not null,
  status text not null default 'active',
  title text not null,
  body_markdown text not null default '',
  start_at timestamptz,
  end_at timestamptz,
  due_at timestamptz,
  remind_at timestamptz,
  timezone text not null default 'Asia/Seoul',
  recurrence_rule text,
  notification_channels jsonb not null default '["pwa"]'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint time_items_kind_check check (
    kind in ('task', 'reminder', 'event', 'deadline', 'follow_up')
  ),
  constraint time_items_status_check check (
    status in ('active', 'completed', 'cancelled', 'dismissed')
  )
);

create index if not exists time_items_status_remind_idx
  on time_items (status, remind_at);

create index if not exists time_items_note_idx
  on time_items (note_id);

create index if not exists time_items_source_note_idx
  on time_items (source_note_id);

create unique index if not exists time_items_source_suggestion_unique_idx
  on time_items (source_note_id, source_suggestion_key)
  where source_note_id is not null and source_suggestion_key is not null;

create table if not exists notification_subscriptions (
  id text primary key,
  channel text not null default 'pwa',
  status text not null default 'active',
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  user_agent text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_seen_at timestamptz,
  disabled_at timestamptz,
  last_error_at timestamptz,
  error_message text,
  constraint notification_subscriptions_channel_check check (
    channel in ('pwa')
  ),
  constraint notification_subscriptions_status_check check (
    status in ('active', 'disabled')
  )
);

create index if not exists notification_subscriptions_status_idx
  on notification_subscriptions (channel, status, updated_at desc);

create table if not exists notification_deliveries (
  id text primary key,
  time_item_id text references time_items(id) on delete cascade,
  channel text not null,
  status text not null default 'queued',
  scheduled_for timestamptz not null,
  sent_at timestamptz,
  error_message text,
  hidden_at timestamptz,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint notification_deliveries_channel_check check (
    channel in ('pwa', 'telegram')
  ),
  constraint notification_deliveries_status_check check (
    status in ('queued', 'sending', 'sent', 'failed', 'cancelled')
  )
);

create unique index if not exists notification_deliveries_pending_time_channel_unique_idx
  on notification_deliveries (time_item_id, channel)
  where time_item_id is not null
    and status in ('queued', 'sending', 'failed')
    and hidden_at is null;

create index if not exists notification_deliveries_status_idx
  on notification_deliveries (status, scheduled_for);
