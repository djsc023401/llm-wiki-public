from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from llm_wiki.notes_store import create_note, dismiss_source_suggestion
from llm_wiki.personalization import update_personalization_settings
from llm_wiki.time_store import (
    _notification_channels,
    _parse_time_suggestion_section,
    auto_register_time_suggestions_for_source,
    create_time_item,
    create_time_item_from_suggestion,
    list_time_items,
    list_time_suggestions_for_source,
    postpone_time_item,
)


def test_parse_time_suggestion_section_reads_reviewable_schedule_rows():
    markdown = """
# 소스 노트

## 관련

### 일정 제안

| 후보 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A 방문 일정 | event | 2026-07-01T10:00:00+09:00 | 2026-07-01T12:00:00+09:00 |  | 2026-07-01T09:30:00+09:00 | Asia/Seoul | "7월 1일에 방문" | 사용자가 피드백으로 확정 |
| 건강검진 예약 확인 | follow_up |  |  | 2026-06-10 |  | Asia/Seoul | 예약 확인 필요 | |

### 주제 제안
"""

    suggestions = _parse_time_suggestion_section(markdown)

    assert len(suggestions) == 2
    assert suggestions[0]["kind"] == "time"
    assert suggestions[0]["candidate"] == "A 방문 일정"
    assert suggestions[0]["time_kind"] == "event"
    assert suggestions[0]["time_intent"] == "event"
    assert suggestions[0]["start_at"] == "2026-07-01T10:00:00+09:00"
    assert suggestions[0]["remind_at"] == "2026-07-01T09:30:00+09:00"
    assert suggestions[0]["timezone"] == "Asia/Seoul"
    assert suggestions[0]["evidence"] == '"7월 1일에 방문"'
    assert suggestions[0]["registered_time_item_id"] is None
    assert suggestions[1]["time_kind"] == "follow_up"
    assert suggestions[1]["time_intent"] == "follow_up"
    assert suggestions[1]["due_at"] == "2026-06-10"
    assert suggestions[1]["remind_at"] == ""


def test_parse_time_suggestion_section_reads_explicit_intent_rows():
    markdown = """
### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 예약 완료 기록 | 기록 전용 | reminder |  |  |  |  | Asia/Seoul | "예약 완료" | 완료 사실만 기록한다. |
| 방문 일정 | 일정 | event | 2026-07-01T10:00:00+09:00 | | | | Asia/Seoul | "7월 1일 방문" | 실제 방문 일정이다. |
"""

    suggestions = _parse_time_suggestion_section(markdown)

    assert suggestions[0]["time_intent"] == "record"
    assert suggestions[0]["time_kind"] == "reminder"
    assert suggestions[1]["time_intent"] == "event"
    assert suggestions[1]["time_kind"] == "event"


def test_parse_time_suggestion_section_reads_english_record_only_aliases():
    markdown = """
### Time Suggestions

| Candidate | Intent | Type | Start | End | Due | Reminder | Timezone | Evidence | Review note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Payment completed | record-only | reminder | | | | | Asia/Seoul | "payment completed" | record only |
| Form submission | completed record | reminder | | | | | Asia/Seoul | "submitted" | no follow-up |
"""

    suggestions = _parse_time_suggestion_section(markdown)

    assert suggestions[0]["time_intent"] == "record"
    assert suggestions[0]["time_kind"] == "reminder"
    assert suggestions[1]["time_intent"] == "record"
    assert suggestions[1]["time_kind"] == "reminder"


def test_parse_time_suggestion_section_normalizes_korean_intent_aliases():
    markdown = """
### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 치약 구매 | 구매 필요 | task | | | 2026-06-10 | | Asia/Seoul | "사야 함" | |
| 예약 확인 | 예약 확인 | follow_up | | | 2026-06-11 | | Asia/Seoul | "확인 필요" | |
| 주가 관찰 | 투자 관찰 | reminder | | | | | Asia/Seoul | "관찰" | |
"""

    suggestions = _parse_time_suggestion_section(markdown)

    assert suggestions[0]["time_intent"] == "task"
    assert suggestions[0]["time_kind"] == "task"
    assert suggestions[1]["time_intent"] == "follow_up"
    assert suggestions[1]["time_kind"] == "follow_up"
    assert suggestions[2]["time_intent"] == "record"
    assert suggestions[2]["time_kind"] == "reminder"


def test_parse_time_suggestion_section_ignores_none_rows():
    markdown = """
### 일정 제안

| 후보 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 없음 | reminder | | | | | Asia/Seoul | | |
"""

    assert _parse_time_suggestion_section(markdown) == []


def test_notification_channels_rejects_wrong_type():
    assert _notification_channels(None) == ["pwa"]
    assert _notification_channels([]) == []
    assert _notification_channels(["pwa", "telegram", "pwa"]) == ["pwa", "telegram"]

    with pytest.raises(ValueError, match="notification_channels must be a list"):
        _notification_channels("telegram")


def test_create_time_item_uses_personal_timezone_default(db_settings):
    update_personalization_settings({"timezone": "UTC"}, db_settings)

    item = create_time_item(
        {
            "kind": "event",
            "title": "UTC 기본 시간대 일정",
            "start_at": "2026-07-01T10:00:00",
        },
        db_settings,
    )

    assert item["timezone"] == "UTC"
    assert item["start_at"].astimezone(timezone.utc).isoformat().startswith("2026-07-01T10:00:00+00:00")


def test_create_time_item_uses_personal_default_channels(db_settings):
    settings = replace(
        db_settings,
        pwa_vapid_public_key="public-key",
        pwa_vapid_private_key="private-key",
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
    )
    update_personalization_settings({"default_notification_channels": ["telegram", "pwa"]}, settings)

    item = create_time_item(
        {
            "kind": "task",
            "title": "직접 생성 기본 채널",
            "due_at": "2026-06-20T10:00:00+09:00",
        },
        settings,
    )
    no_notification = create_time_item(
        {
            "kind": "task",
            "title": "명시적 알림 없음",
            "due_at": "2026-06-20T10:00:00+09:00",
            "notification_channels": [],
        },
        settings,
    )

    assert item["notification_channels"] == ["telegram", "pwa"]
    assert no_notification["notification_channels"] == []


def test_postpone_time_item_uses_item_timezone_for_tomorrow_morning(db_settings):
    item = create_time_item(
        {
            "kind": "event",
            "title": "시간대 기준 미루기",
            "start_at": "2026-06-10T15:00:00+09:00",
            "end_at": "2026-06-10T17:00:00+09:00",
            "remind_at": "2026-06-10T14:00:00+09:00",
            "timezone": "Asia/Seoul",
        },
        db_settings,
    )

    postponed = postpone_time_item(
        item["id"],
        "tomorrow_morning",
        db_settings,
        now=datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc),
    )

    seoul = ZoneInfo("Asia/Seoul")
    assert postponed is not None
    assert postponed["remind_at"].astimezone(seoul).isoformat().startswith("2026-06-11T09:00:00+09:00")
    assert postponed["start_at"].astimezone(seoul).isoformat().startswith("2026-06-11T10:00:00+09:00")
    assert postponed["end_at"].astimezone(seoul).isoformat().startswith("2026-06-11T12:00:00+09:00")


def test_auto_register_time_suggestions_creates_only_dated_items(db_settings):
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "일정 후보",
            "body_markdown": """
# 일정 후보

### Time Suggestions

| Candidate | Type | Start | End | Due | Reminder | Timezone | Evidence | Review note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A 방문 | event | 2026-07-01T10:00:00+09:00 |  |  | 2026-07-01T09:30:00+09:00 | Asia/Seoul | 방문 약속 | |
| 날짜 없는 확인 | follow_up | | | | | Asia/Seoul | 확인 필요 | |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["failed"] == []
    assert len(result["created"]) == 1
    assert result["created"][0]["title"] == "A 방문"
    assert result["created"][0]["created_by"] == "worker"
    assert result["skipped"] == [{"key": "날짜-없는-확인-follow_up", "reason": "missing_time"}]
    suggestions = list_time_suggestions_for_source(source["id"], settings=db_settings)
    registered = [item for item in suggestions if item["candidate"] == "A 방문"]
    assert registered[0]["registered_time_item_id"] == result["created"][0]["id"]

    second = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)
    assert second["created"] == []
    assert second["existing"][0]["time_item_id"] == result["created"][0]["id"]


def test_auto_register_time_suggestions_skips_dismissed_items(db_settings):
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "거절된 일정 후보",
            "body_markdown": """
# 거절된 일정 후보

### 일정 제안

| 후보 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A 방문 | event | 2026-07-01T10:00:00+09:00 |  |  | 2026-07-01T09:30:00+09:00 | Asia/Seoul | 방문 약속 | |
""",
        },
        db_settings,
    )
    dismiss_source_suggestion(
        source["id"],
        kind="time",
        suggestion_key="a-방문-event-2026-07-01t10-00-00-09-00-2026-07-01t09-30-00-09-00",
        candidate="A 방문",
        settings=db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["created"] == []
    assert result["skipped"] == [
        {
            "key": "a-방문-event-2026-07-01t10-00-00-09-00-2026-07-01t09-30-00-09-00",
            "reason": "dismissed",
        }
    ]


def test_auto_register_time_suggestions_skips_completed_reservation_records(db_settings):
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "예약 완료 기록",
            "body_markdown": """
# 예약 완료 기록

### 일정 제안

| 후보 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 병원 예약 완료 | reminder | 2026-06-11T12:00:00+09:00 | | | | Asia/Seoul | 예약 완료 | 완료 날짜만 있고 실제 예약 시각은 없다. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["created"] == []
    assert result["failed"] == []
    assert result["skipped"] == [
        {
            "key": "병원-예약-완료-reminder-2026-06-11t12-00-00-09-00",
            "reason": "record_only",
        }
    ]
    assert list_time_items(note_id=source["id"], include_closed=True, settings=db_settings) == []


def test_auto_register_time_suggestions_skips_generic_completed_records(db_settings):
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "완료 기록 묶음",
            "body_markdown": """
# 완료 기록 묶음

### 일정 제안

| 후보 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 치약 구매 완료 | reminder | 2026-06-07T15:30:00+09:00 | | | | Asia/Seoul | "구매 완료함" | 완료된 구매 기록이며 알림 필요 없음. |
| 병원 검사 완료 | reminder | 2026-06-08T09:00:00+09:00 | | | | Asia/Seoul | "검사 완료" | 완료 사실만 있고 후속 확인 필요 없음. |
| 택배 수령 완료 | reminder | 2026-06-09T18:00:00+09:00 | | | | Asia/Seoul | "수령 완료" | 등록할 일정이 아니다. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["created"] == []
    assert result["failed"] == []
    assert [item["reason"] for item in result["skipped"]] == ["record_only", "record_only", "record_only"]
    suggestions = list_time_suggestions_for_source(source["id"], settings=db_settings)
    assert all(item["registerable"] is False for item in suggestions)
    assert list_time_items(note_id=source["id"], include_closed=True, settings=db_settings) == []


def test_auto_register_time_suggestions_allows_purchase_needed_task(db_settings):
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "구매 필요 할 일",
            "body_markdown": """
# 구매 필요 할 일

### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 치약 구매 | 할 일 | task | | | 2026-06-10 | | Asia/Seoul | "치약이 떨어져서 사야 함" | 아직 완료되지 않은 구매 필요 항목이다. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["skipped"] == []
    assert result["failed"] == []
    assert len(result["created"]) == 1
    assert result["created"][0]["kind"] == "task"
    assert result["created"][0]["title"] == "치약 구매"


def test_auto_register_time_suggestions_uses_personal_default_channels(db_settings):
    settings = replace(
        db_settings,
        pwa_vapid_public_key="public-key",
        pwa_vapid_private_key="private-key",
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
    )
    update_personalization_settings(
        {"default_notification_channels": ["telegram", "pwa"]},
        settings,
    )
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "개인 기본 알림 채널",
            "body_markdown": """
# 개인 기본 알림 채널

### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 병원 방문 | 일정 | event | 2026-06-20T10:00:00+09:00 | | | 2026-06-20T09:30:00+09:00 | Asia/Seoul | "병원 방문 예정" | 실제 미래 방문 일정이다. |
""",
        },
        settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=settings)

    assert result["failed"] == []
    assert result["skipped"] == []
    assert len(result["created"]) == 1
    assert result["created"][0]["notification_channels"] == ["telegram", "pwa"]


def test_auto_register_time_suggestions_applies_personal_default_reminder(db_settings):
    update_personalization_settings(
        {"default_reminder_minutes": 30},
        db_settings,
    )
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "개인 기본 미리 알림",
            "body_markdown": """
# 개인 기본 미리 알림

### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 병원 방문 | 일정 | event | 2026-06-20T10:00:00+09:00 | | | | Asia/Seoul | "병원 방문 예정" | 실제 미래 방문 일정이다. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["failed"] == []
    assert result["skipped"] == []
    assert len(result["created"]) == 1
    seoul = ZoneInfo("Asia/Seoul")
    assert result["created"][0]["remind_at"].astimezone(seoul).isoformat().startswith(
        "2026-06-20T09:30:00+09:00"
    )
    assert result["created"][0]["metadata"]["default_reminder_minutes"] == 30


def test_auto_register_time_suggestions_preserves_explicit_reminder(db_settings):
    update_personalization_settings(
        {"default_reminder_minutes": 30},
        db_settings,
    )
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "명시 알림 보존",
            "body_markdown": """
# 명시 알림 보존

### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 병원 방문 | 일정 | event | 2026-06-20T10:00:00+09:00 | | | 2026-06-20T08:00:00+09:00 | Asia/Seoul | "병원 방문 예정" | 실제 미래 방문 일정이다. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["failed"] == []
    assert len(result["created"]) == 1
    seoul = ZoneInfo("Asia/Seoul")
    assert result["created"][0]["remind_at"].astimezone(seoul).isoformat().startswith(
        "2026-06-20T08:00:00+09:00"
    )
    assert result["created"][0]["metadata"]["default_reminder_minutes"] == 0


def test_create_time_item_from_suggestion_rejects_completed_reservation_records(db_settings):
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "수동 승인 예약 완료 기록",
            "body_markdown": """
# 수동 승인 예약 완료 기록

### 일정 제안

| 후보 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 병원 예약 완료 | event | 2026-06-11T12:00:00+09:00 | | | | Asia/Seoul | 예약 완료 | 완료 날짜만 있고 실제 예약 시각은 없다. |
""",
        },
        db_settings,
    )
    suggestion = list_time_suggestions_for_source(source["id"], settings=db_settings)[0]

    with pytest.raises(ValueError, match="record-only time suggestion"):
        create_time_item_from_suggestion(
            source["id"],
            suggestion_key=suggestion["key"],
            settings=db_settings,
        )


def test_auto_register_time_suggestions_skips_explicit_record_only_intent(db_settings):
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "기록 전용 시간 후보",
            "body_markdown": """
# 기록 전용 시간 후보

### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 운동 기록 | 기록 전용 | reminder | 2026-06-11T20:00:00+09:00 | | | | Asia/Seoul | "운동했다" | 사용자 기록일 뿐 후속 동작은 없다. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)
    suggestions = list_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["created"] == []
    assert result["failed"] == []
    assert result["skipped"] == [
        {
            "key": "운동-기록-reminder-2026-06-11t20-00-00-09-00",
            "reason": "record_only",
        }
    ]
    assert suggestions[0]["time_intent"] == "record"
    assert suggestions[0]["registerable"] is False
    assert list_time_items(note_id=source["id"], include_closed=True, settings=db_settings) == []


def test_auto_register_time_suggestions_allows_completed_booking_with_future_appointment(db_settings):
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "예약된 진료 일정",
            "body_markdown": """
# 예약된 진료 일정

### 일정 제안

| 후보 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 병원 진료 예약 | event | 2026-06-20T10:00:00+09:00 | | | | Asia/Seoul | 예약 완료, 진료일 2026-06-20 10:00 | 예약 완료 기록이지만 실제 진료일이 명시되어 방문 예정 일정이다. 별도 알림 필요 없음. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["skipped"] == []
    assert result["failed"] == []
    assert len(result["created"]) == 1
    assert result["created"][0]["title"] == "병원 진료 예약"
    assert result["created"][0]["metadata"]["time_intent"] == "event"


def test_auto_register_time_suggestions_disables_notifications_when_source_says_no_reminder(db_settings):
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "알림 없는 예약 일정",
            "body_markdown": """
# 알림 없는 예약 일정

### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 병원 진료 예약 | 일정 | event | 2026-06-20T10:00:00+09:00 | | | | Asia/Seoul | 예약 완료, 진료일 2026-06-20 10:00 | 실제 미래 진료 일정이지만 별도 알림 필요 없음. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["skipped"] == []
    assert result["failed"] == []
    assert len(result["created"]) == 1
    created = result["created"][0]
    assert created["kind"] == "event"
    assert created["notification_channels"] == []
    assert created["remind_at"] is None
    assert created["metadata"]["notifications_disabled"] is True
    assert created["metadata"]["notification_policy"] == "source_says_no_reminder"


def test_auto_register_time_suggestions_skips_negated_follow_up_intent(db_settings):
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "후속 확인 불필요 기록",
            "body_markdown": """
# 후속 확인 불필요 기록

### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 자료 재확인 | 후속 확인 | follow_up | | | 2026-06-20 | | Asia/Seoul | "자료를 보관함" | 후속 확인 필요 없음. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)
    suggestions = list_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["created"] == []
    assert result["failed"] == []
    assert result["skipped"] == [{"key": "자료-재확인-follow_up-2026-06-20", "reason": "record_only"}]
    assert suggestions[0]["registerable"] is False


def test_auto_register_time_suggestions_uses_personal_record_only_terms(db_settings):
    update_personalization_settings({"record_only_terms": ["수납 완료"]}, db_settings)
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "수납 완료 기록",
            "body_markdown": """
# 수납 완료 기록

### 일정 제안

| 후보 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 도서관 수납 완료 | reminder | 2026-06-12T12:00:00+09:00 | | | | Asia/Seoul | "수납 완료" | 완료 기록만 있고 후속 일정은 없다. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)
    suggestions = list_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["created"] == []
    assert result["failed"] == []
    assert result["skipped"] == [
        {
            "key": "도서관-수납-완료-reminder-2026-06-12t12-00-00-09-00",
            "reason": "record_only",
        }
    ]
    assert suggestions[0]["registerable"] is False
    assert list_time_items(note_id=source["id"], include_closed=True, settings=db_settings) == []


def test_personal_record_only_terms_match_spacing_variants(db_settings):
    update_personalization_settings({"record_only_terms": ["수납 완료"]}, db_settings)
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "수납완료 기록",
            "body_markdown": """
# 수납완료 기록

### 일정 제안

| 후보 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 도서관 수납완료 | reminder | 2026-06-12T12:00:00+09:00 | | | | Asia/Seoul | "수납완료" | 완료 기록만 있고 후속 일정은 없다. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)
    suggestions = list_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["created"] == []
    assert result["failed"] == []
    assert [item["reason"] for item in result["skipped"]] == ["record_only"]
    assert suggestions[0]["registerable"] is False
    assert list_time_items(note_id=source["id"], include_closed=True, settings=db_settings) == []


def test_personal_record_only_terms_do_not_hide_future_actions(db_settings):
    update_personalization_settings({"record_only_terms": ["수납 완료"]}, db_settings)
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "수납 완료 후 방문 예정",
            "body_markdown": """
# 수납 완료 후 방문 예정

### 일정 제안

| 후보 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 도서관 방문 | event | 2026-07-01T10:00:00+09:00 | | | | Asia/Seoul | "수납 완료, 방문 예정일 2026-07-01 10:00" | 완료 기록과 별도로 미래 방문 일정이 있다. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["skipped"] == []
    assert result["failed"] == []
    assert len(result["created"]) == 1
    assert result["created"][0]["title"] == "도서관 방문"


def test_personal_record_only_terms_do_not_hide_explicit_task_intent(db_settings):
    update_personalization_settings({"record_only_terms": ["수납 완료"]}, db_settings)
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "수납 완료 후 제출",
            "body_markdown": """
# 수납 완료 후 제출

### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 자료 제출 | 할 일 | task | | | 2026-06-20 | | Asia/Seoul | "수납 완료 후 자료 제출" | 완료 기록과 별도로 제출 대상이다. |
""",
        },
        db_settings,
    )

    result = auto_register_time_suggestions_for_source(source["id"], settings=db_settings)
    suggestions = list_time_suggestions_for_source(source["id"], settings=db_settings)

    assert result["skipped"] == []
    assert result["failed"] == []
    assert len(result["created"]) == 1
    assert result["created"][0]["kind"] == "task"
    assert result["created"][0]["title"] == "자료 제출"
    assert suggestions[0]["time_intent"] == "task"
    assert suggestions[0]["registerable"] is True
