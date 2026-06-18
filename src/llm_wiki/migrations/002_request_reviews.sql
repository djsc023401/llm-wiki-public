create table if not exists processing_request_reviews (
  request_id text primary key references processing_requests(id) on delete cascade,
  outcome text not null,
  note text,
  reviewed_by text,
  reviewed_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint processing_request_reviews_outcome_check check (
    outcome in ('useful', 'noisy', 'unsafe', 'duplicated', 'manual_rewrite')
  )
);

create index if not exists processing_request_reviews_outcome_idx
  on processing_request_reviews (outcome, updated_at);
