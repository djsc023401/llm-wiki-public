alter table suggestion_decisions
  drop constraint if exists suggestion_decisions_kind_check;

alter table suggestion_decisions
  add constraint suggestion_decisions_kind_check check (
    suggestion_kind in ('topic', 'entity', 'tag', 'time', 'classification_change')
  );
