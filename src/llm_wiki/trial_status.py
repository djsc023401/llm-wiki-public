from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

from .config import Settings, load_settings
from .db import connect, fetch_one
from .notes_store import create_note


WEB_TRIAL_MARKER = "2026-06-04-w7-trial"
WEB_TRIAL_FEEDBACK_TYPE = "w7-web-trial"
TRIAL_FEEDBACK_OUTCOMES = {"simpler", "not_simpler", "unclear"}
WEB_NOTES_REQUIRED = 5
PROCESSED_NOTES_REQUIRED = 3
EXPORTED_NOTES_REQUIRED = 3
FEEDBACK_REQUIRED = 1

REAL_WEB_NOTE_FILTER = """
    n.deleted_at is null
    and n.kind in ('inbox', 'archive', 'source', 'topic', 'entity', 'log')
    and n.metadata->>'channel' = 'web'
    and coalesce(n.metadata->>'feedback_type', '') != %(feedback_type)s
    and not (
      coalesce(n.metadata->>'trial_marker', '') = %(trial_marker)s
      or coalesce(n.metadata->>'synthetic', '') = 'true'
      or n.slug like 'w7-web-trial-note-%%'
      or n.title ilike 'W7 Web Trial Note %%'
      or n.title ilike %(trial_marker_pattern)s
      or n.body_markdown ilike %(trial_marker_pattern)s
    )
"""

INITIAL_WEB_REVISION_FILTER = """
    exists (
      select 1
        from note_revisions nr
       where nr.note_id = n.id
         and nr.version = 1
         and nr.change_source = 'web'
         and nr.created_by = 'web-ui'
    )
"""


def get_web_trial_status(settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    params = _trial_params()
    with connect(resolved) as conn:
        web_notes = _count(
            fetch_one(
                conn,
                f"""
                select count(distinct n.id) as count
                  from notes n
                 where {REAL_WEB_NOTE_FILTER}
                   and {INITIAL_WEB_REVISION_FILTER}
                """,
                params,
            )
        )
        processed_notes = _count(
            fetch_one(
                conn,
                f"""
                select count(distinct pr.note_id) as count
                  from processing_requests pr
                  join notes n on n.id = pr.note_id
                 where pr.input_mode = 'db-note'
                   and pr.source = 'web-note'
                   and pr.status = 'succeeded'
                   and {REAL_WEB_NOTE_FILTER}
                   and {INITIAL_WEB_REVISION_FILTER}
                """,
                params,
            )
        )
        exported_source_notes = _count(
            fetch_one(
                conn,
                f"""
                select count(distinct ej.note_id) as count
                  from export_jobs ej
                  join processing_requests pr on pr.target_note_id = ej.note_id
                  join notes n on n.id = pr.note_id
                 where ej.scope = 'note-id'
                   and ej.status = 'succeeded'
                   and pr.input_mode = 'db-note'
                   and pr.source = 'web-note'
                   and pr.status = 'succeeded'
                   and {REAL_WEB_NOTE_FILTER}
                   and {INITIAL_WEB_REVISION_FILTER}
                """,
                params,
            )
        )
        feedback_count = _count(
            fetch_one(
                conn,
                """
                select count(*) as count
                  from notes
                 where deleted_at is null
                   and kind = 'log'
                   and metadata->>'feedback_type' = %(feedback_type)s
                """,
                params,
            )
        )
        latest_feedback = fetch_one(
            conn,
            """
            select metadata->>'outcome' as outcome, updated_at
              from notes
             where deleted_at is null
               and kind = 'log'
               and metadata->>'feedback_type' = %(feedback_type)s
             order by updated_at desc
             limit 1
            """,
            params,
        )

    criteria = {
        "web_notes": {"count": web_notes, "required": WEB_NOTES_REQUIRED, "met": web_notes >= WEB_NOTES_REQUIRED},
        "processed_notes": {
            "count": processed_notes,
            "required": PROCESSED_NOTES_REQUIRED,
            "met": processed_notes >= PROCESSED_NOTES_REQUIRED,
        },
        "exported_source_notes": {
            "count": exported_source_notes,
            "required": EXPORTED_NOTES_REQUIRED,
            "met": exported_source_notes >= EXPORTED_NOTES_REQUIRED,
        },
        "feedback": {
            "count": feedback_count,
            "required": FEEDBACK_REQUIRED,
            "met": feedback_count >= FEEDBACK_REQUIRED,
        },
    }
    return {
        "trial": "w7-web-service",
        "criteria": criteria,
        "ready_for_recommendation": all(item["met"] for item in criteria.values()),
        "latest_feedback": dict(latest_feedback) if latest_feedback else None,
    }


def create_web_trial_feedback(
    payload: Mapping[str, object],
    settings: Settings | None = None,
    *,
    created_by: str = "web-ui",
) -> dict:
    resolved = settings or load_settings()
    outcome = _required_choice(str(payload.get("outcome") or "").strip(), TRIAL_FEEDBACK_OUTCOMES, "outcome")
    note = _clean_text(payload.get("note"), max_length=4000)
    title = f"W7 Web Trial Feedback {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    body = note or f"Outcome: {outcome}"
    return create_note(
        {
            "kind": "log",
            "status": "active",
            "title": title,
            "body_markdown": body,
            "metadata": {
                "channel": "web",
                "feedback_type": WEB_TRIAL_FEEDBACK_TYPE,
                "outcome": outcome,
            },
            "change_source": "web",
            "created_by": created_by,
        },
        resolved,
    )


def _trial_params() -> dict:
    return {
        "feedback_type": WEB_TRIAL_FEEDBACK_TYPE,
        "trial_marker": WEB_TRIAL_MARKER,
        "trial_marker_pattern": f"%{WEB_TRIAL_MARKER}%",
    }


def _count(row: dict | None) -> int:
    if not row:
        return 0
    return int(row.get("count") or 0)


def _required_choice(value: str, choices: set[str], field: str) -> str:
    if value not in choices:
        expected = ", ".join(sorted(choices))
        raise ValueError(f"invalid {field}: expected one of {expected}")
    return value


def _clean_text(value: object, *, max_length: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:max_length]
