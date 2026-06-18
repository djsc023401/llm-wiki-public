from __future__ import annotations

from collections.abc import Mapping
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg.types.json import Jsonb

from .config import Settings, load_settings
from .db import connect, fetch_all, fetch_one


PERSONALIZATION_ID = "default"
NOTIFICATION_CHANNELS = {"pwa", "telegram"}
WORKFLOW_MODES = {"generic", "personal"}
WORKFLOW_MODE_LABELS = {
    "generic": "Generic knowledge workspace",
    "personal": "Personal operating workspace",
}
PROFILE_FIELDS = {
    "frequent_people": "Frequent people",
    "frequent_places": "Frequent places",
    "active_projects": "Active projects",
    "life_categories": "Life categories",
}
PROFILE_MARKDOWN_LABELS = {
    "frequent_people": "자주 등장하는 사람",
    "frequent_places": "자주 등장하는 장소",
    "active_projects": "진행 중인 프로젝트",
    "life_categories": "생활 카테고리",
}
PERSONAL_HINT_FIELDS = {
    "aliases": "Aliases",
    "priority_terms": "Priority terms",
    "custom_facets": "Custom facets",
    "preference_rules": "Preference rules",
}
PERSONAL_HINT_MARKDOWN_LABELS = {
    "aliases": "별칭",
    "priority_terms": "우선순위 용어",
    "custom_facets": "사용자 분류 축",
    "preference_rules": "답변 선호 규칙",
}
PROFILE_SUGGESTION_LIMIT = 8
PROFILE_SUGGESTION_SCAN_LIMIT = 500
PEOPLE_ENTITY_TYPE_HINTS = {
    "person",
    "people",
    "human",
    "인물",
    "사람",
}
PLACE_ENTITY_TYPE_HINTS = {
    "place",
    "location",
    "venue",
    "장소",
    "위치",
    "지역",
}
PROJECT_ENTITY_TYPE_HINTS = {
    "project",
    "프로젝트",
}
OVERBROAD_RECORD_ONLY_TERMS = {
    "완료",
    "완료함",
    "완료됨",
    "완료했다",
    "처리",
    "기록",
    "예약",
    "구매",
    "주문",
    "결제",
    "신청",
    "제출",
    "방문",
    "done",
    "completed",
    "finished",
    "resolved",
}
OVERBROAD_FOLLOW_UP_TERMS = {
    "필요",
    "확인",
    "후속",
    "할 일",
    "알림",
    "체크",
    "task",
    "todo",
    "follow",
    "remind",
    "reminder",
}
SECRET_LIKE_VALUE_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|credential)\s*[:=]\s*\S+"),
    re.compile(r"(?i)^sk-(?:proj-)?[A-Za-z0-9_-]{16,}$"),
    re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$"),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}$"),
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^/\s:]+:[^@\s]+@"),
    re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[0-1]))(?:\.\d{1,3}){2}\b"),
    re.compile(r"(?i)(?:[A-Z]:\\Users\\[^\\\s]+|/home/[^/\s]+)(?:[/\\]|\b)"),
]
DEFAULT_PERSONALIZATION_SETTINGS = {
    "id": PERSONALIZATION_ID,
    "workflow_mode": "generic",
    "timezone": "Asia/Seoul",
    "default_schedule_days": 30,
    "daily_digest_time": "08:00",
    "default_reminder_minutes": 0,
    "default_notification_channels": ["pwa", "telegram"],
    "personal_terms": [],
    "classification_seeds": [],
    "record_only_terms": [],
    "follow_up_terms": [],
    "frequent_people": [],
    "frequent_places": [],
    "active_projects": [],
    "life_categories": [],
    "aliases": [],
    "priority_terms": [],
    "custom_facets": [],
    "preference_rules": [],
    "metadata": {},
}


def ai_personalization_context(settings: Settings | None = None) -> dict:
    value = get_personalization_settings(settings)
    return {
        "workflow_mode": _validate_workflow_mode(
            value.get("workflow_mode") or DEFAULT_PERSONALIZATION_SETTINGS["workflow_mode"]
        ),
        "timezone": value.get("timezone") or DEFAULT_PERSONALIZATION_SETTINGS["timezone"],
        "default_schedule_days": value.get("default_schedule_days")
        or DEFAULT_PERSONALIZATION_SETTINGS["default_schedule_days"],
        "daily_digest_time": value.get("daily_digest_time") or DEFAULT_PERSONALIZATION_SETTINGS["daily_digest_time"],
        "default_reminder_minutes": _validate_default_reminder_minutes(
            value.get("default_reminder_minutes")
            if value.get("default_reminder_minutes") is not None
            else DEFAULT_PERSONALIZATION_SETTINGS["default_reminder_minutes"]
        ),
        "default_notification_channels": _validate_notification_channels(
            value.get("default_notification_channels")
            or DEFAULT_PERSONALIZATION_SETTINGS["default_notification_channels"]
        ),
        "personal_terms": _validate_text_list(value.get("personal_terms")),
        "classification_seeds": _validate_text_list(value.get("classification_seeds")),
        "record_only_terms": _validate_policy_terms(
            value.get("record_only_terms"),
            overbroad_terms=OVERBROAD_RECORD_ONLY_TERMS,
        ),
        "follow_up_terms": _validate_policy_terms(
            value.get("follow_up_terms"),
            overbroad_terms=OVERBROAD_FOLLOW_UP_TERMS,
        ),
        **{field: _validate_text_list(value.get(field)) for field in PROFILE_FIELDS},
        **{field: _validate_text_list(value.get(field)) for field in PERSONAL_HINT_FIELDS},
    }


def personalization_schedule_horizon_days(value: Mapping[str, object] | None) -> int:
    if not isinstance(value, Mapping):
        return int(DEFAULT_PERSONALIZATION_SETTINGS["default_schedule_days"])
    return _safe_days(value.get("default_schedule_days"))


def personalization_prompt_lines(value: object) -> list[str]:
    context = _normalize_ai_context(value)
    if not context:
        return []
    lines = [
        "Personalization context:",
        f"- Workflow mode: `{context['workflow_mode']}` ({WORKFLOW_MODE_LABELS[context['workflow_mode']]})",
        f"- Default timezone: `{context['timezone']}`",
        f"- Default schedule horizon: `{context['default_schedule_days']} days`",
        f"- Daily digest time: `{context['daily_digest_time']}`",
        f"- Default reminder lead time: `{context['default_reminder_minutes']} minutes`",
    ]
    channels = context["default_notification_channels"]
    if channels:
        lines.append("- Preferred notification channels: " + ", ".join(f"`{item}`" for item in channels))
    terms = context["personal_terms"]
    if terms:
        lines.append("- Personal terms: " + ", ".join(f"`{item}`" for item in terms))
    seeds = context["classification_seeds"]
    if seeds:
        lines.append("- Classification seeds: " + ", ".join(f"`{item}`" for item in seeds))
    record_terms = context["record_only_terms"]
    if record_terms:
        lines.append("- Record-only terms: " + ", ".join(f"`{item}`" for item in record_terms))
    follow_terms = context["follow_up_terms"]
    if follow_terms:
        lines.append("- Follow-up terms: " + ", ".join(f"`{item}`" for item in follow_terms))
    for field, label in PROFILE_FIELDS.items():
        values = context[field]
        if values:
            lines.append(f"- {label}: " + ", ".join(f"`{item}`" for item in values))
    for field, label in PERSONAL_HINT_FIELDS.items():
        values = context[field]
        if values:
            lines.append(f"- {label}: " + ", ".join(f"`{item}`" for item in values))
    lines.extend(
        [
            "- Treat personal terms, classification seeds, profile items, aliases, priority terms, custom facets, and preference rules as user-specific hints, not standalone facts.",
            "- Never infer ownership, possession, investment holdings, relationships, visits, appointments, or completed actions from personalization hints alone.",
            "- Treat record-only terms as phrases that usually describe completed or non-actionable records, not future schedules.",
            "- Treat follow-up terms as phrases that may indicate a task or follow-up only when the source evidence supports future action.",
            "- Use default reminder lead time and preferred channels only after the source supports a real actionable time candidate; they must not create time candidates by themselves.",
            "- In `personal` workflow mode, optimize summaries and follow-ups for the user's personal operating flow, while still requiring source evidence.",
            "- In `generic` workflow mode, keep interpretation neutral and reusable across users.",
            "- Prefer these terms when they match source evidence; do not force unrelated tags, topics, or entities.",
            "- Use aliases only to recognize alternate names in source evidence; do not merge unrelated entities without evidence.",
            "- Use priority terms only as ranking or review hints; do not create new facts from them.",
            "- Use custom facets as optional classification dimensions when the source evidence fits them.",
            "- Use preference rules to shape answer style and review priority only when they do not conflict with source evidence.",
            "- If a hint helps choose a tag, topic, or entity name, keep the suggestion reviewable and cite the matching source evidence.",
            "- For ambiguous source times without an explicit timezone, use the Default timezone.",
            "- Use personal hints to interpret wording and categories, but never create schedules, reminders, tasks, topics, or entities without source evidence.",
        ]
    )
    return lines


def personalization_markdown_section(value: object) -> str:
    context = _normalize_ai_context(value)
    if not context:
        return ""
    rows = [
        ("운영 모드", "개인 운영" if context["workflow_mode"] == "personal" else "범용"),
        ("기본 시간대", str(context["timezone"])),
        ("일정 조회 범위", f"{context['default_schedule_days']}일"),
        ("하루 요약 시간", str(context["daily_digest_time"])),
        (
            "기본 미리 알림",
            f"{context['default_reminder_minutes']}분 전"
            if context["default_reminder_minutes"] > 0
            else "사용 안 함",
        ),
    ]
    if context["default_notification_channels"]:
        rows.append(("선호 알림 채널", ", ".join(context["default_notification_channels"])))
    if context["personal_terms"]:
        rows.append(("개인 용어", ", ".join(context["personal_terms"])))
    if context["classification_seeds"]:
        rows.append(("분류 기준", ", ".join(context["classification_seeds"])))
    if context["record_only_terms"]:
        rows.append(("기록 전용 용어", ", ".join(context["record_only_terms"])))
    if context["follow_up_terms"]:
        rows.append(("후속 확인 용어", ", ".join(context["follow_up_terms"])))
    for field, label in PROFILE_MARKDOWN_LABELS.items():
        if context[field]:
            rows.append((label, ", ".join(context[field])))
    for field, label in PERSONAL_HINT_MARKDOWN_LABELS.items():
        if context[field]:
            rows.append((label, ", ".join(context[field])))
    table = [
        "| 항목 | 값 |",
        "| --- | --- |",
        *[f"| {_markdown_table_cell(name)} | {_markdown_table_cell(value)} |" for name, value in rows],
    ]
    return "\n".join(
        [
            "## 개인화 참고 (비근거)",
            "",
            "이 값은 사용자가 저장한 개인 기본값입니다. 원문 근거나 사실 데이터가 아니라 해석과 분류를 돕는 힌트로만 사용하세요.",
            "이 블록만으로 보유, 방문, 관계, 일정, 알림, 완료 사실을 만들거나 추출된 사실/근거 셀에 인용하지 마세요.",
            "원문과 충돌하면 원문과 사용자 피드백을 우선하고, 관련 없는 값은 억지로 적용하지 마세요.",
            "",
            *table,
            "",
        ]
    )


def get_personalization_settings(settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            """
            select id, timezone, default_schedule_days, daily_digest_time,
                   default_reminder_minutes,
                   default_notification_channels, personal_terms,
                   classification_seeds, record_only_terms, follow_up_terms,
                   metadata, updated_at
              from personalization_settings
             where id = %s
            """,
            (PERSONALIZATION_ID,),
        )
    if not row:
        return _default_settings_for(resolved)
    return _row_to_settings(row)


def personalization_profile_suggestions(settings: Settings | None = None) -> dict:
    """Return reviewable profile candidates from existing notes.

    Suggestions are intentionally one-way hints. They are not persisted here and
    must not be treated as evidence by AI processing.
    """

    resolved = settings or load_settings()
    current = get_personalization_settings(resolved)
    existing = {
        field: {str(item).strip().casefold() for item in current.get(field, []) or [] if str(item).strip()}
        for field in PROFILE_FIELDS
    }
    buckets: dict[str, dict[str, dict[str, object]]] = {field: {} for field in PROFILE_FIELDS}
    with connect(resolved) as conn:
        rows = fetch_all(
            conn,
            """
            select kind, status, title, metadata, updated_at
              from notes
             where deleted_at is null
               and status in ('active', 'needs_review')
               and kind in ('source', 'topic', 'entity')
             order by updated_at desc, created_at desc, id desc
             limit %s
            """,
            (PROFILE_SUGGESTION_SCAN_LIMIT,),
        )

    for row in rows:
        kind = str(row.get("kind") or "")
        title = str(row.get("title") or "").strip()
        metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        if kind == "entity":
            field = _profile_field_for_entity_type(metadata.get("entity_type"))
            if field:
                _add_profile_suggestion(
                    buckets,
                    existing,
                    field,
                    title,
                    source="대상",
                    reason=f"대상 유형: {metadata.get('entity_type')}",
                )
            continue
        if kind == "topic":
            _add_profile_suggestion(
                buckets,
                existing,
                "life_categories",
                title,
                source="주제",
                reason="승인된 주제 노트",
            )
            continue
        if kind == "source":
            for value in _metadata_string_list(metadata.get("manual_tags")):
                _add_profile_suggestion(
                    buckets,
                    existing,
                    "life_categories",
                    value,
                    source="소스 태그",
                    reason="소스 노트 태그",
                )
            for value in _metadata_string_list(metadata.get("manual_topics")):
                _add_profile_suggestion(
                    buckets,
                    existing,
                    "life_categories",
                    value,
                    source="소스 주제",
                    reason="소스 노트 주제",
                )
            for value in _metadata_item_titles(metadata.get("approved_topics")):
                _add_profile_suggestion(
                    buckets,
                    existing,
                    "life_categories",
                    value,
                    source="승인된 주제",
                    reason="소스에서 승인된 주제",
                )

    result: dict[str, list[dict[str, object]]] = {}
    for field, bucket in buckets.items():
        ranked = sorted(
            bucket.values(),
            key=lambda item: (-int(item.get("count") or 0), str(item.get("value") or "").casefold()),
        )
        result[field] = ranked[:PROFILE_SUGGESTION_LIMIT]
    return result


def apply_personalization_profile_suggestions(
    payload: Mapping[str, object],
    settings: Settings | None = None,
) -> dict:
    """Merge explicitly selected profile suggestions into personalization settings."""

    resolved = settings or load_settings()
    current = get_personalization_settings(resolved)
    next_profile: dict[str, list[str]] = {}
    applied: dict[str, list[str]] = {}
    for field in PROFILE_FIELDS:
        existing = _validate_text_list(current.get(field))
        existing_keys = {item.casefold() for item in existing}
        selected = _validate_text_list(payload.get(field))
        added: list[str] = []
        for value in selected:
            key = value.casefold()
            if key in existing_keys:
                continue
            existing.append(value)
            existing_keys.add(key)
            added.append(value)
        next_profile[field] = existing
        applied[field] = added
    applied_count = sum(len(values) for values in applied.values())
    if applied_count <= 0:
        raise ValueError("no new profile suggestions selected")
    updated = update_personalization_settings(next_profile, resolved)
    return {
        "settings": updated,
        "applied": applied,
        "applied_count": applied_count,
    }


def update_personalization_settings(payload: Mapping[str, object], settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    current = get_personalization_settings(resolved)
    metadata = _validate_metadata(payload.get("metadata", current.get("metadata") or {}))
    workflow_mode = _validate_workflow_mode(
        payload.get("workflow_mode", metadata.get("workflow_mode", current.get("workflow_mode")))
    )
    metadata["workflow_mode"] = workflow_mode
    metadata["profile"] = {
        field: _validate_text_list(payload.get(field, current.get(field))) for field in PROFILE_FIELDS
    }
    metadata["hints"] = {
        field: _validate_text_list(payload.get(field, current.get(field))) for field in PERSONAL_HINT_FIELDS
    }
    next_value = {
        "workflow_mode": workflow_mode,
        "timezone": _validate_timezone(payload.get("timezone", current["timezone"])),
        "default_schedule_days": _validate_schedule_days(
            payload.get("default_schedule_days", current["default_schedule_days"])
        ),
        "daily_digest_time": _validate_daily_digest_time(
            payload.get("daily_digest_time", current["daily_digest_time"])
        ),
        "default_reminder_minutes": _validate_default_reminder_minutes(
            payload.get("default_reminder_minutes", current["default_reminder_minutes"])
        ),
        "default_notification_channels": _validate_notification_channels(
            payload.get("default_notification_channels", current["default_notification_channels"])
        ),
        "personal_terms": _validate_text_list(payload.get("personal_terms", current["personal_terms"])),
        "classification_seeds": _validate_text_list(
            payload.get("classification_seeds", current["classification_seeds"])
        ),
        "record_only_terms": _validate_policy_terms(
            payload.get("record_only_terms", current["record_only_terms"]),
            overbroad_terms=OVERBROAD_RECORD_ONLY_TERMS,
        ),
        "follow_up_terms": _validate_policy_terms(
            payload.get("follow_up_terms", current["follow_up_terms"]),
            overbroad_terms=OVERBROAD_FOLLOW_UP_TERMS,
        ),
        **metadata["profile"],
        **metadata["hints"],
        "metadata": metadata,
    }
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            """
            insert into personalization_settings (
              id, timezone, default_schedule_days, daily_digest_time,
              default_reminder_minutes,
              default_notification_channels, personal_terms,
              classification_seeds, record_only_terms, follow_up_terms,
              metadata, updated_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            on conflict (id) do update
               set timezone = excluded.timezone,
                   default_schedule_days = excluded.default_schedule_days,
                   daily_digest_time = excluded.daily_digest_time,
                   default_reminder_minutes = excluded.default_reminder_minutes,
                   default_notification_channels = excluded.default_notification_channels,
                   personal_terms = excluded.personal_terms,
                   classification_seeds = excluded.classification_seeds,
                   record_only_terms = excluded.record_only_terms,
                   follow_up_terms = excluded.follow_up_terms,
                   metadata = excluded.metadata,
                   updated_at = now()
            returning id, timezone, default_schedule_days, daily_digest_time,
                      default_reminder_minutes,
                      default_notification_channels, personal_terms,
                      classification_seeds, record_only_terms, follow_up_terms,
                      metadata, updated_at
            """,
            (
                PERSONALIZATION_ID,
                next_value["timezone"],
                next_value["default_schedule_days"],
                next_value["daily_digest_time"],
                next_value["default_reminder_minutes"],
                Jsonb(next_value["default_notification_channels"]),
                Jsonb(next_value["personal_terms"]),
                Jsonb(next_value["classification_seeds"]),
                Jsonb(next_value["record_only_terms"]),
                Jsonb(next_value["follow_up_terms"]),
                Jsonb(next_value["metadata"]),
            ),
        )
        conn.commit()
    if not row:
        raise RuntimeError("personalization_settings_not_saved")
    return _row_to_settings(row)


def parse_personalization_form(form: Mapping[str, object]) -> dict:
    return {
        "workflow_mode": form.get("workflow_mode"),
        "timezone": form.get("timezone"),
        "default_schedule_days": form.get("default_schedule_days"),
        "daily_digest_time": form.get("daily_digest_time"),
        "default_reminder_minutes": form.get("default_reminder_minutes"),
        "default_notification_channels": _form_list(form, "default_notification_channels"),
        "personal_terms": _lines_to_list(str(form.get("personal_terms") or "")),
        "classification_seeds": _lines_to_list(str(form.get("classification_seeds") or "")),
        "record_only_terms": _lines_to_list(str(form.get("record_only_terms") or "")),
        "follow_up_terms": _lines_to_list(str(form.get("follow_up_terms") or "")),
        "frequent_people": _lines_to_list(str(form.get("frequent_people") or "")),
        "frequent_places": _lines_to_list(str(form.get("frequent_places") or "")),
        "active_projects": _lines_to_list(str(form.get("active_projects") or "")),
        "life_categories": _lines_to_list(str(form.get("life_categories") or "")),
        "aliases": _lines_to_list(str(form.get("aliases") or "")),
        "priority_terms": _lines_to_list(str(form.get("priority_terms") or "")),
        "custom_facets": _lines_to_list(str(form.get("custom_facets") or "")),
        "preference_rules": _lines_to_list(str(form.get("preference_rules") or "")),
    }


def parse_profile_suggestion_form(form: Mapping[str, object]) -> dict:
    return {field: _form_list(form, field) for field in PROFILE_FIELDS}


def _row_to_settings(row: Mapping[str, object]) -> dict:
    metadata = _validate_metadata(row.get("metadata"))
    profile = _profile_from_metadata(metadata)
    hints = _hints_from_metadata(metadata)
    result = dict(DEFAULT_PERSONALIZATION_SETTINGS)
    result.update(
        {
            "id": str(row.get("id") or PERSONALIZATION_ID),
            "workflow_mode": _validate_workflow_mode(
                metadata.get("workflow_mode"),
                fallback=str(DEFAULT_PERSONALIZATION_SETTINGS["workflow_mode"]),
            ),
            "timezone": str(row.get("timezone") or DEFAULT_PERSONALIZATION_SETTINGS["timezone"]),
            "default_schedule_days": int(
                row.get("default_schedule_days") or DEFAULT_PERSONALIZATION_SETTINGS["default_schedule_days"]
            ),
            "daily_digest_time": str(row.get("daily_digest_time") or DEFAULT_PERSONALIZATION_SETTINGS["daily_digest_time"]),
            "default_reminder_minutes": _validate_default_reminder_minutes(
                row.get("default_reminder_minutes")
                if row.get("default_reminder_minutes") is not None
                else DEFAULT_PERSONALIZATION_SETTINGS["default_reminder_minutes"]
            ),
            "default_notification_channels": _validate_notification_channels(row.get("default_notification_channels")),
            "personal_terms": _validate_text_list(row.get("personal_terms")),
            "classification_seeds": _validate_text_list(row.get("classification_seeds")),
            "record_only_terms": _validate_policy_terms(
                row.get("record_only_terms"),
                overbroad_terms=OVERBROAD_RECORD_ONLY_TERMS,
            ),
            "follow_up_terms": _validate_policy_terms(
                row.get("follow_up_terms"),
                overbroad_terms=OVERBROAD_FOLLOW_UP_TERMS,
            ),
            **profile,
            **hints,
            "metadata": metadata,
        }
    )
    if row.get("updated_at") is not None:
        result["updated_at"] = row["updated_at"]
    return result


def _validate_timezone(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("timezone is required")
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid timezone") from exc
    return text[:80]


def _validate_workflow_mode(value: object, *, fallback: str | None = None) -> str:
    text = str(value or "").strip().lower()
    if text in WORKFLOW_MODES:
        return text
    if fallback is not None:
        return fallback
    raise ValueError("workflow_mode must be generic or personal")


def _validate_schedule_days(value: object) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("default_schedule_days must be an integer") from exc
    if days < 1 or days > 365:
        raise ValueError("default_schedule_days must be between 1 and 365")
    return days


def _validate_daily_digest_time(value: object) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", text):
        raise ValueError("daily_digest_time must use HH:MM")
    return text


def _validate_default_reminder_minutes(value: object) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("default_reminder_minutes must be an integer") from exc
    if minutes < 0 or minutes > 10_080:
        raise ValueError("default_reminder_minutes must be between 0 and 10080")
    return minutes


def _validate_notification_channels(value: object) -> list[str]:
    raw_items: list[object]
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    else:
        raw_items = []
    result: list[str] = []
    for item in raw_items:
        channel = str(item or "").strip()
        if channel not in NOTIFICATION_CHANNELS:
            continue
        if channel not in result:
            result.append(channel)
    return result


def _validate_text_list(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = _lines_to_list(value)
        value = decoded
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if looks_like_secret_text(text):
            continue
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text[:120])
    return result[:200]


def _validate_policy_terms(value: object, *, overbroad_terms: set[str]) -> list[str]:
    result: list[str] = []
    for text in _validate_text_list(value):
        normalized = re.sub(r"\s+", " ", text).strip().casefold()
        compact = re.sub(r"\s+", "", normalized)
        if not compact or len(compact) < 3:
            continue
        if normalized in overbroad_terms or compact in overbroad_terms:
            continue
        result.append(text)
    return result


def looks_like_secret_text(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in SECRET_LIKE_VALUE_PATTERNS)


def _validate_metadata(value: object) -> dict:
    if not isinstance(value, Mapping):
        return {}
    metadata: dict[str, object] = {}
    if "workflow_mode" in value:
        metadata["workflow_mode"] = _validate_workflow_mode(value.get("workflow_mode"))
    if "profile" in value:
        metadata["profile"] = _profile_from_metadata(value)
    if "hints" in value:
        metadata["hints"] = _hints_from_metadata(value)
    return metadata


def _profile_from_metadata(metadata: Mapping[str, object]) -> dict[str, list[str]]:
    raw = metadata.get("profile")
    if not isinstance(raw, Mapping):
        raw = {}
    return {field: _validate_text_list(raw.get(field)) for field in PROFILE_FIELDS}


def _hints_from_metadata(metadata: Mapping[str, object]) -> dict[str, list[str]]:
    raw = metadata.get("hints")
    if not isinstance(raw, Mapping):
        raw = {}
    return {field: _validate_text_list(raw.get(field)) for field in PERSONAL_HINT_FIELDS}


def _profile_field_for_entity_type(value: object) -> str | None:
    normalized = re.sub(r"[\s/_-]+", "", str(value or "")).casefold()
    if not normalized:
        return None
    if any(hint in normalized for hint in PEOPLE_ENTITY_TYPE_HINTS):
        return "frequent_people"
    if any(hint in normalized for hint in PLACE_ENTITY_TYPE_HINTS):
        return "frequent_places"
    if any(hint in normalized for hint in PROJECT_ENTITY_TYPE_HINTS):
        return "active_projects"
    return None


def _add_profile_suggestion(
    buckets: dict[str, dict[str, dict[str, object]]],
    existing: Mapping[str, set[str]],
    field: str,
    value: object,
    *,
    source: str,
    reason: str,
) -> None:
    if field not in buckets:
        return
    values = _validate_text_list([value])
    if not values:
        return
    text = values[0]
    key = text.casefold()
    if key in existing.get(field, set()):
        return
    bucket = buckets[field]
    if key not in bucket:
        bucket[key] = {
            "value": text,
            "source": str(source or "")[:80],
            "reason": str(reason or "")[:160],
            "count": 0,
        }
    bucket[key]["count"] = int(bucket[key].get("count") or 0) + 1


def _metadata_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return _validate_text_list(value)


def _metadata_item_titles(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            result.extend(_validate_text_list([item.get("title")]))
        else:
            result.extend(_validate_text_list([item]))
    return result


def _normalize_ai_context(value: object) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    return {
        "workflow_mode": _validate_workflow_mode(
            value.get("workflow_mode"),
            fallback=str(DEFAULT_PERSONALIZATION_SETTINGS["workflow_mode"]),
        ),
        "timezone": _safe_text(value.get("timezone"), DEFAULT_PERSONALIZATION_SETTINGS["timezone"]),
        "default_schedule_days": _safe_days(value.get("default_schedule_days")),
        "daily_digest_time": _safe_digest_time(value.get("daily_digest_time")),
        "default_reminder_minutes": _safe_reminder_minutes(value.get("default_reminder_minutes")),
        "default_notification_channels": _validate_notification_channels(value.get("default_notification_channels")),
        "personal_terms": _validate_text_list(value.get("personal_terms")),
        "classification_seeds": _validate_text_list(value.get("classification_seeds")),
        "record_only_terms": _validate_policy_terms(
            value.get("record_only_terms"),
            overbroad_terms=OVERBROAD_RECORD_ONLY_TERMS,
        ),
        "follow_up_terms": _validate_policy_terms(
            value.get("follow_up_terms"),
            overbroad_terms=OVERBROAD_FOLLOW_UP_TERMS,
        ),
        **{field: _validate_text_list(value.get(field)) for field in PROFILE_FIELDS},
        **{field: _validate_text_list(value.get(field)) for field in PERSONAL_HINT_FIELDS},
    }


def _safe_text(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text[:80] if text else fallback


def _safe_days(value: object) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return int(DEFAULT_PERSONALIZATION_SETTINGS["default_schedule_days"])
    return max(1, min(days, 365))


def _safe_digest_time(value: object) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", text) else str(
        DEFAULT_PERSONALIZATION_SETTINGS["daily_digest_time"]
    )


def _safe_reminder_minutes(value: object) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return int(DEFAULT_PERSONALIZATION_SETTINGS["default_reminder_minutes"])
    return max(0, min(minutes, 10_080))


def _default_settings_for(settings: Settings) -> dict:
    workflow_mode = _validate_workflow_mode(
        getattr(settings, "personalization_default_workflow_mode", None),
        fallback=str(DEFAULT_PERSONALIZATION_SETTINGS["workflow_mode"]),
    )
    result = dict(DEFAULT_PERSONALIZATION_SETTINGS)
    result["workflow_mode"] = workflow_mode
    result["metadata"] = {
        "workflow_mode": workflow_mode,
        "profile": {field: [] for field in PROFILE_FIELDS},
        "hints": {field: [] for field in PERSONAL_HINT_FIELDS},
    }
    return result


def _markdown_table_cell(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).replace("|", "\\|").strip()


def _lines_to_list(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _form_list(form: Mapping[str, object], name: str) -> list[str]:
    getter = getattr(form, "getlist", None)
    if callable(getter):
        return [str(item) for item in getter(name)]
    value = form.get(name)
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]
