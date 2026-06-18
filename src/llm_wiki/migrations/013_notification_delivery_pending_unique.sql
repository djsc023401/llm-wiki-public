drop index if exists notification_deliveries_time_channel_unique_idx;

create unique index if not exists notification_deliveries_pending_time_channel_unique_idx
  on notification_deliveries (time_item_id, channel)
  where time_item_id is not null
    and status in ('queued', 'sending', 'failed')
    and hidden_at is null;
