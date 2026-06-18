from __future__ import annotations

import uuid

from llm_wiki.notes_store import (
    add_note_asset,
    add_note_link,
    apply_source_classification_change,
    create_export_job,
    create_feedback_reprocess_note,
    create_note,
    create_note_feedback,
    create_source_reanalysis_note,
    delete_note_with_related_cleanup,
    dismiss_note_feedback,
    get_note,
    get_latest_export_job_for_note,
    get_note_asset,
    get_note_revision,
    get_source_note_for_source,
    list_note_assets,
    list_note_feedback,
    list_exportable_notes,
    list_note_links,
    list_note_revisions,
    list_notes,
    list_source_suggestions,
    promote_source_suggestion,
    process_note_revision_to_source,
    queue_source_readable_reanalysis,
    refresh_promoted_targets_for_source,
    refresh_promoted_target_source_sections,
    update_export_job,
    update_note,
    _preserve_existing_source_classification,
    _source_metadata_with_promoted_links,
)
from llm_wiki.personalization import update_personalization_settings
from llm_wiki.requests_store import content_sha256, create_request


def note_id() -> str:
    return f"note_test_{uuid.uuid4().hex}"


def test_source_metadata_keeps_existing_classification_when_promoted_links_are_resynced():
    metadata = {"source_note_id": "note_capture"}
    existing_metadata = {
        "manual_tags": ["투자"],
        "manual_topics": ["기존 주제"],
        "manual_entities": ["기존 대상"],
    }
    promoted_links = [
        {
            "link_type": "topic_suggestion",
            "to_note_id": "note_topic",
            "target_text": "배당률",
            "title": "배당률",
        },
        {
            "link_type": "entity_suggestion",
            "to_note_id": "note_entity",
            "target_text": "QQQI",
            "title": "QQQI",
        },
    ]

    preserved = _preserve_existing_source_classification(metadata, existing_metadata)
    synced = _source_metadata_with_promoted_links(preserved, promoted_links)

    assert synced["manual_tags"] == ["투자"]
    assert synced["manual_topics"] == ["기존 주제", "배당률"]
    assert synced["manual_entities"] == ["기존 대상", "QQQI"]
    assert synced["approved_topics"] == [{"title": "배당률", "note_id": "note_topic"}]
    assert synced["approved_entities"] == [{"title": "QQQI", "note_id": "note_entity"}]

    resynced = _source_metadata_with_promoted_links(synced, [])
    assert resynced["manual_tags"] == ["투자"]
    assert resynced["manual_topics"] == ["기존 주제"]
    assert resynced["manual_entities"] == ["기존 대상"]
    assert "approved_topics" not in resynced
    assert "approved_entities" not in resynced


def test_note_create_update_revisions_and_stale_version(db_settings):
    created = create_note(
        {
            "id": note_id(),
            "kind": "inbox",
            "status": "draft",
            "title": "2026 Web Transition",
            "body_markdown": "Initial note",
            "metadata": {"source": "pytest"},
            "change_source": "test",
            "created_by": "pytest",
        },
        db_settings,
    )

    assert created["version"] == 1
    assert created["slug"] == "2026-web-transition"
    assert get_note(created["id"], db_settings)["metadata"]["source"] == "pytest"
    assert list_note_revisions(created["id"], settings=db_settings)[0]["version"] == 1

    updated = update_note(
        created["id"],
        expected_version=1,
        title="2026 Web Transition Updated",
        body_markdown="Updated note",
        metadata={"source": "pytest", "state": "updated"},
        status="active",
        change_source="test",
        created_by="pytest",
        settings=db_settings,
    )

    assert updated["version"] == 2
    assert updated["status"] == "active"
    assert updated["metadata"]["state"] == "updated"
    assert update_note(
        created["id"],
        expected_version=1,
        body_markdown="stale write",
        change_source="test",
        settings=db_settings,
    ) is None
    revisions = list_note_revisions(created["id"], settings=db_settings)
    assert [row["version"] for row in revisions] == [2, 1]
    assert revisions[0]["body_markdown"] == "Updated note"


def test_note_list_filters_and_slug_collision_resolution(db_settings):
    first = create_note({"id": note_id(), "kind": "inbox", "title": "새로운 메모", "body_markdown": "alpha"}, db_settings)
    second = create_note({"id": note_id(), "kind": "inbox", "title": "새로운 메모", "body_markdown": "beta"}, db_settings)
    internal = create_note(
        {
            "id": note_id(),
            "kind": "inbox",
            "title": "AI 재분석 - 내부 노트",
            "body_markdown": "beta internal",
            "metadata": {"source_reanalysis": True},
        },
        db_settings,
    )
    create_note({"id": note_id(), "kind": "topic", "title": "새로운 메모", "body_markdown": "topic"}, db_settings)

    assert first["slug"] == "새로운-메모"
    assert second["slug"] == "새로운-메모-2"

    rows = list_notes(kind="inbox", query="beta", settings=db_settings)

    assert [row["id"] for row in rows] == [second["id"]]
    assert internal["id"] not in [row["id"] for row in list_notes(kind="inbox", settings=db_settings)]
    assert internal["id"] in [row["id"] for row in list_notes(kind="inbox", include_internal=True, settings=db_settings)]


def test_note_feedback_create_list_and_reprocess_note(db_settings):
    source = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "A 방문 일정",
            "body_markdown": "# A 방문 일정\n\nA가 2026년 6월 6일 놀러오기로 했다.",
            "metadata": {"channel": "web"},
        },
        db_settings,
    )

    feedback = create_note_feedback(
        source["id"],
        {
            "expected_version": source["version"],
            "feedback_type": "change",
            "body_markdown": "A가 2026년 7월 1일에 놀러오기로 변경함",
            "created_by": "pytest",
        },
        db_settings,
    )

    rows = list_note_feedback(source["id"], include_closed=True, settings=db_settings)
    assert rows[0]["id"] == feedback["id"]
    assert rows[0]["feedback_type"] == "change"
    assert rows[0]["status"] == "open"

    dismissed_source = create_note_feedback(
        source["id"],
        {
            "expected_version": source["version"],
            "feedback_type": "low_priority",
            "body_markdown": "이 피드백은 재처리하지 않음",
            "created_by": "pytest",
        },
        db_settings,
    )
    dismissed = dismiss_note_feedback(source["id"], dismissed_source["id"], db_settings)
    assert dismissed["status"] == "dismissed"
    assert dismissed["resolved_at"] is not None
    open_rows = list_note_feedback(source["id"], settings=db_settings)
    assert [row["id"] for row in open_rows] == [feedback["id"]]
    all_rows = list_note_feedback(source["id"], include_closed=True, settings=db_settings)
    assert {row["id"] for row in all_rows} == {feedback["id"], dismissed_source["id"]}

    reprocess = create_feedback_reprocess_note(source["id"], settings=db_settings)

    assert reprocess["note"]["kind"] == "inbox"
    assert reprocess["note"]["metadata"]["feedback_reprocess"] is True
    assert reprocess["note"]["metadata"]["feedback_target_note_id"] == source["id"]
    assert reprocess["note"]["metadata"]["feedback_ids"] == [feedback["id"]]
    assert "A가 2026년 7월 1일에 놀러오기로 변경함" in reprocess["revision"]["body_markdown"]
    assert reprocess["revision"]["version"] == 1


def test_source_reanalysis_note_captures_target_source(db_settings):
    update_personalization_settings(
        {
            "timezone": "UTC",
            "default_schedule_days": 45,
            "daily_digest_time": "07:30",
            "default_notification_channels": ["telegram"],
            "personal_terms": ["예약 완료"],
            "classification_seeds": ["개인 일정"],
            "record_only_terms": ["예약 완료"],
            "follow_up_terms": ["확인 필요"],
            "frequent_people": ["A"],
            "frequent_places": ["강릉"],
            "active_projects": ["llm-wiki"],
            "life_categories": ["건강"],
            "metadata": {"admin_token": "admin-secret", "telegram_token": "telegram-secret"},
        },
        db_settings,
    )
    original = create_note(
        {
            "id": note_id(),
            "kind": "archive",
            "status": "archived",
            "title": "원본",
            "body_markdown": "원본 메모",
        },
        db_settings,
    )
    source = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "기존 분석",
            "body_markdown": "# 기존 분석\n\n오늘이라고만 적힌 분석",
            "source_note_id": original["id"],
        },
        db_settings,
    )
    feedback = create_note_feedback(
        source["id"],
        {
            "expected_version": source["version"],
            "feedback_type": "correction",
            "body_markdown": "원문 기준으로 날짜를 다시 확인해야 함",
            "created_by": "pytest",
        },
        db_settings,
    )
    dismissed_feedback = create_note_feedback(
        source["id"],
        {
            "expected_version": source["version"],
            "feedback_type": "low_priority",
            "body_markdown": "재분석에서 제외할 피드백",
            "created_by": "pytest",
        },
        db_settings,
    )
    dismiss_note_feedback(source["id"], dismissed_feedback["id"], db_settings)

    reanalysis = create_source_reanalysis_note(
        source["id"],
        expected_version=source["version"],
        created_by="pytest",
        settings=db_settings,
    )

    temp_note = reanalysis["note"]
    revision = reanalysis["revision"]
    assert temp_note["kind"] == "inbox"
    assert temp_note["source_note_id"] == original["id"]
    assert temp_note["parent_id"] == source["id"]
    assert temp_note["metadata"]["source_reanalysis"] is True
    assert temp_note["metadata"]["reanalysis_target_note_id"] == source["id"]
    assert temp_note["metadata"]["reanalysis_target_note_version"] == source["version"]
    assert temp_note["metadata"]["reanalysis_original_note_id"] == original["id"]
    assert temp_note["metadata"]["reanalysis_feedback_ids"] == [feedback["id"]]
    assert "## 재분석 지시" in temp_note["body_markdown"]
    assert "더 나은 읽기용 정리, 요약" in temp_note["body_markdown"]
    assert "## 개인화 참고" in temp_note["body_markdown"]
    assert "원문 근거나 사실 데이터가 아니라 해석과 분류를 돕는 힌트" in temp_note["body_markdown"]
    assert "추출된 사실/근거 셀에 인용하지 마세요" in temp_note["body_markdown"]
    assert "UTC" in temp_note["body_markdown"]
    assert "45일" in temp_note["body_markdown"]
    assert "예약 완료" in temp_note["body_markdown"]
    assert "개인 일정" in temp_note["body_markdown"]
    assert "기록 전용 용어" in temp_note["body_markdown"]
    assert "후속 확인 용어" in temp_note["body_markdown"]
    assert "확인 필요" in temp_note["body_markdown"]
    assert "강릉" in temp_note["body_markdown"]
    assert "llm-wiki" in temp_note["body_markdown"]
    assert "admin-secret" not in temp_note["body_markdown"]
    assert "telegram-secret" not in temp_note["body_markdown"]
    assert "## 원문" in temp_note["body_markdown"]
    assert "원본 메모" in temp_note["body_markdown"]
    assert "## 현재 소스 노트" in temp_note["body_markdown"]
    assert "오늘이라고만 적힌 분석" in temp_note["body_markdown"]
    assert "## 사용자 피드백" in temp_note["body_markdown"]
    assert "원문 기준으로 날짜를 다시 확인해야 함" in temp_note["body_markdown"]
    assert "재분석에서 제외할 피드백" not in temp_note["body_markdown"]
    personalization_index = temp_note["body_markdown"].index("## 개인화 참고")
    original_index = temp_note["body_markdown"].index("## 원문")
    current_source_index = temp_note["body_markdown"].index("## 현재 소스 노트")
    feedback_index = temp_note["body_markdown"].index("## 사용자 피드백")
    assert personalization_index < original_index < current_source_index < feedback_index
    original_and_feedback = temp_note["body_markdown"][original_index:]
    assert "기록 전용 용어" not in original_and_feedback
    assert "후속 확인 용어" not in original_and_feedback
    assert revision["note_id"] == temp_note["id"]
    assert revision["created_by"] == "pytest"


def test_note_links_and_assets(db_settings):
    source = create_note({"id": note_id(), "kind": "source", "title": "Source Note"}, db_settings)
    topic = create_note({"id": note_id(), "kind": "topic", "title": "Topic Note"}, db_settings)

    link = add_note_link(
        source["id"],
        to_note_id=topic["id"],
        target_text="Topic Note",
        link_type="topic_suggestion",
        settings=db_settings,
    )
    asset = add_note_asset(
        source["id"],
        object_key="assets/test/file.txt",
        file_name="file.txt",
        content_type="text/plain",
        sha256="abc123",
        size_bytes=12,
        settings=db_settings,
    )

    assert list_note_links(source["id"], db_settings)[0]["id"] == link["id"]
    assert list_note_assets(source["id"], db_settings)[0]["id"] == asset["id"]
    assert get_note_asset(source["id"], asset["id"], db_settings)["object_key"] == "assets/test/file.txt"
    assert get_note_asset(topic["id"], asset["id"], db_settings) is None


def test_promote_source_suggestions_creates_or_links_notes(db_settings):
    source = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "Source Note",
            "body_markdown": "\n".join(
                [
                    "# Source Note",
                    "",
                    "## 관련",
                    "",
                    "### 주제 제안",
                    "",
                    "| 후보 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- |",
                    "| Knowledge Ops | `wiki/topics/knowledge-ops.md` | Source mentions review cadence. | Review before creating topic page. |",
                    "| 없음 |  |  | No supported topic suggestion. |",
                    "",
                    "### 대상 제안",
                    "",
                    "| 후보 | 유형 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- | --- |",
                    "| llm-wiki | project | `wiki/entities/llm-wiki.md` | Source names the project. | Link to project page. |",
                    "",
                    "### 태그 제안",
                    "",
                    "| 후보 | 근거 | 검토 메모 |",
                    "| --- | --- | --- |",
                    "| 운영 | Source discusses review cadence. | Apply as a lightweight label. |",
                    "| 연구 | Source discusses review cadence. | Already applied by the user. |",
                ]
            ),
            "metadata": {"manual_tags": ["연구"]},
        },
        db_settings,
    )
    existing_entity = create_note(
        {
            "id": note_id(),
            "kind": "entity",
            "status": "active",
            "title": "llm-wiki",
            "slug": "llm-wiki",
            "body_markdown": "Existing project page",
        },
        db_settings,
    )

    suggestions = list_source_suggestions(source["id"], db_settings)
    assert suggestions["topics"][0]["candidate"] == "Knowledge Ops"
    assert suggestions["topics"][0]["slug"] == "knowledge-ops"
    assert suggestions["entities"][0]["existing_note_id"] == existing_entity["id"]
    assert suggestions["tags"][0]["candidate"] == "운영"
    assert suggestions["tags"][0]["applied"] is False
    assert suggestions["tags"][1]["candidate"] == "연구"
    assert suggestions["tags"][1]["applied"] is True

    promoted_topic = promote_source_suggestion(
        source["id"],
        kind="topic",
        candidate="Knowledge Ops",
        suggested_path="wiki/topics/knowledge-ops.md",
        expected_version=source["version"],
        settings=db_settings,
    )
    assert promoted_topic["created_note"] is True
    assert promoted_topic["note"]["kind"] == "topic"
    assert promoted_topic["note"]["slug"] == "knowledge-ops"
    assert promoted_topic["note"]["source_note_id"] == source["id"]
    assert promoted_topic["note"]["metadata"]["promotion_status"] == "approved"
    assert "## 종합 정리" in promoted_topic["note"]["body_markdown"]
    assert "## 요약" in promoted_topic["note"]["body_markdown"]
    assert "## 근거" in promoted_topic["note"]["body_markdown"]
    assert "## 연결된 소스 요약" in promoted_topic["note"]["body_markdown"]
    assert "## 출처" in promoted_topic["note"]["body_markdown"]
    assert "## 검토 메모" in promoted_topic["note"]["body_markdown"]
    assert "## Summary" not in promoted_topic["note"]["body_markdown"]
    assert promoted_topic["link"]["link_type"] == "topic_suggestion"
    assert promoted_topic["source_note"]["version"] == source["version"] + 1
    assert "## 승인된 연결" in promoted_topic["source_note"]["body_markdown"]
    assert "### 주제" in promoted_topic["source_note"]["body_markdown"]
    assert "- Knowledge Ops" in promoted_topic["source_note"]["body_markdown"]
    assert promoted_topic["source_note"]["metadata"]["approved_topics"][0]["title"] == "Knowledge Ops"
    assert promoted_topic["source_note"]["metadata"]["manual_topics"] == ["Knowledge Ops"]

    promoted_again = promote_source_suggestion(
        source["id"],
        kind="topic",
        candidate="Knowledge Ops",
        suggested_path="wiki/topics/knowledge-ops.md",
        expected_version=promoted_topic["source_note"]["version"],
        settings=db_settings,
    )
    assert promoted_again["created_note"] is False
    assert promoted_again["note"]["id"] == promoted_topic["note"]["id"]
    assert promoted_again["note"]["body_markdown"].count(f"Source Note (`{source['id']}`)") == 1
    assert promoted_again["source_note"]["metadata"]["manual_topics"] == ["Knowledge Ops"]
    assert len(list_note_links(source["id"], db_settings)) == 1

    promoted_entity = promote_source_suggestion(
        source["id"],
        kind="entity",
        candidate="llm-wiki",
        suggested_path="wiki/entities/llm-wiki.md",
        expected_version=promoted_again["source_note"]["version"],
        settings=db_settings,
    )
    assert promoted_entity["created_note"] is False
    assert promoted_entity["note"]["id"] == existing_entity["id"]
    assert promoted_entity["note"]["body_markdown"].startswith("Existing project page")
    assert "## 연결된 소스" in promoted_entity["note"]["body_markdown"]
    assert f"Source Note (`{source['id']}`)" in promoted_entity["note"]["body_markdown"]
    assert promoted_entity["link"]["link_type"] == "entity_suggestion"
    assert "### 대상" in promoted_entity["source_note"]["body_markdown"]
    assert "- llm-wiki" in promoted_entity["source_note"]["body_markdown"]
    assert promoted_entity["source_note"]["metadata"]["approved_entities"][0]["title"] == "llm-wiki"
    assert promoted_entity["source_note"]["metadata"]["manual_entities"] == ["llm-wiki"]


def test_promoted_target_note_body_lists_all_linked_sources(db_settings):
    def source_note(title: str, body: str) -> dict:
        return create_note(
            {
                "id": note_id(),
                "kind": "source",
                "status": "active",
                "title": title,
                "body_markdown": "\n".join(
                    [
                        f"# {title}",
                        "",
                        "## 관련",
                        "",
                        "### 대상 제안",
                        "",
                        "| 후보 | 유형 | 제안 경로 | 근거 | 검토 메모 |",
                        "| --- | --- | --- | --- | --- |",
                        f"| 치약 | 생활용품 | `wiki/entities/치약.md` | {body} | 생활용품 재고로 연결한다. |",
                    ]
                ),
            },
            db_settings,
        )

    first = source_note("치약 구매 필요", "치약이 다 떨어져서 사야돼")
    promoted_first = promote_source_suggestion(
        first["id"],
        kind="entity",
        candidate="치약",
        suggested_path="wiki/entities/치약.md",
        expected_version=first["version"],
        settings=db_settings,
    )
    assert promoted_first["created_note"] is True
    assert "1개의 소스 노트" in promoted_first["note"]["body_markdown"]
    assert "현재 1개의 소스에서 확인된 대상" in promoted_first["note"]["body_markdown"]
    assert f"치약 구매 필요 (`{first['id']}`)" in promoted_first["note"]["body_markdown"]

    second = source_note("집에 남아있는 치약이 없다", "집에 남아있는 치약이 없다")
    promoted_second = promote_source_suggestion(
        second["id"],
        kind="entity",
        candidate="치약",
        suggested_path="wiki/entities/치약.md",
        expected_version=second["version"],
        settings=db_settings,
    )

    body = promoted_second["note"]["body_markdown"]
    assert promoted_second["created_note"] is False
    assert promoted_second["note"]["id"] == promoted_first["note"]["id"]
    assert "2개의 소스 노트" in body
    assert "2개의 소스에서 반복적으로 연결된 대상" in body
    assert "### 공통 맥락" in body
    assert "### 소스별 차이" in body
    assert "### 최근 기준" in body
    assert "치약 구매 필요:" in body
    assert "집에 남아있는 치약이 없다:" in body
    assert "가장 최근 기준 소스" in body
    assert f"치약 구매 필요 (`{first['id']}`)" in body
    assert f"집에 남아있는 치약이 없다 (`{second['id']}`)" in body
    assert len([link for link in list_note_links(first["id"], db_settings) if link["to_note_id"] == promoted_first["note"]["id"]]) == 1
    assert len([link for link in list_note_links(second["id"], db_settings) if link["to_note_id"] == promoted_first["note"]["id"]]) == 1


def test_apply_classification_change_suggestion_updates_tags(db_settings):
    source = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "분류 변경 소스",
            "body_markdown": "\n".join(
                [
                    "# 분류 변경 소스",
                    "",
                    "## 관련",
                    "",
                    "### 분류 변경 제안",
                    "",
                    "| 동작 | 분류 | 현재 값 | 변경 값 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                    "| 교체 | 태그 | 투자 | 지출 |  | 사용자가 소비 기록이라고 정정했다. | 태그를 바꾼다. |",
                ]
            ),
            "metadata": {"manual_tags": ["투자", "건강"]},
        },
        db_settings,
    )

    suggestions = list_source_suggestions(source["id"], db_settings)
    change = suggestions["classification_changes"][0]
    assert change["kind"] == "classification_change"
    assert change["classification_action"] == "replace"
    assert change["classification_kind"] == "tag"
    assert change["applied"] is False

    applied = apply_source_classification_change(
        source["id"],
        suggestion_key=change["key"],
        expected_version=source["version"],
        settings=db_settings,
    )

    assert applied["applied"] is True
    assert applied["source_note"]["metadata"]["manual_tags"] == ["건강", "지출"]
    assert list_source_suggestions(source["id"], db_settings)["classification_changes"][0]["applied"] is True


def test_apply_classification_change_replaces_topic_link_and_deletes_orphan(db_settings):
    source = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "주제 교체 소스",
            "body_markdown": "\n".join(
                [
                    "# 주제 교체 소스",
                    "",
                    "## 승인된 연결",
                    "",
                    "### 주제",
                    "- 기존 주제 (`note_placeholder`)",
                    "",
                    "## 관련",
                    "",
                    "### 분류 변경 제안",
                    "",
                    "| 동작 | 분류 | 현재 값 | 변경 값 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                    "| 교체 | 주제 | 기존 주제 | 새 주제 | `wiki/topics/새-주제.md` | 사용자 피드백이 더 정확한 주제를 제시했다. | 연결을 교체한다. |",
                ]
            ),
            "metadata": {
                "manual_topics": ["기존 주제"],
                "approved_topics": [{"title": "기존 주제", "note_id": "note_placeholder"}],
            },
        },
        db_settings,
    )
    old_topic = create_note(
        {
            "id": note_id(),
            "kind": "topic",
            "status": "active",
            "title": "기존 주제",
            "slug": "기존-주제",
            "body_markdown": "# 기존 주제\n\n## 연결된 소스\n\n- 주제 교체 소스\n",
            "metadata": {"promotion_status": "approved", "created_kind": "topic"},
        },
        db_settings,
    )
    add_note_link(
        source["id"],
        to_note_id=old_topic["id"],
        target_text="기존 주제",
        link_type="topic_suggestion",
        settings=db_settings,
    )
    source = get_note(source["id"], db_settings)
    source = update_note(
        source["id"],
        expected_version=source["version"],
        metadata={
            "manual_topics": ["기존 주제"],
            "approved_topics": [{"title": "기존 주제", "note_id": old_topic["id"]}],
        },
        change_source="test",
        created_by="pytest",
        settings=db_settings,
    )
    change = list_source_suggestions(source["id"], db_settings)["classification_changes"][0]

    applied = apply_source_classification_change(
        source["id"],
        suggestion_key=change["key"],
        expected_version=source["version"],
        settings=db_settings,
    )

    updated_source = applied["source_note"]
    assert applied["note"]["kind"] == "topic"
    assert applied["note"]["title"] == "새 주제"
    assert get_note(old_topic["id"], db_settings)["status"] == "deleted"
    assert updated_source["metadata"]["manual_topics"] == ["새 주제"]
    assert updated_source["metadata"]["approved_topics"] == [{"title": "새 주제", "note_id": applied["note"]["id"]}]
    links = list_note_links(source["id"], db_settings)
    assert [link["to_note_id"] for link in links] == [applied["note"]["id"]]
    assert list_source_suggestions(source["id"], db_settings)["classification_changes"][0]["applied"] is True


def test_refresh_promoted_target_source_sections_updates_existing_generated_notes(db_settings):
    target = create_note(
        {
            "id": note_id(),
            "kind": "entity",
            "status": "active",
            "title": "치약",
            "slug": "치약",
            "body_markdown": "# 치약\n\n## 요약\n\n이 대상 노트는 소스 노트 하나만 표시합니다.\n",
            "metadata": {
                "promotion_status": "approved",
                "created_kind": "entity",
                "suggested_path": "wiki/entities/치약.md",
                "evidence": "치약",
                "review_note": "생활용품 재고로 연결한다.",
            },
        },
        db_settings,
    )
    first = create_note({"id": note_id(), "kind": "source", "status": "active", "title": "치약 구매 필요"}, db_settings)
    second = create_note({"id": note_id(), "kind": "source", "status": "active", "title": "집에 남아있는 치약이 없다"}, db_settings)
    add_note_link(first["id"], target_text="치약 구매 필요", to_note_id=target["id"], link_type="entity_suggestion", settings=db_settings)
    add_note_link(second["id"], target_text="집에 남아있는 치약이 없다", to_note_id=target["id"], link_type="entity_suggestion", settings=db_settings)

    result = refresh_promoted_target_source_sections(db_settings)
    updated = get_note(target["id"], db_settings)

    assert result["refreshed"] == [target["id"]]
    assert "2개의 소스 노트" in updated["body_markdown"]
    assert "2개의 소스에서 반복적으로 연결된 대상" in updated["body_markdown"]
    assert "### 공통 맥락" in updated["body_markdown"]
    assert "### 소스별 차이" in updated["body_markdown"]
    assert "### 최근 기준" in updated["body_markdown"]
    assert f"치약 구매 필요 (`{first['id']}`)" in updated["body_markdown"]
    assert f"집에 남아있는 치약이 없다 (`{second['id']}`)" in updated["body_markdown"]
    assert list_note_revisions(target["id"], settings=db_settings)[0]["created_by"] == "refresh-promoted-sources"


def test_refresh_promoted_targets_for_source_ignores_mismatched_link_type(db_settings):
    source = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "잘못된 링크 소스",
            "body_markdown": "# 잘못된 링크 소스\n\n## 읽기용 정리\n\n링크 타입이 잘못된 소스입니다.",
        },
        db_settings,
    )
    topic = create_note(
        {
            "id": note_id(),
            "kind": "topic",
            "status": "active",
            "title": "링크 타입 확인",
            "slug": "link-type-check",
            "body_markdown": "# 링크 타입 확인\n\n기존 본문입니다.\n",
            "metadata": {"promotion_status": "approved", "created_kind": "topic"},
        },
        db_settings,
    )
    add_note_link(
        source["id"],
        target_text="링크 타입 확인",
        to_note_id=topic["id"],
        link_type="entity_suggestion",
        settings=db_settings,
    )

    result = refresh_promoted_targets_for_source(source["id"], db_settings)
    updated = get_note(topic["id"], db_settings)

    assert result["count"] == 0
    assert result["refreshed"] == []
    assert result["deleted"] == []
    assert updated["status"] == "active"
    assert updated["body_markdown"] == topic["body_markdown"]


def test_queue_source_readable_reanalysis_enqueues_missing_readable_only(db_settings):
    missing = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "기존 소스",
            "body_markdown": "# 기존 소스\n\n## 요약\n\n예전 형식의 소스 노트입니다.",
        },
        db_settings,
    )
    create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "새 형식 소스",
            "body_markdown": "# 새 형식 소스\n\n## 읽기용 정리\n\n이미 변환된 소스입니다.",
        },
        db_settings,
    )

    dry_run = queue_source_readable_reanalysis(db_settings, dry_run=True)

    assert dry_run["matched"] == 1
    assert dry_run["dry_run"] == 1
    assert dry_run["items"][0]["source_note_id"] == missing["id"]

    queued = queue_source_readable_reanalysis(db_settings, created_by="pytest")

    assert queued["matched"] == 1
    assert queued["queued"] == 1
    item = queued["items"][0]
    assert item["source_note_id"] == missing["id"]
    assert item["request"]["source"] == "source-readable-backfill"
    assert item["request"]["input_mode"] == "db-note"
    assert item["request"]["target_note_id"] == missing["id"]
    reanalysis_note = get_note(item["reanalysis_note_id"], db_settings)
    assert reanalysis_note["metadata"]["source_reanalysis"] is True
    assert reanalysis_note["metadata"]["reanalysis_target_note_id"] == missing["id"]

    duplicate = queue_source_readable_reanalysis(db_settings, created_by="pytest")

    assert duplicate["matched"] == 1
    assert duplicate["existing"] == 1
    assert duplicate["items"][0]["request"]["id"] == item["request"]["id"]


def test_source_suggestions_match_approved_link_by_target_note(db_settings):
    topic = create_note(
        {
            "id": note_id(),
            "kind": "topic",
            "status": "active",
            "title": "Dividend yield",
            "slug": "배당률",
            "body_markdown": "Existing topic page",
        },
        db_settings,
    )
    source = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "QQQI 배당률",
            "body_markdown": "\n".join(
                [
                    "# QQQI 배당률",
                    "",
                    "## 관련",
                    "",
                    "### 주제 제안",
                    "",
                    "| 후보 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- |",
                    "| 배당률 | `wiki/topics/배당률.md` | 연 배당율 | 같은 문서의 새 후보명이다. |",
                ]
            ),
        },
        db_settings,
    )
    link = add_note_link(
        source["id"],
        target_text="Dividend yield",
        to_note_id=topic["id"],
        link_type="topic_suggestion",
        settings=db_settings,
    )

    suggestions = list_source_suggestions(source["id"], db_settings)

    assert suggestions["topics"][0]["candidate"] == "배당률"
    assert suggestions["topics"][0]["existing_note_id"] == topic["id"]
    assert suggestions["topics"][0]["promoted_note_id"] == topic["id"]
    assert suggestions["topics"][0]["link_id"] == link["id"]


def test_process_note_revision_to_source_archives_inbox_and_creates_source(db_settings):
    inbox = create_note(
        {
            "id": note_id(),
            "kind": "inbox",
            "status": "active",
            "title": "DB Capture",
            "body_markdown": "First line\nSecond line",
            "metadata": {"channel": "pytest"},
        },
        db_settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=db_settings)
    request = create_request(
        {
            "id": "req_test_note_process",
            "source": "pytest",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )

    result = process_note_revision_to_source(
        request_id=request["id"],
        note_id=inbox["id"],
        source_revision_id=revision["id"],
        settings=db_settings,
    )

    archived = get_note(inbox["id"], db_settings)
    target = result["target_note"]
    assert archived["kind"] == "archive"
    assert archived["status"] == "archived"
    assert archived["title"] == f"원문 - {target['title']}"
    assert archived["metadata"]["target_note_id"] == target["id"]
    assert target["kind"] == "source"
    assert target["status"] == "active"
    assert target["source_note_id"] == inbox["id"]
    assert target["body_markdown"].index("## 읽기용 정리") < target["body_markdown"].index("## 요약")
    assert "사람이 다시 읽기 쉽게 정리한 것입니다" in target["body_markdown"]
    assert "## 원본 메모" in target["body_markdown"]
    assert "First line" in target["body_markdown"]
    assert target["metadata"]["source_revision_id"] == revision["id"]
    assert list_note_revisions(target["id"], settings=db_settings)[0]["request_id"] == request["id"]
    assert list_note_revisions(archived["id"], settings=db_settings)[0]["title"] == archived["title"]
    assert get_source_note_for_source(inbox["id"], settings=db_settings)["id"] == target["id"]


def test_source_reanalysis_preserves_promoted_classification_metadata(db_settings):
    original = create_note(
        {
            "id": note_id(),
            "kind": "archive",
            "status": "archived",
            "title": "원문 - QQQI 메모",
            "body_markdown": "QQQI 배당률 원문",
        },
        db_settings,
    )
    source = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "QQQI 배당률",
            "body_markdown": "# QQQI 배당률\n\n## 요약\n기존 분석",
            "metadata": {"manual_tags": ["투자"]},
            "source_note_id": original["id"],
        },
        db_settings,
    )
    topic = create_note(
        {
            "id": note_id(),
            "kind": "topic",
            "status": "active",
            "title": "배당률",
            "body_markdown": "배당률 주제",
        },
        db_settings,
    )
    entity = create_note(
        {
            "id": note_id(),
            "kind": "entity",
            "status": "active",
            "title": "QQQI",
            "body_markdown": "QQQI 대상",
        },
        db_settings,
    )
    add_note_link(
        source["id"],
        target_text="배당률",
        to_note_id=topic["id"],
        link_type="topic_suggestion",
        settings=db_settings,
    )
    add_note_link(
        source["id"],
        target_text="QQQI",
        to_note_id=entity["id"],
        link_type="entity_suggestion",
        settings=db_settings,
    )
    reanalysis = create_source_reanalysis_note(
        source["id"],
        expected_version=source["version"],
        settings=db_settings,
    )
    revision = reanalysis["revision"]
    request = create_request(
        {
            "id": f"req_{uuid.uuid4().hex}",
            "source": "pytest",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": reanalysis["note"]["id"],
            "source_revision_id": revision["id"],
            "target_note_id": source["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )

    result = process_note_revision_to_source(
        request_id=request["id"],
        note_id=reanalysis["note"]["id"],
        source_revision_id=revision["id"],
        target_note_id=source["id"],
        generated_body_markdown="# QQQI 배당률 재분석\n\n## 요약\n새 분석",
        settings=db_settings,
    )

    updated = result["target_note"]
    assert updated["id"] == source["id"]
    assert updated["metadata"]["manual_tags"] == ["투자"]
    assert updated["metadata"]["manual_topics"] == ["배당률"]
    assert updated["metadata"]["manual_entities"] == ["QQQI"]
    assert updated["metadata"]["approved_topics"] == [{"title": "배당률", "note_id": topic["id"]}]
    assert updated["metadata"]["approved_entities"] == [{"title": "QQQI", "note_id": entity["id"]}]
    assert "## 승인된 연결" in updated["body_markdown"]
    assert f"- 배당률 (`{topic['id']}`)" in updated["body_markdown"]
    assert f"- QQQI (`{entity['id']}`)" in updated["body_markdown"]


def test_delete_source_restores_orphan_original_to_inbox(db_settings):
    inbox = create_note(
        {
            "id": note_id(),
            "kind": "inbox",
            "status": "active",
            "title": "원문 삭제 기본",
            "body_markdown": "소스 삭제 후 다시 작성중으로 볼 원문입니다.",
        },
        db_settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=db_settings)
    request_id = f"req_{uuid.uuid4().hex}"
    create_request(
        {
            "id": request_id,
            "source": "pytest",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )
    result = process_note_revision_to_source(
        request_id=request_id,
        note_id=inbox["id"],
        source_revision_id=revision["id"],
        generated_body_markdown="# 복원 대상 소스\n\n## 요약\n\n원문을 분석했습니다.",
        settings=db_settings,
    )
    source = result["target_note"]
    original = result["source_note"]

    deleted = delete_note_with_related_cleanup(
        source["id"],
        expected_version=source["version"],
        change_source="test",
        created_by="pytest",
        settings=db_settings,
    )

    restored = get_note(original["id"], db_settings)
    assert deleted["status"] == "deleted"
    assert deleted["delete_cleanup"]["restored_original_notes"] == 1
    assert deleted["delete_cleanup"]["deleted_original_notes"] == 0
    assert deleted["delete_cleanup"]["source_original"]["action"] == "restored_to_inbox"
    assert restored["kind"] == "inbox"
    assert restored["status"] == "draft"
    assert restored["deleted_at"] is None
    assert restored["archived_at"] is None
    assert restored["title"] == "복원 대상 소스"
    assert restored["metadata"]["restored_by"] == "source_note_deleted"
    assert restored["metadata"]["restored_source_note_id"] == source["id"]
    assert "target_note_id" not in restored["metadata"]


def test_delete_source_can_delete_orphan_original_when_requested(db_settings):
    original = create_note(
        {
            "id": note_id(),
            "kind": "archive",
            "status": "archived",
            "title": "원문 - 함께 삭제",
            "body_markdown": "같이 삭제할 원문입니다.",
            "metadata": {"target_note_id": "old_source"},
        },
        db_settings,
    )
    source = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "함께 삭제 소스",
            "body_markdown": "소스 본문",
            "source_note_id": original["id"],
        },
        db_settings,
    )

    deleted = delete_note_with_related_cleanup(
        source["id"],
        expected_version=source["version"],
        delete_original_note=True,
        change_source="test",
        created_by="pytest",
        settings=db_settings,
    )

    deleted_original = get_note(original["id"], db_settings)
    assert deleted["delete_cleanup"]["restored_original_notes"] == 0
    assert deleted["delete_cleanup"]["deleted_original_notes"] == 1
    assert deleted["delete_cleanup"]["source_original"]["action"] == "deleted_with_source"
    assert deleted_original["status"] == "deleted"
    assert deleted_original["deleted_at"] is not None
    assert deleted_original["metadata"]["deleted_reason"] == "delete_with_source"
    assert deleted_original["metadata"]["deleted_source_note_id"] == source["id"]


def test_delete_source_keeps_original_when_other_source_still_references_it(db_settings):
    original = create_note(
        {
            "id": note_id(),
            "kind": "archive",
            "status": "archived",
            "title": "원문 - 공유 원문",
            "body_markdown": "두 소스가 공유하는 원문입니다.",
        },
        db_settings,
    )
    source = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "삭제할 소스",
            "body_markdown": "소스 본문",
            "source_note_id": original["id"],
        },
        db_settings,
    )
    other_source = create_note(
        {
            "id": note_id(),
            "kind": "source",
            "status": "active",
            "title": "남는 소스",
            "body_markdown": "다른 소스 본문",
            "source_note_id": original["id"],
        },
        db_settings,
    )

    deleted = delete_note_with_related_cleanup(
        source["id"],
        expected_version=source["version"],
        delete_original_note=True,
        change_source="test",
        created_by="pytest",
        settings=db_settings,
    )

    kept_original = get_note(original["id"], db_settings)
    assert deleted["delete_cleanup"]["restored_original_notes"] == 0
    assert deleted["delete_cleanup"]["deleted_original_notes"] == 0
    assert deleted["delete_cleanup"]["source_original"]["action"] == "kept_existing_sources"
    assert deleted["delete_cleanup"]["source_original"]["remaining_source_note_ids"] == [other_source["id"]]
    assert kept_original["kind"] == "archive"
    assert kept_original["status"] == "archived"
    assert kept_original["deleted_at"] is None


def test_process_note_revision_to_source_can_store_runner_generated_body(db_settings):
    inbox = create_note(
        {
            "id": note_id(),
            "kind": "inbox",
            "status": "active",
            "title": "Runner Capture",
            "body_markdown": "Raw capture",
        },
        db_settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=db_settings)
    create_request(
        {
            "id": "req_runner_body",
            "source": "pytest",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )

    result = process_note_revision_to_source(
        request_id="req_runner_body",
        note_id=inbox["id"],
        source_revision_id=revision["id"],
        generated_body_markdown="# 러너 캡처\n\n## 추출된 사실\n\n- AI가 생성한 사실입니다.",
        processor="db-note-runner:pytest",
        runner_summary="pytest runner completed",
        settings=db_settings,
    )

    target = result["target_note"]
    archived = result["source_note"]
    assert target["title"] == "러너 캡처"
    assert archived["title"] == "원문 - 러너 캡처"
    assert target["slug"] == "러너-캡처"
    assert "AI가 생성한 사실입니다." in target["body_markdown"]
    assert "## 원본 메모" not in target["body_markdown"]
    assert target["metadata"]["processor"] == "db-note-runner:pytest"
    assert target["metadata"]["runner_summary"] == "pytest runner completed"


def test_process_note_revision_to_source_ignores_default_runner_title(db_settings):
    inbox = create_note(
        {
            "id": note_id(),
            "kind": "inbox",
            "status": "active",
            "title": "제목 없는 노트",
            "body_markdown": "스타벅스에 3만원을 충전했다.",
        },
        db_settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=db_settings)
    create_request(
        {
            "id": "req_default_runner_title",
            "source": "pytest",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )

    result = process_note_revision_to_source(
        request_id="req_default_runner_title",
        note_id=inbox["id"],
        source_revision_id=revision["id"],
        generated_body_markdown=(
            "# 제목 없는 웹 메모\n\n"
            "## 요약\n\n"
            "스타벅스 3만원 충전 기록입니다.\n\n"
            "## 추출된 사실\n\n"
            "- 스타벅스에 3만원을 충전했다."
        ),
        processor="db-note-runner:pytest",
        settings=db_settings,
    )

    target = result["target_note"]
    archived = result["source_note"]
    assert target["title"] == "스타벅스 3만원 충전 기록입니다."
    assert archived["title"] == "원문 - 스타벅스 3만원 충전 기록입니다."
    assert target["slug"] == "스타벅스-3만원-충전-기록입니다"


def test_export_job_lifecycle(db_settings):
    note = create_note({"id": note_id(), "kind": "source", "title": "Export Target"}, db_settings)
    job = create_export_job(scope="note-id", note_id=note["id"], settings=db_settings)

    assert job["status"] == "queued"

    updated = update_export_job(
        job["id"],
        status="succeeded",
        content_commit_sha="abc123",
        settings=db_settings,
    )

    assert updated["status"] == "succeeded"
    assert updated["content_commit_sha"] == "abc123"
    assert updated["processed_at"] is not None
    assert get_latest_export_job_for_note(note["id"], db_settings)["id"] == job["id"]


def test_list_exportable_notes_excludes_deleted_notes(db_settings):
    keep = create_note({"id": note_id(), "kind": "source", "title": "Keep Export"}, db_settings)
    remove = create_note({"id": note_id(), "kind": "source", "title": "Remove Export"}, db_settings)
    update_note(
        remove["id"],
        expected_version=1,
        status="deleted",
        change_source="test",
        settings=db_settings,
    )

    exported_ids = {row["id"] for row in list_exportable_notes(settings=db_settings)}

    assert keep["id"] in exported_ids
    assert remove["id"] not in exported_ids
