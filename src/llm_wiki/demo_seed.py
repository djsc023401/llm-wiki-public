from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import Settings, load_settings
from .notifications import sync_time_item_notification_deliveries
from .notes_store import (
    create_note,
    dismiss_source_suggestion,
    get_note,
    list_source_suggestions,
    list_suggestion_decisions,
    promote_source_suggestion,
    update_note,
)
from .time_store import create_time_item, get_time_item, list_time_suggestions_for_source, update_time_item


DEMO_SEED_VERSION = 1
DEMO_CREATED_BY = "demo-seed"
DEMO_ORIGINAL_NOTE_ID = "note_demo_public_original"
DEMO_SOURCE_NOTE_ID = "note_demo_public_source"
DEMO_TIME_ITEM_ID = "time_demo_publication_review"
DEMO_TIMEZONE = "Asia/Seoul"


def create_demo_seed(
    settings: Settings | None = None,
    *,
    anchor_date: date | None = None,
    with_notifications: bool = False,
) -> dict:
    """Create a small public-safe demo dataset.

    The seed is intentionally synthetic. It creates enough data for a new
    installation to show the note, source, suggestion, topic/entity, and schedule
    flows without depending on private notes or external services.
    """

    resolved = settings or load_settings()
    anchor = anchor_date or _existing_anchor_date(resolved) or date.today()
    original = _upsert_note(_original_note_payload(anchor), resolved)
    source = _upsert_note(_source_note_payload(anchor, original["row"]), resolved)

    topic_promotion = promote_source_suggestion(
        source["row"]["id"],
        kind="topic",
        candidate="공개 배포 준비",
        suggested_path="wiki/topics/demo-publication-readiness.md",
        settings=resolved,
    )
    entity_promotion = promote_source_suggestion(
        source["row"]["id"],
        kind="entity",
        candidate="샘플 워크벤치",
        suggested_path="wiki/entities/demo-workbench.md",
        settings=resolved,
    )
    source_row = entity_promotion["source_note"]

    dismissed = _dismiss_demo_tag(source_row["id"], resolved)
    time_item, notification_sync = _upsert_demo_time_item(
        source_row["id"],
        anchor,
        with_notifications=with_notifications,
        settings=resolved,
    )

    source_suggestions = list_source_suggestions(source_row["id"], resolved)
    time_suggestions = list_time_suggestions_for_source(source_row["id"], settings=resolved)
    decisions = list_suggestion_decisions([source_row["id"]], resolved)

    return {
        "seed": "public-demo",
        "version": DEMO_SEED_VERSION,
        "anchor_date": anchor.isoformat(),
        "with_notifications": with_notifications,
        "notes": {
            "original": {"id": original["row"]["id"], "action": original["action"]},
            "source": {"id": source_row["id"], "action": source["action"]},
            "topic": {"id": topic_promotion["note"]["id"], "created": topic_promotion["created_note"]},
            "entity": {"id": entity_promotion["note"]["id"], "created": entity_promotion["created_note"]},
        },
        "time_item": {"id": time_item["id"], "status": time_item["status"], "kind": time_item["kind"]},
        "notification_sync": notification_sync,
        "suggestions": {
            "topics": len(source_suggestions["topics"]),
            "entities": len(source_suggestions["entities"]),
            "tags": len(source_suggestions["tags"]),
            "time": len(time_suggestions),
            "dismissed": len(decisions),
            "dismissed_tag_id": dismissed["id"],
        },
    }


def _existing_anchor_date(settings: Settings) -> date | None:
    for note_id in (DEMO_SOURCE_NOTE_ID, DEMO_ORIGINAL_NOTE_ID):
        row = get_note(note_id, settings)
        metadata = row.get("metadata") if row and isinstance(row.get("metadata"), Mapping) else {}
        raw = str(metadata.get("demo_seed_anchor_date") or "").strip()
        if not raw:
            continue
        try:
            return date.fromisoformat(raw)
        except ValueError:
            continue
    return None


def _upsert_note(payload: Mapping[str, object], settings: Settings) -> dict:
    note_id = str(payload["id"])
    existing = get_note(note_id, settings)
    if not existing:
        return {"action": "created", "row": create_note(payload, settings)}
    if existing.get("deleted_at") is not None:
        raise ValueError(f"demo seed note was deleted and cannot be reused: {note_id}")

    expected_marker = _demo_marker(payload.get("metadata"))
    existing_marker = _demo_marker(existing.get("metadata"))
    if expected_marker and expected_marker == existing_marker:
        return {"action": "existing", "row": existing}

    updated = update_note(
        note_id,
        expected_version=int(existing["version"]),
        title=str(payload["title"]),
        body_markdown=str(payload.get("body_markdown") or ""),
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {},
        kind=str(payload["kind"]),
        status=str(payload["status"]),
        slug=str(payload.get("slug") or ""),
        source_note_id=str(payload.get("source_note_id") or "") or None,
        change_source="operator",
        created_by=DEMO_CREATED_BY,
        settings=settings,
    )
    if not updated:
        raise ValueError(f"demo seed note changed during upsert: {note_id}")
    return {"action": "updated", "row": updated}


def _demo_marker(metadata: object) -> tuple[int, str] | None:
    if not isinstance(metadata, Mapping):
        return None
    if metadata.get("demo_seed") is not True:
        return None
    try:
        version = int(metadata.get("demo_seed_version") or 0)
    except (TypeError, ValueError):
        return None
    anchor = str(metadata.get("demo_seed_anchor_date") or "").strip()
    return (version, anchor) if version and anchor else None


def _original_note_payload(anchor: date) -> dict:
    launch = anchor + timedelta(days=21)
    review_due = launch - timedelta(days=7)
    body = (
        "공개 배포 준비 회의 메모.\n"
        f"- 샘플 워크벤치 설치 후 첫 화면에서 노트, 제안, 일정 흐름을 확인할 수 있어야 한다.\n"
        f"- 공개 발행 점검은 {review_due.isoformat()}까지 마친다.\n"
        "- 실제 개인 메모, 내부 주소, 토큰, 운영 식별자는 샘플 데이터에 넣지 않는다.\n"
        "- 설치 문서는 처음 실행하는 사람이 따라 할 수 있게 짧은 확인 절차를 포함한다.\n"
    )
    return {
        "id": DEMO_ORIGINAL_NOTE_ID,
        "kind": "archive",
        "status": "archived",
        "title": "데모 원문 - 공개 배포 준비 회의",
        "slug": "demo-original-publication-planning",
        "body_markdown": body,
        "metadata": _base_demo_metadata(anchor)
        | {
            "original_path": "demo/publication-planning.md",
            "original_title": "공개 배포 준비 회의",
        },
        "change_source": "operator",
        "created_by": DEMO_CREATED_BY,
    }


def _source_note_payload(anchor: date, original_note: Mapping[str, object]) -> dict:
    launch = anchor + timedelta(days=21)
    review_due = launch - timedelta(days=7)
    review_start = datetime.combine(review_due, time(10, 0), tzinfo=ZoneInfo(DEMO_TIMEZONE))
    review_deadline = datetime.combine(review_due, time(18, 0), tzinfo=ZoneInfo(DEMO_TIMEZONE))
    reminder = review_deadline - timedelta(hours=2)
    body = f"""# 공개 배포 준비 회의 정리

## 읽기용 정리

공개 배포를 준비하는 샘플 회의 메모입니다. 첫 설치자가 빈 화면만 보지 않도록 합성 데이터로 노트, 제안, 일정 흐름을 확인하게 하고, 공개 snapshot에는 실제 개인 메모나 운영 식별자가 들어가지 않아야 한다는 점을 정리합니다.

## 요약

샘플 워크벤치에서 노트 작성, AI 분석 결과 확인, 제안 승인과 거절, 일정 등록 흐름을 확인할 수 있어야 합니다. 공개 발행 점검은 {review_due.isoformat()}까지 마치는 것으로 정리했습니다.

## 추출된 사실

| 사실 | 근거 | 검토 메모 |
| --- | --- | --- |
| 첫 설치자는 샘플 워크벤치에서 노트와 제안 흐름을 확인해야 한다. | 샘플 워크벤치 설치 후 첫 화면에서 노트, 제안, 일정 흐름을 확인할 수 있어야 한다. | 공개 demo seed의 목적입니다. |
| 공개 발행 점검 마감일은 {review_due.isoformat()}입니다. | 공개 발행 점검은 {review_due.isoformat()}까지 마친다. | 기준일 {anchor.isoformat()}에서 계산한 합성 일정입니다. |
| 실제 개인 메모와 운영 식별자는 샘플 데이터에 넣지 않습니다. | 실제 개인 메모, 내부 주소, 토큰, 운영 식별자는 샘플 데이터에 넣지 않는다. | 공개 저장소 검증 기준입니다. |

## 원본 메모

{str(original_note.get("body_markdown") or "").strip()}

## 소스 메타데이터

| 항목 | 값 |
| --- | --- |
| 현재 원문 제목 | {original_note.get("title") or "데모 원문"} |
| 현재 원문 파일 | demo/publication-planning.md |
| 원문 노트 ID | {original_note["id"]} |
| 기준일 | {anchor.isoformat()} |
| 샘플 발행 예정일 | {launch.isoformat()} |

## 관련

### 주제 제안

| 후보 | 제안 경로 | 근거 | 검토 메모 |
| --- | --- | --- | --- |
| 공개 배포 준비 | wiki/topics/demo-publication-readiness.md | 공개 발행 전 설치와 seed 확인이 필요하다. | 공개 snapshot 준비 흐름을 묶는 주제입니다. |
| 문서 점검 | wiki/topics/demo-document-review.md | 설치 문서는 처음 실행하는 사람이 따라 할 수 있어야 한다. | 미검토 제안 예시로 남겨 둡니다. |

### 대상 제안

| 후보 | 유형 | 제안 경로 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- |
| 샘플 워크벤치 | 서비스 | wiki/entities/demo-workbench.md | 샘플 워크벤치 설치 후 첫 화면에서 흐름을 확인한다. | 공개 demo 대상입니다. |
| 공개 체크리스트 | 문서 | wiki/entities/demo-public-checklist.md | 공개 발행 점검과 설치 확인 절차가 필요하다. | 미검토 제안 예시로 남겨 둡니다. |

### 태그 제안

| 후보 | 근거 | 검토 메모 |
| --- | --- | --- |
| 공개데모 | 실제 데이터가 아닌 합성 샘플이다. | 첫 설치 확인용 태그 후보입니다. |
| 검토흐름 | 승인과 거절 상태를 함께 보여줄 필요가 있다. | 거절된 제안 예시로 사용합니다. |

### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 공개 발행 점검 마감 | deadline | deadline | {review_start.isoformat()} |  | {review_deadline.isoformat()} | {reminder.isoformat()} | {DEMO_TIMEZONE} | 공개 발행 점검은 {review_due.isoformat()}까지 마친다. | 데모 일정으로 등록합니다. |
"""
    return {
        "id": DEMO_SOURCE_NOTE_ID,
        "kind": "source",
        "status": "active",
        "title": "공개 배포 준비 회의 정리",
        "slug": "demo-source-publication-planning",
        "body_markdown": body,
        "metadata": _base_demo_metadata(anchor)
        | {
            "source_note_id": original_note["id"],
            "source_version": original_note.get("version"),
            "processor": "demo-seed",
            "manual_tags": ["데모"],
            "original_path": "demo/publication-planning.md",
        },
        "source_note_id": original_note["id"],
        "change_source": "operator",
        "created_by": DEMO_CREATED_BY,
    }


def _base_demo_metadata(anchor: date) -> dict:
    return {
        "demo_seed": True,
        "demo_seed_name": "public-demo",
        "demo_seed_version": DEMO_SEED_VERSION,
        "demo_seed_anchor_date": anchor.isoformat(),
        "sensitivity": "public-demo",
    }


def _dismiss_demo_tag(source_note_id: str, settings: Settings) -> dict:
    return dismiss_source_suggestion(
        source_note_id,
        kind="tag",
        suggestion_key="검토흐름",
        candidate="검토흐름",
        reason="demo seed dismissed suggestion sample",
        created_by=DEMO_CREATED_BY,
        settings=settings,
    )


def _upsert_demo_time_item(
    source_note_id: str,
    anchor: date,
    *,
    with_notifications: bool,
    settings: Settings,
) -> tuple[dict, dict]:
    suggestion = _demo_time_suggestion(source_note_id, settings)
    due_at = _datetime_at(anchor + timedelta(days=14), 18, 0)
    remind_at = due_at - timedelta(hours=2)
    payload = {
        "id": DEMO_TIME_ITEM_ID,
        "note_id": source_note_id,
        "source_note_id": source_note_id,
        "source_suggestion_key": suggestion["key"],
        "kind": "deadline",
        "status": "active",
        "title": "공개 발행 점검 마감",
        "body_markdown": "공개 demo seed가 만든 합성 마감 일정입니다.",
        "due_at": due_at,
        "remind_at": remind_at,
        "timezone": DEMO_TIMEZONE,
        "notification_channels": ["pwa"] if with_notifications else [],
        "metadata": _base_demo_metadata(anchor)
        | {
            "source": "demo_seed",
            "evidence": suggestion.get("evidence") or "",
            "review_note": suggestion.get("review_note") or "",
            "notifications_disabled": not with_notifications,
        },
        "created_by": DEMO_CREATED_BY,
    }
    existing = get_time_item(DEMO_TIME_ITEM_ID, settings)
    if existing:
        row = update_time_item(
            DEMO_TIME_ITEM_ID,
            {
                "kind": payload["kind"],
                "status": payload["status"],
                "title": payload["title"],
                "body_markdown": payload["body_markdown"],
                "due_at": payload["due_at"],
                "remind_at": payload["remind_at"],
                "timezone": payload["timezone"],
                "notification_channels": payload["notification_channels"],
                "metadata": payload["metadata"],
            },
            settings,
        )
        if not row:
            raise ValueError(f"demo seed time item changed during upsert: {DEMO_TIME_ITEM_ID}")
    else:
        row = create_time_item(payload, settings)
    sync = sync_time_item_notification_deliveries(row, settings)
    return row, sync


def _demo_time_suggestion(source_note_id: str, settings: Settings) -> dict:
    suggestions = list_time_suggestions_for_source(source_note_id, settings=settings)
    for suggestion in suggestions:
        if suggestion.get("candidate") == "공개 발행 점검 마감":
            return suggestion
    raise ValueError("demo source note is missing the time suggestion")


def _datetime_at(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(DEMO_TIMEZONE))
