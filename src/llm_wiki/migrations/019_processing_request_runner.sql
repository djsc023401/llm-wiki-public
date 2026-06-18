alter table processing_requests
  add column if not exists runner_name text;

create index if not exists processing_requests_runner_status_idx
  on processing_requests (runner_name, status, updated_at);
