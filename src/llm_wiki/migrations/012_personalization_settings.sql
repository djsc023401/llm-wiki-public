create table if not exists personalization_settings (
  id text primary key default 'default',
  timezone text not null default 'Asia/Seoul',
  default_schedule_days integer not null default 30,
  daily_digest_time text not null default '08:00',
  default_reminder_minutes integer not null default 0,
  default_notification_channels jsonb not null default '["pwa", "telegram"]'::jsonb,
  personal_terms jsonb not null default '[]'::jsonb,
  classification_seeds jsonb not null default '[]'::jsonb,
  record_only_terms jsonb not null default '[]'::jsonb,
  follow_up_terms jsonb not null default '[]'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  constraint personalization_settings_singleton_check check (id = 'default'),
  constraint personalization_schedule_days_check check (
    default_schedule_days between 1 and 365
  ),
  constraint personalization_daily_digest_time_check check (
    daily_digest_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
  ),
  constraint personalization_default_reminder_minutes_check check (
    default_reminder_minutes between 0 and 10080
  )
);
