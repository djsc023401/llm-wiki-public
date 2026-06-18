alter table notification_deliveries
  add column if not exists hidden_at timestamptz;

create index if not exists notification_deliveries_visible_status_idx
  on notification_deliveries (status, scheduled_for)
  where hidden_at is null;
