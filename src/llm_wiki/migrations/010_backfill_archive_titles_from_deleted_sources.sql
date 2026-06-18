with candidates as (
  select
      archive.id,
      archive.version,
      archive.body_markdown,
      archive.metadata,
      left('원문 - ' || source.title, 300) as new_title
    from notes archive
    join notes source
      on source.id = archive.metadata ->> 'target_note_id'
   where archive.kind = 'archive'
     and archive.status = 'archived'
     and archive.deleted_at is null
     and lower(trim(coalesce(archive.title, ''))) in (
       '',
       'untitled',
       'untitled note',
       'untitled source',
       '제목은 ai가 정합니다',
       '제목 없는 노트',
       '제목 없는 웹 메모',
       '제목 없는 소스',
       '제목 없는 주제',
       '제목 없는 대상',
       '제목 없는 로그'
     )
     and lower(trim(coalesce(source.title, ''))) not in (
       '',
       'untitled',
       'untitled note',
       'untitled source',
       '제목은 ai가 정합니다',
       '제목 없는 노트',
       '제목 없는 웹 메모',
       '제목 없는 소스',
       '제목 없는 주제',
       '제목 없는 대상',
       '제목 없는 로그'
     )
),
updated as (
  update notes archive
     set title = candidates.new_title,
         version = archive.version + 1,
         updated_at = now()
    from candidates
   where archive.id = candidates.id
  returning
      archive.id,
      archive.version,
      archive.title,
      archive.body_markdown,
      archive.metadata
)
insert into note_revisions (
  id,
  note_id,
  version,
  title,
  body_markdown,
  metadata,
  change_source,
  created_by
)
select
    'rev_archive_title_backfill_deleted_source_' || updated.id,
    updated.id,
    updated.version,
    updated.title,
    updated.body_markdown,
    updated.metadata,
    'operator',
    'migration-010'
  from updated
on conflict (id) do nothing;
