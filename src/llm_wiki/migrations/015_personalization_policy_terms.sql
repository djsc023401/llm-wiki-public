alter table personalization_settings
  add column if not exists record_only_terms jsonb not null default '[]'::jsonb,
  add column if not exists follow_up_terms jsonb not null default '[]'::jsonb;
