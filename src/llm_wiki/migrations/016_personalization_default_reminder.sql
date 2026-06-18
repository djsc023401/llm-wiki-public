alter table personalization_settings
  add column if not exists default_reminder_minutes integer not null default 0;

do $$
begin
  if not exists (
    select 1
      from pg_constraint
     where conname = 'personalization_default_reminder_minutes_check'
  ) then
    alter table personalization_settings
      add constraint personalization_default_reminder_minutes_check
      check (default_reminder_minutes between 0 and 10080);
  end if;
end $$;
