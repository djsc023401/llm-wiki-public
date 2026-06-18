from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest

import llm_wiki.api as api
import llm_wiki.chat_search as chat_search
from llm_wiki.api import app, settings_dep
from llm_wiki.chat_ai import ChatAnswerResult
from llm_wiki.chat_search import _build_answer, _build_answer_refs, _build_query_plan, _rank_notes, run_chat_search
from llm_wiki.config import Settings
from llm_wiki.db import connect, fetch_one
from llm_wiki.notes_store import add_note_link, create_export_job, create_note, update_export_job
from llm_wiki.personalization import update_personalization_settings
from llm_wiki.requests_store import create_request, get_request, update_status
from llm_wiki.time_store import create_time_item, list_time_items


def test_note_api_lifecycle_and_admin_auth(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        assert client.get("/api/notes").status_code == 401
        assert client.get("/api/notes", headers={"Authorization": "Bearer plugin-token"}).status_code == 401

        created = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "inbox",
                "status": "draft",
                "title": "API Note",
                "body_markdown": "Initial body",
                "metadata": {"channel": "pytest"},
                "change_source": "test",
                "created_by": "pytest",
            },
        )

        assert created.status_code == 200
        note = created.json()
        assert note["version"] == 1
        assert note["metadata"] == {"channel": "pytest"}

        detail = client.get(f"/api/notes/{note['id']}", headers={"Authorization": "Bearer admin-token"})
        assert detail.status_code == 200
        assert detail.json()["body_markdown"] == "Initial body"
        assert detail.json()["delete_capability"]["can_delete"] is True
        assert detail.json()["delete_capability"]["blockers"] == []

        listing = client.get(
            "/api/notes?kind=inbox&status=draft&q=API&limit=5",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert listing.status_code == 200
        assert [row["id"] for row in listing.json()] == [note["id"]]

        tagged = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "Tagged Source",
                "body_markdown": "Tagged body",
                "metadata": {"manual_tags": ["투자", "건강"]},
                "change_source": "test",
            },
        )
        assert tagged.status_code == 200
        untagged = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "Untagged Source",
                "body_markdown": "Untagged body",
                "metadata": {"manual_tags": ["일정"]},
                "change_source": "test",
            },
        )
        assert untagged.status_code == 200
        tag_listing = client.get(
            "/api/notes?kind=source&tag=투자&limit=10",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert tag_listing.status_code == 200
        tag_ids = [row["id"] for row in tag_listing.json()]
        assert tagged.json()["id"] in tag_ids
        assert untagged.json()["id"] not in tag_ids
        first_page = client.get(
            "/api/notes?kind=source&q=Source&limit=1",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert first_page.status_code == 200
        assert len(first_page.json()) == 1
        cursor = first_page.json()[0]
        second_page = client.get(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            params={
                "kind": "source",
                "q": "Source",
                "limit": 1,
                "cursor_updated_at": cursor["updated_at"],
                "cursor_created_at": cursor["created_at"],
                "cursor_id": cursor["id"],
            },
        )
        assert second_page.status_code == 200
        assert second_page.json()
        assert cursor["id"] not in [row["id"] for row in second_page.json()]

        updated = client.patch(
            f"/api/notes/{note['id']}",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": 1,
                "status": "active",
                "body_markdown": "Updated body",
                "metadata": {"channel": "pytest", "state": "updated"},
                "change_source": "test",
                "created_by": "pytest",
            },
        )

        assert updated.status_code == 200
        assert updated.json()["version"] == 2
        assert updated.json()["status"] == "active"

        stale = client.patch(
            f"/api/notes/{note['id']}",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 1, "body_markdown": "stale body", "change_source": "test"},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"] == "stale_note_version"

        revisions = client.get(
            f"/api/notes/{note['id']}/revisions",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert revisions.status_code == 200
        assert [row["version"] for row in revisions.json()] == [2, 1]

        plugin_process = client.post(
            f"/api/notes/{note['id']}/process",
            headers={"Authorization": "Bearer plugin-token"},
            json={"expected_version": 2},
        )
        assert plugin_process.status_code == 401

        stale_process = client.post(
            f"/api/notes/{note['id']}/process",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 1},
        )
        assert stale_process.status_code == 409

        process = client.post(
            f"/api/notes/{note['id']}/process",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 2},
        )
        assert process.status_code == 200
        request = process.json()
        assert request["input_mode"] == "db-note"
        assert request["file_path"] is None
        assert request["note_id"] == note["id"]
        assert request["source_revision_id"] == revisions.json()[0]["id"]
        assert request["status"] == "queued"

        detail_with_request = client.get(
            f"/api/notes/{note['id']}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert detail_with_request.status_code == 200
        assert detail_with_request.json()["latest_processing_request"]["id"] == request["id"]
        assert detail_with_request.json()["latest_processing_request"]["note_id"] == note["id"]
        assert detail_with_request.json()["latest_processing_request"]["source_revision_id"] == request["source_revision_id"]
        assert detail_with_request.json()["latest_processing_request"]["status"] == "queued"
        assert detail_with_request.json()["delete_capability"]["can_delete"] is True
        assert detail_with_request.json()["delete_capability"]["queued_request_ids"] == [request["id"]]

        duplicate = client.post(
            f"/api/notes/{note['id']}/process",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 2},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["id"] == request["id"]

        delete_candidate = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "inbox",
                "status": "draft",
                "title": "Queued Delete Candidate",
                "body_markdown": "Delete while queued.",
                "metadata": {"channel": "pytest"},
                "change_source": "test",
                "created_by": "pytest",
            },
        )
        assert delete_candidate.status_code == 200
        delete_candidate_process = client.post(
            f"/api/notes/{delete_candidate.json()['id']}/process",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 1},
        )
        assert delete_candidate_process.status_code == 200
        delete_processing = client.post(
            f"/api/notes/{delete_candidate.json()['id']}/delete",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 1, "change_source": "test", "created_by": "pytest"},
        )
        assert delete_processing.status_code == 200
        assert delete_processing.json()["status"] == "deleted"
        cleanup = delete_processing.json()["delete_cleanup"]
        assert cleanup["cancelled_processing_request"]["id"] == delete_candidate_process.json()["id"]
        assert get_request(delete_candidate_process.json()["id"], settings)["status"] == "cancelled"

        update_status(request["id"], "running", settings=settings)
        duplicate_running = client.post(
            f"/api/notes/{note['id']}/process",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 2},
        )
        assert duplicate_running.status_code == 200
        assert duplicate_running.json()["id"] == request["id"]
        assert duplicate_running.json()["status"] == "running"
        running_detail = client.get(
            f"/api/notes/{note['id']}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert running_detail.status_code == 200
        assert running_detail.json()["delete_capability"]["can_delete"] is False
        assert running_detail.json()["delete_capability"]["blockers"] == ["running_processing_request"]
        assert running_detail.json()["delete_capability"]["running_request_ids"] == [request["id"]]

        delete_running = client.post(
            f"/api/notes/{note['id']}/delete",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 2, "change_source": "test", "created_by": "pytest"},
        )
        assert delete_running.status_code == 422
        assert delete_running.json()["detail"] == "note_delete_processing_not_supported"

        update_status(request["id"], "needs_sync", settings=settings)
        duplicate_needs_sync = client.post(
            f"/api/notes/{note['id']}/process",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 2},
        )
        assert duplicate_needs_sync.status_code == 200
        assert duplicate_needs_sync.json()["id"] == request["id"]
        assert duplicate_needs_sync.json()["status"] == "needs_sync"

        admin_request = client.get(
            f"/api/requests/{request['id']}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert admin_request.status_code == 200
        assert admin_request.json()["id"] == request["id"]
        assert "content_snapshot" not in admin_request.json()

        archived = client.post(
            f"/api/notes/{note['id']}/archive",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 2, "change_source": "test", "created_by": "pytest"},
        )
        assert archived.status_code == 200
        assert archived.json()["version"] == 3
        assert archived.json()["status"] == "archived"
        assert archived.json()["archived_at"] is not None

        deleted = client.post(
            f"/api/notes/{note['id']}/delete",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 3, "change_source": "test", "created_by": "pytest"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["version"] == 4
        assert deleted.json()["status"] == "deleted"
        assert deleted.json()["deleted_at"] is not None

        hidden_listing = client.get(
            "/api/notes?kind=inbox&q=API&limit=5",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert hidden_listing.status_code == 200
        assert note["id"] not in [row["id"] for row in hidden_listing.json()]

        deleted_listing = client.get(
            "/api/notes?kind=inbox&q=API&include_deleted=true&limit=5",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert deleted_listing.status_code == 200
        assert note["id"] in [row["id"] for row in deleted_listing.json()]
    finally:
        app.dependency_overrides.clear()


def test_note_api_resolves_note_references_for_preview(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        assert client.get("/api/notes/resolve").status_code == 401
        assert client.get(
            "/api/notes/resolve",
            headers={"Authorization": "Bearer plugin-token"},
        ).status_code == 401

        source = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "미리보기 소스",
                "slug": "preview-source",
                "body_markdown": "본문",
                "change_source": "test",
            },
        )
        assert source.status_code == 200
        topic = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "topic",
                "status": "active",
                "title": "미리보기 주제",
                "slug": "preview-topic",
                "body_markdown": "본문",
                "change_source": "test",
            },
        )
        assert topic.status_code == 200

        resolved = client.get(
            "/api/notes/resolve",
            headers={"Authorization": "Bearer admin-token"},
            params=[
                ("ids", topic.json()["id"]),
                ("ids", "note_missing1234"),
                ("ids", source.json()["id"]),
                ("ids", topic.json()["id"]),
            ],
        )
        assert resolved.status_code == 200
        rows = resolved.json()
        assert [row["id"] for row in rows] == [topic.json()["id"], source.json()["id"]]
        assert rows[0]["kind"] == "topic"
        assert rows[0]["title"] == "미리보기 주제"
        assert rows[0]["slug"] == "preview-topic"
        assert rows[1]["kind"] == "source"
        assert rows[1]["status"] == "active"

        invalid = client.get(
            "/api/notes/resolve?ids=bad-id",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"] == "invalid_note_id"
    finally:
        app.dependency_overrides.clear()


def test_chat_search_api_returns_ranked_note_evidence(db_settings):
    settings = replace(
        db_settings,
        api_admin_token="admin-token",
        api_plugin_token="plugin-token",
        chat_answer_provider="rules",
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        topic = create_note(
            {
                "kind": "topic",
                "status": "active",
                "title": "배당률",
                "body_markdown": "배당 수익률을 모아보는 주제입니다.",
                "change_source": "test",
            },
            settings,
        )
        source = create_note(
            {
                "kind": "source",
                "status": "active",
                "title": "QQQI 배당률 메모",
                "body_markdown": "QQQI의 연 배당률이 약 14%라고 기록한 메모입니다.",
                "metadata": {
                    "manual_tags": ["투자"],
                    "manual_topics": ["배당률"],
                    "approved_topics": [{"title": "배당률", "note_id": topic["id"]}],
                },
                "change_source": "test",
            },
            settings,
        )
        add_note_link(
            source["id"],
            target_text="배당률",
            to_note_id=topic["id"],
            link_type="topic_suggestion",
            settings=settings,
        )

        response = client.post(
            "/api/chat/search",
            headers={"Authorization": "Bearer admin-token"},
            json={"query": "QQQI 배당률", "limit": 5},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answer_mode"] == "planned_retrieval"
        assert payload["meta"]["ai_configured"] is False
        assert payload["items"]
        assert payload["items"][0]["note_id"] == source["id"]
        assert payload["items"][0]["kind"] == "source"
        assert "배당률" in payload["items"][0]["topics"]
        assert "투자" in payload["items"][0]["tags"]
        assert payload["answer_refs"][0]["note_id"] == source["id"]
        assert payload["answer_refs"][0]["kind"] == "source"
        assert "QQQI" in payload["answer"]
        assert "배당률" in payload["answer"]
        assert payload["session_id"].startswith("chat_")
        assert payload["turn_id"].startswith("turn_")
        assert payload["conversation"]["id"] == payload["session_id"]
        assert len(payload["conversation"]["turns"]) == 1
        with connect(settings) as conn:
            assert fetch_one(conn, "select id from chat_sessions where id = %s", (payload["session_id"],))
            stored_turn = fetch_one(conn, "select query, turn_index from chat_turns where id = %s", (payload["turn_id"],))
            assert stored_turn == {"query": "QQQI 배당률", "turn_index": 1}

        followup = client.post(
            "/api/chat/search",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "query": "관련 소스만 보여줘",
                "limit": 5,
                "session_id": payload["session_id"],
            },
        )
        assert followup.status_code == 200
        followup_payload = followup.json()
        assert followup_payload["session_id"] == payload["session_id"]
        assert len(followup_payload["conversation"]["turns"]) == 2
        assert followup_payload["meta"]["query_plan"]["context_used"] is True
        assert source["id"] in [item.get("note_id") for item in followup_payload["items"]]
        assert "이전 대화 맥락" in followup_payload["answer"]

        listed = client.get(
            "/api/chat/sessions",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == payload["session_id"]

        detail = client.get(
            f"/api/chat/sessions/{payload['session_id']}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert detail.status_code == 200
        assert [turn["turn_index"] for turn in detail.json()["turns"]] == [1, 2]

        deleted = client.delete(
            f"/api/chat/sessions/{payload['session_id']}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": True, "id": payload["session_id"]}
        assert client.get(
            f"/api/chat/sessions/{payload['session_id']}",
            headers={"Authorization": "Bearer admin-token"},
        ).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_chat_search_marks_answer_mode_ai_when_chat_provider_used(monkeypatch, db_settings):
    update_personalization_settings(
        {
            "workflow_mode": "personal",
            "timezone": "UTC",
            "default_schedule_days": 14,
            "personal_terms": ["장보기"],
            "classification_seeds": ["생활 관리"],
            "aliases": ["치약=생활용품"],
            "priority_terms": ["건강"],
            "custom_facets": ["생활"],
            "preference_rules": ["결론 먼저"],
        },
        db_settings,
    )
    create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "치약 구매 필요",
            "body_markdown": "집에 남아있는 치약이 없어서 구매해야 한다.",
            "change_source": "test",
        },
        db_settings,
    )

    captured = {}

    def fake_generate_chat_answer(*_args, **_kwargs):
        captured.update(_kwargs)
        return ChatAnswerResult(
            answer="기록 기준으로 부족한 물품은 치약입니다.",
            provider="openai-api",
            configured=True,
            used=True,
            model="gpt-test",
            prompt_chars=1234,
            max_prompt_chars=24000,
            evidence_count=2,
            usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )

    monkeypatch.setattr(chat_search, "generate_chat_answer", fake_generate_chat_answer)

    settings = replace(
        db_settings,
        chat_answer_openai_input_cost_per_1m_tokens=0.25,
        chat_answer_openai_output_cost_per_1m_tokens=2.0,
    )

    payload = run_chat_search("집에 부족한 물품이 뭐야?", settings=settings)

    assert payload["answer_mode"] == "ai"
    assert payload["answer"] == "기록 기준으로 부족한 물품은 치약입니다."
    assert payload["meta"]["ai_provider"] == "openai-api"
    assert payload["meta"]["ai_configured"] is True
    assert payload["meta"]["ai_answer_used"] is True
    assert payload["meta"]["ai_model"] == "gpt-test"
    assert payload["meta"]["ai_prompt_chars"] == 1234
    assert payload["meta"]["ai_max_prompt_chars"] == 24000
    assert payload["meta"]["ai_evidence_count"] == 2
    assert payload["meta"]["ai_usage"] == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    assert payload["meta"]["ai_cost_estimate_configured"] is True
    assert payload["meta"]["ai_input_cost_per_1m_tokens"] == 0.25
    assert payload["meta"]["ai_output_cost_per_1m_tokens"] == 2.0
    assert payload["meta"]["ai_estimated_input_cost_usd"] == 0.000025
    assert payload["meta"]["ai_estimated_output_cost_usd"] == 0.00004
    assert payload["meta"]["ai_estimated_cost_usd"] == 0.000065
    assert captured["personalization_context"]["workflow_mode"] == "personal"
    assert captured["personalization_context"]["timezone"] == "UTC"
    assert captured["personalization_context"]["default_schedule_days"] == 14
    assert captured["personalization_context"]["personal_terms"] == ["장보기"]
    assert captured["personalization_context"]["aliases"] == ["치약=생활용품"]
    assert captured["personalization_context"]["priority_terms"] == ["건강"]
    assert captured["personalization_context"]["custom_facets"] == ["생활"]
    assert captured["personalization_context"]["preference_rules"] == ["결론 먼저"]


def test_chat_search_uses_personal_timezone_and_schedule_horizon(db_settings):
    update_personalization_settings({"timezone": "UTC", "default_schedule_days": 2}, db_settings)
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "개인 일정 소스",
            "body_markdown": "앞으로 확인할 일정입니다.",
            "change_source": "test",
        },
        db_settings,
    )
    within = create_time_item(
        {
            "note_id": source["id"],
            "source_note_id": source["id"],
            "kind": "event",
            "status": "active",
            "title": "설정 범위 안 일정",
            "start_at": "2026-06-09T00:30:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        db_settings,
    )
    outside = create_time_item(
        {
            "note_id": source["id"],
            "source_note_id": source["id"],
            "kind": "event",
            "status": "active",
            "title": "설정 범위 밖 일정",
            "start_at": "2026-06-11T00:30:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        db_settings,
    )

    payload = run_chat_search(
        "앞으로 일정",
        settings=db_settings,
        now=datetime(2026, 6, 8, 12, 0, tzinfo=ZoneInfo("UTC")),
    )

    plan = payload["meta"]["query_plan"]
    assert plan["primary_domain"] == "time"
    assert plan["timezone"] == "UTC"
    assert plan["default_schedule_days"] == 2
    assert plan["time_range"]["from"].startswith("2026-06-08T12:00:00")
    assert plan["time_range"]["to"].startswith("2026-06-10T12:00:00")
    assert any(item.get("time_item_id") == within["id"] for item in payload["items"])
    assert not any(item.get("time_item_id") == outside["id"] for item in payload["items"])
    result = next(item for item in payload["items"] if item.get("time_item_id") == within["id"])
    assert "2026-06-08 15:30" in result["when_label"]


def test_chat_search_today_briefing_matches_home_work_items(db_settings):
    settings = replace(db_settings, chat_answer_provider="rules")
    update_personalization_settings({"timezone": "Asia/Seoul", "default_schedule_days": 2}, settings)
    now = datetime(2026, 6, 8, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "오늘 브리핑 소스",
            "body_markdown": "\n".join(
                [
                    "# 오늘 브리핑 소스",
                    "",
                    "확인할 작업과 제안이 있다.",
                    "",
                    "### 주제 제안",
                    "",
                    "| 후보 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- |",
                    "| 홈 화면 개선 | `wiki/topics/홈-화면-개선.md` | 작업을 한 곳에서 본다. | 오늘 확인 후보이다. |",
                ]
            ),
            "change_source": "test",
        },
        settings,
    )
    draft = create_note(
        {
            "kind": "inbox",
            "status": "draft",
            "title": "작성중 브리핑 노트",
            "body_markdown": "오늘 안에 정리할 초안",
            "change_source": "test",
        },
        settings,
    )
    stale_draft = create_note(
        {
            "kind": "inbox",
            "status": "draft",
            "title": "오래된 작성중 브리핑 노트",
            "body_markdown": "며칠째 정리하지 않은 초안",
            "change_source": "test",
        },
        settings,
    )
    today_reminder = create_time_item(
        {
            "note_id": source["id"],
            "source_note_id": source["id"],
            "kind": "task",
            "status": "active",
            "title": "오늘 알림만 있는 작업",
            "body_markdown": "마감은 내일이지만 오늘 확인 알림이 있다.",
            "due_at": "2026-06-09T12:00:00+09:00",
            "remind_at": "2026-06-08T10:00:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        settings,
    )
    overdue = create_time_item(
        {
            "note_id": source["id"],
            "source_note_id": source["id"],
            "kind": "deadline",
            "status": "active",
            "title": "어제 마감 작업",
            "due_at": "2026-06-07T18:00:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        settings,
    )
    upcoming = create_time_item(
        {
            "note_id": source["id"],
            "source_note_id": source["id"],
            "kind": "event",
            "status": "active",
            "title": "이틀 안 예정",
            "start_at": "2026-06-10T09:00:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        settings,
    )
    outside = create_time_item(
        {
            "note_id": source["id"],
            "source_note_id": source["id"],
            "kind": "event",
            "status": "active",
            "title": "범위 밖 예정",
            "start_at": "2026-06-11T09:00:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        settings,
    )
    failed_request = create_request(
        {
            "id": "req_chat_daily_failed",
            "source": "chat-daily-test",
            "operation": "ingest",
            "input_mode": "snapshot",
            "content_snapshot": "오늘 브리핑 실패 요청",
        },
        settings,
    )
    update_status(failed_request["id"], "failed", error_message="대화 브리핑 AI 실패", settings=settings)
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update notes set updated_at = %s where id = %s",
                ("2026-06-01T09:00:00+09:00", stale_draft["id"]),
            )
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload, error_message
                )
                values (
                  'ntf_chat_daily_failed1234',
                  %s,
                  'pwa',
                  'failed',
                  %s,
                  '{"title": "실패 알림", "body": "오늘 알림만 있는 작업"}'::jsonb,
                  'send failed'
                )
                """,
                (today_reminder["id"], "2026-06-08T10:00:00+09:00"),
            )
        conn.commit()

    payload = run_chat_search("오늘 처리할 일", settings=settings, now=now)

    plan = payload["meta"]["query_plan"]
    assert plan["primary_domain"] == "daily_briefing"
    assert plan["daily_briefing"] is True
    assert plan["timezone"] == "Asia/Seoul"
    assert plan["default_schedule_days"] == 2
    assert plan["daily_digest_time"] == "08:00"
    assert plan["focus_terms"] == []
    ids = {item.get("time_item_id") for item in payload["items"]}
    assert today_reminder["id"] in ids
    assert overdue["id"] in ids
    assert upcoming["id"] in ids
    assert outside["id"] not in ids
    assert any(item.get("processing_request_id") == "req_chat_daily_failed" for item in payload["items"])
    assert any(item.get("notification_delivery_id") == "ntf_chat_daily_failed1234" for item in payload["items"])
    assert any(item.get("item_type") == "suggestion" and "홈 화면 개선" in item.get("title", "") for item in payload["items"])
    assert any(item.get("note_id") == draft["id"] and item.get("briefing_bucket") == "draft_notes" for item in payload["items"])
    assert any(item.get("note_id") == stale_draft["id"] and item.get("briefing_bucket") == "stale_draft_notes" for item in payload["items"])
    assert "오늘 처리할 일" in payload["answer"]
    assert "Asia/Seoul" in payload["answer"]
    assert "2일 이내" in payload["answer"]
    assert "하루 요약 08:00" in payload["answer"]
    assert "오늘 일정/할 일" in payload["answer"]
    assert "AI 처리 실패" in payload["answer"]
    assert "대화 브리핑 AI 실패" in payload["answer"]
    assert "지연된 항목" in payload["answer"]
    assert payload["answer"].index("오늘 일정/할 일") < payload["answer"].index("지연된 항목")
    assert payload["answer"].index("지연된 항목") < payload["answer"].index("다가오는 예정")
    assert payload["answer"].index("\n작성중 노트") < payload["answer"].index("\n오래된 작성중 노트")
    assert "미검토 제안" in payload["answer"]
    refs = payload["answer_refs"]
    assert any(ref.get("processing_request_id") == "req_chat_daily_failed" for ref in refs)


def test_chat_search_prioritizes_structured_time_items_without_hardcoded_topic(db_settings):
    settings = replace(db_settings, chat_answer_provider="rules")
    travel_original = create_note(
        {
            "kind": "archive",
            "status": "archived",
            "title": "원문 - 강릉 친구 여행 계획",
            "body_markdown": "강릉 친구 여행 계획을 처음 적은 원문입니다.",
            "change_source": "test",
        },
        db_settings,
    )
    travel_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "강릉 친구 여행 계획",
            "body_markdown": "친구들과 강릉으로 2박 3일 여행을 계획한다.",
            "source_note_id": travel_original["id"],
            "metadata": {"manual_tags": ["여행"], "manual_topics": ["강릉 여행"]},
            "change_source": "test",
        },
        db_settings,
    )
    other_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "7월 17일 서예 방문 예정",
            "body_markdown": "서예 수업에 방문하기로 했다.",
            "metadata": {"manual_tags": ["일정"], "manual_topics": ["개인 일정"]},
            "change_source": "test",
        },
        db_settings,
    )
    travel_item = create_time_item(
        {
            "note_id": travel_source["id"],
            "source_note_id": travel_source["id"],
            "kind": "event",
            "status": "active",
            "title": "강릉 친구 여행",
            "body_markdown": "강릉 2박 3일 여행 후보 일정",
            "start_at": "2026-09-15T10:00:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        db_settings,
    )
    other_item = create_time_item(
        {
            "note_id": other_source["id"],
            "source_note_id": other_source["id"],
            "kind": "event",
            "status": "active",
            "title": "서예 방문",
            "body_markdown": "서예 수업 방문 일정",
            "start_at": "2026-07-17T10:00:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        db_settings,
    )
    family_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "가족 국내여행 휴가",
            "body_markdown": "가족과 8월 국내여행을 검토한다.",
            "metadata": {"manual_tags": ["여행"], "manual_topics": ["가족 여행"]},
            "change_source": "test",
        },
        db_settings,
    )
    family_item = create_time_item(
        {
            "note_id": family_source["id"],
            "source_note_id": family_source["id"],
            "kind": "event",
            "status": "active",
            "title": "가족 국내여행 휴가",
            "body_markdown": "8월 가족 국내여행 일정",
            "start_at": "2026-08-01T10:00:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        db_settings,
    )
    planning_deadline = create_time_item(
        {
            "note_id": travel_source["id"],
            "source_note_id": travel_source["id"],
            "kind": "reminder",
            "status": "active",
            "title": "강릉 여행 준비 마감",
            "body_markdown": "여행 준비를 끝내야 하는 마감",
            "due_at": "2026-07-15T00:00:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        db_settings,
    )

    payload = run_chat_search(
        "올해 남은 여행 일정",
        settings=settings,
        now=datetime(2026, 6, 7, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert payload["answer_mode"] == "planned_retrieval"
    assert payload["meta"]["query_plan"]["primary_domain"] == "time"
    assert payload["meta"]["query_plan"]["focus_terms"] == ["여행"]
    assert payload["meta"]["query_plan"]["time_kinds"] == ["event"]
    assert payload["meta"]["query_plan"]["time_shape"] == "start"
    assert any(item.get("time_item_id") == travel_item["id"] for item in payload["items"])
    travel_result = next(item for item in payload["items"] if item.get("time_item_id") == travel_item["id"])
    assert travel_result["source_note_id"] == travel_source["id"]
    assert travel_result["source_note_title"] == "강릉 친구 여행 계획"
    assert travel_result["original_note_id"] == travel_original["id"]
    assert travel_result["original_note_title"] == "원문 - 강릉 친구 여행 계획"
    travel_ref = next(
        ref for ref in payload["answer_refs"] if ref.get("time_item_id") == travel_item["id"]
    )
    assert travel_ref["item_type"] == "time_item"
    assert any(item.get("item_type") == "note" and item.get("note_id") == travel_source["id"] for item in payload["items"])
    assert any(item.get("time_item_id") == family_item["id"] for item in payload["items"])
    assert not any(item.get("time_item_id") == other_item["id"] for item in payload["items"])
    assert not any(item.get("time_item_id") == planning_deadline["id"] for item in payload["items"])
    assert "2026-09-15" in payload["answer"]
    assert "서예" not in payload["answer"]

    followup = run_chat_search(
        "강릉 여행 계획 관련 일정만 보여줘",
        settings=settings,
        now=datetime(2026, 6, 7, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        context={
            "parent_query": payload["query"],
            "query_plan": payload["meta"]["query_plan"],
            "messages": [{"query": payload["query"], "answer": payload["answer"]}],
            "items": payload["items"],
        },
    )

    assert followup["meta"]["query_plan"]["context_used"] is True
    assert followup["meta"]["query_plan"]["focus_match"] == "all"
    assert followup["meta"]["query_plan"]["time_range"]["from"].startswith("2026-06-07T12:00:00")
    assert any(item.get("time_item_id") == travel_item["id"] for item in followup["items"])
    assert not any(item.get("time_item_id") == family_item["id"] for item in followup["items"])
    assert "이전 대화 맥락" in followup["answer"]

    detail_followup = run_chat_search(
        "강릉 여행에 대해 자세히 알려줘",
        settings=settings,
        now=datetime(2026, 6, 7, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        context={
            "parent_query": payload["query"],
            "query_plan": payload["meta"]["query_plan"],
            "messages": [{"query": payload["query"], "answer": payload["answer"]}],
            "items": payload["items"],
        },
    )

    assert detail_followup["meta"]["query_plan"]["context_used"] is True
    assert detail_followup["meta"]["query_plan"]["primary_domain"] == "time"
    assert detail_followup["meta"]["query_plan"]["answer_intent"] == "detail_summary"
    assert detail_followup["meta"]["query_plan"]["focus_terms"] == ["강릉", "여행"]
    assert any(item.get("time_item_id") == travel_item["id"] for item in detail_followup["items"])
    assert not any(item.get("time_item_id") == family_item["id"] for item in detail_followup["items"])
    assert "조건에 맞는 일정/알림" not in detail_followup["answer"]
    assert "강릉 친구 여행" in detail_followup["answer"]
    assert "시점:" in detail_followup["answer"]
    assert "2박 3일" in detail_followup["answer"]


def test_chat_search_state_answer_synthesis_is_concise():
    plan = {
        "query": "집에 부족한 물품이 뭐야?",
        "primary_domain": "notes",
        "answer_intent": "state_summary",
        "focus_terms": ["집", "부족한", "물품"],
        "context": {"applied": False},
    }
    answer = _build_answer(
        plan,
        [
            {
                "item_type": "note",
                "note_id": "note_need",
                "kind": "source",
                "kind_label": "소스",
                "title": "집에 남아있는 치약이 없다",
                "excerpt": "집에 남아있는 치약이 없어서 새로 구매해야 한다.",
                "tags": ["생활용품", "재고부족"],
                "topics": ["생활용품 재고"],
                "entities": ["치약"],
                "score": 50,
                "updated_at": "2026-06-07T10:00:00+09:00",
                "matched_fields": ["본문", "태그"],
            },
            {
                "item_type": "note",
                "note_id": "note_done",
                "kind": "source",
                "kind_label": "소스",
                "title": "치약 구매 완료",
                "excerpt": "치약 구매를 완료했다.",
                "tags": ["생활용품"],
                "topics": ["생활용품 재고"],
                "entities": ["치약"],
                "score": 40,
                "updated_at": "2026-06-08T09:00:00+09:00",
                "matched_fields": ["태그"],
            },
        ],
    )

    assert "치약" in answer
    assert "해결" in answer or "해소" in answer or "완료" in answer
    assert "근거 버튼" in answer
    assert "관련된 근거" not in answer


def test_chat_search_state_answer_prioritizes_unresolved_substrings():
    plan = {
        "query": "집에 부족한 물품이 뭐야?",
        "primary_domain": "notes",
        "answer_intent": "state_summary",
        "focus_terms": ["집", "부족한", "물품"],
        "context": {"applied": False},
    }
    answer = _build_answer(
        plan,
        [
            {
                "item_type": "note",
                "note_id": "note_unfinished",
                "kind": "source",
                "kind_label": "소스",
                "title": "치약 구매 미완료",
                "excerpt": "아직 치약 구매를 하지 못했다.",
                "tags": ["생활용품"],
                "topics": ["생활용품 재고"],
                "entities": ["치약"],
                "score": 50,
                "updated_at": "2026-06-08T10:00:00+09:00",
                "matched_fields": ["제목", "본문"],
            }
        ],
    )

    assert "치약" in answer
    assert "부족하거나 조치가 필요한 항목" in answer
    assert "완료 또는 해결된 항목" not in answer


def test_chat_search_state_answer_handles_negated_need_phrases():
    plan = {
        "query": "집에 부족한 물품이 뭐야?",
        "primary_domain": "notes",
        "answer_intent": "state_summary",
        "focus_terms": ["집", "부족한", "물품"],
        "context": {"applied": False},
    }
    answer = _build_answer(
        plan,
        [
            {
                "item_type": "note",
                "note_id": "note_enough",
                "kind": "source",
                "kind_label": "소스",
                "title": "치약 구매 필요 없음",
                "excerpt": "치약은 충분해서 부족하지 않다. 문제 없음.",
                "tags": ["생활용품"],
                "topics": ["생활용품 재고"],
                "entities": ["치약"],
                "score": 50,
                "updated_at": "2026-06-08T10:00:00+09:00",
                "matched_fields": ["제목", "본문"],
            }
        ],
    )

    assert "치약" in answer
    assert "미해결 항목은 명확히 확인되지 않습니다" in answer
    assert "부족하거나 조치가 필요한 항목" not in answer


def test_chat_search_retrieval_answer_uses_answer_style_not_raw_result_list():
    plan = {
        "query": "강릉 여행",
        "primary_domain": "notes",
        "answer_intent": "retrieval",
        "focus_terms": ["강릉", "여행"],
        "context": {"applied": False},
    }
    answer = _build_answer(
        plan,
        [
            {
                "item_type": "note",
                "note_id": "note_trip",
                "kind": "source",
                "kind_label": "소스",
                "title": "강릉 친구 여행 계획",
                "excerpt": "친구들과 강릉으로 2박 3일 여행을 계획한다.",
                "tags": ["여행"],
                "topics": ["강릉 여행 계획"],
                "entities": ["강원도 강릉"],
                "score": 60,
                "updated_at": "2026-06-08T10:00:00+09:00",
                "matched_fields": ["제목", "본문", "주제"],
            },
            {
                "item_type": "note",
                "note_id": "note_topic",
                "kind": "topic",
                "kind_label": "주제",
                "title": "강릉 여행 계획",
                "excerpt": "강릉 여행 계획과 연결된 주제다.",
                "tags": [],
                "topics": [],
                "entities": [],
                "score": 40,
                "updated_at": "2026-06-08T10:10:00+09:00",
                "matched_fields": ["제목"],
            },
        ],
    )

    assert "가장 관련 있는 기록은 강릉 친구 여행 계획" in answer
    assert "친구들과 강릉으로 2박 3일 여행" in answer
    assert "근거 위치: 제목, 본문, 주제" in answer
    assert "관련 근거 2건은 근거 버튼" in answer
    assert "'강릉 여행'와 관련된 근거" not in answer
    assert "1. 강릉 친구 여행 계획" not in answer


def test_chat_search_time_answer_groups_related_time_items():
    plan = {
        "query": "올해 남은 여행",
        "primary_domain": "time",
        "answer_intent": "retrieval",
        "focus_terms": ["여행"],
        "time_range": {"label": "2026-06-08 10:30부터 2026-12-31 23:59까지"},
        "context": {"applied": False},
    }
    items = [
        {
            "item_type": "time_item",
            "time_item_id": "time_gn_deadline_1",
            "note_id": "note_gn",
            "source_note_id": "note_gn",
            "time_kind": "reminder",
            "kind_label": "마감",
            "title": "강릉 여행 계획 완성",
            "when_label": "마감 2026-06-15 00:00",
            "sort_at": "2026-06-15T00:00:00+09:00",
            "excerpt": "가장 이른 검토 마감이다.",
        },
        {
            "item_type": "time_item",
            "time_item_id": "time_gn_deadline_2",
            "note_id": "note_gn",
            "source_note_id": "note_gn",
            "time_kind": "reminder",
            "kind_label": "마감",
            "title": "강릉 여행 계획 완성",
            "when_label": "마감 2026-07-15 00:00",
            "sort_at": "2026-07-15T00:00:00+09:00",
            "excerpt": "가장 늦은 검토 마감이다.",
        },
        {
            "item_type": "time_item",
            "time_item_id": "time_gn_event",
            "note_id": "note_gn",
            "source_note_id": "note_gn",
            "time_kind": "reminder",
            "kind_label": "일정",
            "title": "강릉 친구 여행 후보 기간",
            "when_label": "시작 2026-09-15 00:00 / 종료 2026-10-15 00:00",
            "sort_at": "2026-09-15T00:00:00+09:00",
            "excerpt": "정확한 출발일과 종료일은 미정이다.",
        },
        {
            "item_type": "time_item",
            "time_item_id": "time_family_task",
            "note_id": "note_family",
            "source_note_id": "note_family",
            "time_kind": "task",
            "kind_label": "할 일",
            "title": "가족 여행 계획 세우기",
            "when_label": "마감 2026-08-01 00:00",
            "sort_at": "2026-08-01T00:00:00+09:00",
            "excerpt": "여행 시작 전까지 계획을 세우는 작업 후보다.",
        },
        {
            "item_type": "time_item",
            "time_item_id": "time_family_event",
            "note_id": "note_family",
            "source_note_id": "note_family",
            "time_kind": "reminder",
            "kind_label": "일정",
            "title": "가족 국내여행 휴가",
            "when_label": "시작 2026-08-01 00:00 / 종료 2026-08-09 00:00",
            "sort_at": "2026-08-01T00:00:00+09:00",
            "excerpt": "가까운 8월로 해석한 검토 후보다.",
        },
        {
            "item_type": "note",
            "note_id": "note_gn",
            "kind": "source",
            "kind_label": "소스",
            "title": "강릉 친구 여행 계획",
        },
    ]

    answer = _build_answer(plan, items)
    refs = _build_answer_refs(plan, items)
    ref_ids = [ref["time_item_id"] for ref in refs]

    assert "2개 묶음" in answer
    assert answer.count("강릉 친구 여행 후보 기간") == 1
    assert "강릉 여행 계획 완성" not in answer
    assert "마감 2건" in answer
    assert answer.count("가족 국내여행 휴가") == 1
    assert "할 일 1건" in answer
    assert "관련 노트 1건은 근거 버튼" in answer
    assert "time_gn_event" in ref_ids
    assert "time_family_event" in ref_ids
    assert "time_gn_deadline_1" in ref_ids
    assert "time_gn_deadline_2" in ref_ids
    assert ref_ids.index("time_gn_event") < ref_ids.index("time_gn_deadline_1")


def test_chat_daily_briefing_answer_groups_related_time_items():
    plan = {
        "query": "오늘 처리할 일",
        "primary_domain": "daily_briefing",
        "daily_briefing": True,
        "default_schedule_days": 7,
        "timezone": "Asia/Seoul",
        "daily_digest_time": "07:30",
        "now": datetime(2026, 6, 14, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    }
    items = [
        {
            "item_type": "time_item",
            "time_item_id": "time_trip_deadline_1",
            "note_id": "note_trip",
            "source_note_id": "note_trip",
            "time_kind": "deadline",
            "kind_label": "마감",
            "title": "강릉 여행 준비 1차",
            "when_label": "마감 2026-06-15 00:00",
            "sort_at": "2026-06-15T00:00:00+09:00",
            "briefing_bucket": "upcoming_time_items",
            "excerpt": "준비 마감이다.",
        },
        {
            "item_type": "time_item",
            "time_item_id": "time_trip_deadline_2",
            "note_id": "note_trip",
            "source_note_id": "note_trip",
            "time_kind": "deadline",
            "kind_label": "마감",
            "title": "강릉 여행 준비 2차",
            "when_label": "마감 2026-06-16 00:00",
            "sort_at": "2026-06-16T00:00:00+09:00",
            "briefing_bucket": "upcoming_time_items",
            "excerpt": "최종 마감이다.",
        },
        {
            "item_type": "time_item",
            "time_item_id": "time_trip_event",
            "note_id": "note_trip",
            "source_note_id": "note_trip",
            "time_kind": "event",
            "kind_label": "일정",
            "title": "강릉 여행",
            "when_label": "시작 2026-06-17 00:00",
            "sort_at": "2026-06-17T00:00:00+09:00",
            "briefing_bucket": "upcoming_time_items",
            "excerpt": "여행 일정이다.",
        },
    ]

    answer = _build_answer(plan, items)
    refs = _build_answer_refs(plan, items)

    assert "오늘 처리할 일을 기준으로 1건을 찾았습니다" in answer
    assert "기준: 2026-06-14 · Asia/Seoul · 7일 이내 · 하루 요약 07:30" in answer
    assert "다가오는 예정 1건" in answer
    assert answer.count("강릉 여행") == 1
    assert "강릉 여행 준비 1차" not in answer
    assert "강릉 여행 준비 2차" not in answer
    assert "관련 세부 항목: 마감 2건" in answer
    assert {ref["time_item_id"] for ref in refs if ref.get("time_item_id")} == {
        "time_trip_deadline_1",
        "time_trip_deadline_2",
        "time_trip_event",
    }


def test_chat_search_detail_words_do_not_become_focus_terms():
    plan = _build_query_plan(
        "강릉 여행에 대해 자세히 알려줘",
        now=datetime(2026, 6, 8, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        context={
            "parent_query": "올해 남은 여행",
            "query_plan": {
                "primary_domain": "time",
                "focus_terms": ["여행"],
                "time_range": {
                    "from": "2026-06-08T10:00:00+09:00",
                    "to": "2026-12-31T23:59:59+09:00",
                    "label": "2026-06-08 10:00부터 2026-12-31 23:59까지",
                },
            },
            "items": [{"item_type": "time_item", "title": "강릉 친구 여행 후보 기간"}],
            "messages": [{"query": "올해 남은 여행", "answer": "강릉 친구 여행 후보 기간"}],
        },
    )

    assert plan["answer_intent"] == "detail_summary"
    assert plan["primary_domain"] == "time"
    assert plan["focus_match"] == "all"
    assert plan["focus_terms"] == ["강릉", "여행"]
    assert "자세히" not in plan["focus_terms"]
    assert "알려줘" not in plan["focus_terms"]
    assert "대해" not in plan["focus_terms"]


def test_chat_search_time_detail_answer_explains_group():
    plan = {
        "query": "강릉 여행에 대해 자세히 알려줘",
        "primary_domain": "time",
        "answer_intent": "detail_summary",
        "focus_terms": ["강릉", "여행"],
        "time_range": {"label": "2026-06-08 10:30부터 2026-12-31 23:59까지"},
        "context": {"applied": True},
    }
    items = [
        {
            "item_type": "time_item",
            "time_item_id": "time_gn_event",
            "note_id": "note_gn",
            "source_note_id": "note_gn",
            "source_note_title": "강릉 친구 여행 계획",
            "source_note_kind": "source",
            "original_note_id": "note_archive",
            "original_note_title": "원문 - 강릉 친구 여행 계획",
            "time_kind": "event",
            "kind_label": "일정",
            "title": "강릉 친구 여행 후보 기간",
            "when_label": "시작 2026-09-15 00:00 / 종료 2026-10-15 00:00",
            "sort_at": "2026-09-15T00:00:00+09:00",
            "excerpt": "친구들과 강릉으로 2박 3일 여행을 계획한다. 정확한 출발일과 종료일은 미정이다.",
        },
        {
            "item_type": "time_item",
            "time_item_id": "time_gn_deadline",
            "note_id": "note_gn",
            "source_note_id": "note_gn",
            "source_note_title": "강릉 친구 여행 계획",
            "time_kind": "reminder",
            "kind_label": "마감",
            "title": "강릉 여행 준비 마감",
            "when_label": "마감 2026-07-15 00:00",
            "sort_at": "2026-07-15T00:00:00+09:00",
            "excerpt": "여행 준비를 끝내야 하는 마감이다.",
        },
        {
            "item_type": "note",
            "note_id": "note_gn",
            "kind": "source",
            "kind_label": "소스",
            "title": "강릉 친구 여행 계획",
            "excerpt": "친구들과 강릉으로 2박 3일 여행을 계획한다.",
        },
    ]

    answer = _build_answer(plan, items)
    refs = _build_answer_refs(plan, items)
    ref_ids = [ref["time_item_id"] for ref in refs if ref.get("time_item_id")]
    note_refs = {ref["note_id"]: ref for ref in refs if ref.get("item_type") == "note" and ref.get("note_id")}

    assert "조건에 맞는 일정/알림" not in answer
    assert "강릉, 여행에 대해" in answer
    assert "강릉 친구 여행 후보 기간" in answer
    assert "시점:" in answer
    assert "2박 3일" in answer
    assert "관련 세부 항목" in answer
    assert "강릉 여행 준비 마감" in answer
    assert "확정 전 정보" in answer
    assert "근거 3건은 근거 버튼" in answer
    assert ref_ids[0] == "time_gn_event"
    assert "time_gn_deadline" in ref_ids
    assert note_refs["note_gn"]["title"] == "강릉 친구 여행 계획"
    assert note_refs["note_archive"]["title"] == "원문 - 강릉 친구 여행 계획"


def test_chat_search_note_detail_answer_prefers_sources_over_auxiliary_notes():
    plan = {
        "query": "강릉 여행 계획에 대해 자세히 알려줘",
        "primary_domain": "notes",
        "answer_intent": "detail_summary",
        "focus_terms": ["강릉", "여행", "계획"],
        "context": {"applied": True},
    }
    items = [
        {
            "item_type": "note",
            "note_id": "note_source",
            "kind": "source",
            "kind_label": "소스",
            "title": "강릉 친구 여행 계획",
            "excerpt": "친구들과 강릉으로 2박 3일 여행을 계획한다.",
            "tags": ["여행계획", "강릉"],
            "topics": ["강릉 여행 계획"],
            "entities": ["강원도 강릉"],
            "matched_fields": ["제목", "본문", "태그", "주제", "대상", "연결"],
            "original_note_id": "note_archive",
            "original_note_title": "원문 - 강릉 친구 여행 계획",
        },
        {
            "item_type": "note",
            "note_id": "note_topic",
            "kind": "topic",
            "kind_label": "주제",
            "title": "강릉 여행 계획",
            "excerpt": "1개의 소스 노트에서 승인된 AI 제안과 연결되어 있습니다.",
            "linked_sources": [{"note_id": "note_source", "title": "강릉 친구 여행 계획"}],
            "matched_fields": ["제목", "본문"],
        },
        {
            "item_type": "note",
            "note_id": "note_entity",
            "kind": "entity",
            "kind_label": "대상",
            "title": "강원도 강릉",
            "excerpt": "1개의 소스 노트에서 승인된 AI 제안과 연결되어 있습니다.",
            "linked_sources": [{"note_id": "note_source", "title": "강릉 친구 여행 계획"}],
            "matched_fields": ["제목", "본문"],
        },
        {
            "item_type": "note",
            "note_id": "note_archive",
            "kind": "archive",
            "kind_label": "원문",
            "title": "원문 - 강릉 친구 여행 계획",
            "excerpt": "처음 작성한 원문입니다.",
            "matched_fields": ["제목", "본문"],
        },
    ]

    answer = _build_answer(plan, items)
    refs = _build_answer_refs(plan, items)

    assert "강릉 친구 여행 계획 (소스)" in answer
    assert "강릉 여행 계획 (주제)" not in answer
    assert "강원도 강릉 (대상)" not in answer
    assert "원문 - 강릉 친구 여행 계획" not in answer
    assert "근거 4건은 근거 버튼" in answer
    assert [ref["note_id"] for ref in refs[:4]] == ["note_source", "note_archive", "note_topic", "note_entity"]


def test_chat_search_personalization_hints_boost_only_matching_query_results():
    plan = _build_query_plan(
        "구매",
        now=datetime(2026, 6, 8, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        personalization={
            "workflow_mode": "personal",
            "classification_seeds": ["재고 부족"],
            "life_categories": ["생활용품"],
            "aliases": ["치약=생활용품"],
            "priority_terms": ["구매 필요"],
            "custom_facets": ["소모품"],
            "preference_rules": ["결론 먼저"],
        },
    )
    notes = [
        {
            "id": "note_travel",
            "kind": "source",
            "status": "active",
            "title": "캠핑 구매 준비",
            "body_markdown": "캠핑 장비 목록을 정리한다.",
            "metadata": {"manual_tags": ["여행"]},
            "source_note_id": None,
            "updated_at": "2026-06-08T12:00:00+09:00",
        },
        {
            "id": "note_toothpaste",
            "kind": "source",
            "status": "active",
            "title": "치약 구매 필요",
            "body_markdown": "집에 남아있는 치약이 없다.",
            "metadata": {"manual_tags": ["생활용품", "재고 부족"]},
            "source_note_id": None,
            "updated_at": "2026-06-08T10:00:00+09:00",
        },
        {
            "id": "note_hint_only",
            "kind": "source",
            "status": "active",
            "title": "생활용품 재고",
            "body_markdown": "재고 부족 항목을 점검한다.",
            "metadata": {"manual_tags": ["생활용품"]},
            "source_note_id": None,
            "updated_at": "2026-06-08T13:00:00+09:00",
        },
    ]

    ranked = _rank_notes(notes, links=[], terms=plan["terms"], query=plan["query"], plan=plan)

    assert plan["personalization_hinting"] == {"enabled": True, "mode": "score_only"}
    assert "생활용품" not in plan["terms"]
    assert "결론 먼저" not in plan["personalization_hint_terms"]
    assert "재고" not in plan["focus_terms"]
    assert [item["note_id"] for item in ranked] == ["note_toothpaste", "note_travel"]
    assert ranked[0]["matched_personalization_hints"] == ["재고 부족", "생활용품", "치약", "구매 필요"]
    assert "note_hint_only" not in [item["note_id"] for item in ranked]


def test_chat_search_explicit_state_relation_requires_matching_state_evidence():
    plan = _build_query_plan(
        "내가 투자 중인 주식에 대해 알려줘.",
        now=datetime(2026, 6, 8, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    notes = [
        {
            "id": "note_idea",
            "kind": "source",
            "status": "active",
            "title": "QQQI 배당률",
            "body_markdown": "QQQI의 연 배당률이 약 14%라는 투자 아이디어 메모다.",
            "metadata": {"manual_tags": ["투자", "주식"]},
            "source_note_id": None,
            "updated_at": "2026-06-08T10:00:00+09:00",
        },
        {
            "id": "note_site",
            "kind": "source",
            "status": "active",
            "title": "pehelper 표준 내용 정리 아이디어",
            "body_markdown": "내가 만든 기술사 공부 사이트 pehelper의 내용을 정리한다.",
            "metadata": {},
            "source_note_id": None,
            "updated_at": "2026-06-08T11:00:00+09:00",
        },
        {
            "id": "note_holding",
            "kind": "source",
            "status": "active",
            "title": "QQQI 보유 기록",
            "body_markdown": "QQQI를 보유중이며 배당률을 관찰하고 있다.",
            "metadata": {"manual_tags": ["투자"]},
            "source_note_id": None,
            "updated_at": "2026-06-08T12:00:00+09:00",
        },
    ]

    ranked = _rank_notes(notes, links=[], terms=plan["terms"], query=plan["query"], plan=plan)
    answer = _build_answer(plan, ranked)

    assert plan["evidence_requirement"]["kind"] == "explicit_state_relation"
    assert plan["evidence_requirement"]["state_kind"] == "holding"
    assert plan["evidence_requirement"]["state_label"] == "보유/투자 중"
    assert plan["evidence_requirement"]["label"] == "투자 중인 주식"
    assert "내가" not in plan["terms"]
    assert "중인" not in plan["terms"]
    assert [item["note_id"] for item in ranked] == ["note_holding"]
    assert "QQQI 보유 기록" in answer
    assert "pehelper" not in answer
    assert "명시적 상태/관계 근거" in answer


def test_chat_search_explicit_state_relation_missing_evidence_does_not_return_related_ideas():
    plan = _build_query_plan(
        "내가 투자 중인 주식에 대해 알려줘.",
        now=datetime(2026, 6, 8, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        personalization={
            "workflow_mode": "personal",
            "classification_seeds": ["투자", "주식"],
            "life_categories": ["투자"],
        },
    )
    notes = [
        {
            "id": "note_idea",
            "kind": "source",
            "status": "active",
            "title": "QQQI 배당률",
            "body_markdown": "QQQI의 연 배당률이 약 14%라는 투자 아이디어 메모다.",
            "metadata": {"manual_tags": ["투자", "주식"]},
            "source_note_id": None,
            "updated_at": "2026-06-08T10:00:00+09:00",
        }
    ]

    ranked = _rank_notes(notes, links=[], terms=plan["terms"], query=plan["query"], plan=plan)
    answer = _build_answer(plan, ranked)

    assert ranked == []
    assert plan["personalization_hinting"] == {"enabled": True, "mode": "score_only"}
    assert "명시 조건 '투자 중인 주식'에 맞는 근거를 찾지 못했습니다" in answer
    assert "관련 아이디어나 일반 사실 메모" in answer


def test_chat_search_explicit_state_relation_supports_non_investment_queries():
    plan = _build_query_plan(
        "내가 구독 중인 서비스 알려줘",
        now=datetime(2026, 6, 8, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    notes = [
        {
            "id": "note_subscription",
            "kind": "source",
            "status": "active",
            "title": "넷플릭스 구독 기록",
            "body_markdown": "넷플릭스를 구독중이며 매달 결제한다.",
            "metadata": {"manual_tags": ["구독", "서비스"]},
            "source_note_id": None,
            "updated_at": "2026-06-08T10:00:00+09:00",
        },
        {
            "id": "note_idea",
            "kind": "source",
            "status": "active",
            "title": "스트리밍 서비스 비교",
            "body_markdown": "OTT 서비스 가격과 후보 아이디어를 비교한다.",
            "metadata": {"manual_tags": ["서비스"]},
            "source_note_id": None,
            "updated_at": "2026-06-08T11:00:00+09:00",
        },
    ]

    ranked = _rank_notes(notes, links=[], terms=plan["terms"], query=plan["query"], plan=plan)
    answer = _build_answer(plan, ranked)

    assert plan["evidence_requirement"]["kind"] == "explicit_state_relation"
    assert plan["evidence_requirement"]["state_kind"] == "subscription"
    assert plan["evidence_requirement"]["state_label"] == "구독/이용 중"
    assert [item["note_id"] for item in ranked] == ["note_subscription"]
    assert "넷플릭스 구독 기록" in answer
    assert "스트리밍 서비스 비교" not in answer


def test_chat_search_explicit_state_relation_ignores_advice_or_idea_queries():
    now = datetime(2026, 6, 8, 14, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    idea_plan = _build_query_plan("주식 투자 아이디어 보여줘", now=now)
    howto_plan = _build_query_plan("구독 방법 알려줘", now=now)

    assert idea_plan["evidence_requirement"] is None
    assert howto_plan["evidence_requirement"] is None


def test_chat_search_synthesizes_state_answer_from_conflicting_note_evidence(db_settings):
    settings = replace(db_settings, chat_answer_provider="rules")
    entity = create_note(
        {
            "kind": "entity",
            "status": "active",
            "title": "치약",
            "body_markdown": "생활용품 대상입니다.",
            "change_source": "test",
        },
        db_settings,
    )
    need_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "집에 남아있는 치약이 없다",
            "body_markdown": "집에 남아있는 치약이 없어서 새로 구매해야 한다.",
            "metadata": {
                "manual_tags": ["생활용품", "재고부족"],
                "approved_entities": [{"title": "치약", "note_id": entity["id"]}],
            },
            "change_source": "test",
        },
        db_settings,
    )
    done_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "치약 구매 완료",
            "body_markdown": "치약 물품 구매를 완료했다.",
            "metadata": {
                "manual_tags": ["생활물품"],
                "approved_entities": [{"title": "치약", "note_id": entity["id"]}],
            },
            "change_source": "test",
        },
        db_settings,
    )
    add_note_link(
        need_source["id"],
        target_text="치약",
        to_note_id=entity["id"],
        link_type="entity_suggestion",
        settings=db_settings,
    )
    add_note_link(
        done_source["id"],
        target_text="치약",
        to_note_id=entity["id"],
        link_type="entity_suggestion",
        settings=db_settings,
    )

    payload = run_chat_search(
        "집에 부족한 물품이 뭐야?",
        settings=settings,
        now=datetime(2026, 6, 8, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert payload["meta"]["query_plan"]["answer_intent"] == "state_summary"
    assert "치약" in payload["answer"]
    assert "완료" in payload["answer"] or "해결" in payload["answer"] or "해소" in payload["answer"]
    assert "근거 버튼" in payload["answer"]
    assert "관련된 근거" not in payload["answer"]
    assert any(item.get("note_id") == need_source["id"] for item in payload["items"])
    assert any(item.get("note_id") == done_source["id"] for item in payload["items"])


def test_source_delete_api_restores_original_by_default_and_can_delete_it(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        original = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "archive",
                "status": "archived",
                "title": "원문 - API 기본 복원",
                "body_markdown": "기본 삭제에서는 작성중으로 돌아갈 원문입니다.",
                "metadata": {"target_note_id": "old_source"},
            },
        )
        assert original.status_code == 200
        source = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "API 기본 복원 소스",
                "body_markdown": "소스 본문",
                "source_note_id": original.json()["id"],
            },
        )
        assert source.status_code == 200

        deleted = client.post(
            f"/api/notes/{source.json()['id']}/delete",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": source.json()["version"], "change_source": "test", "created_by": "pytest"},
        )
        assert deleted.status_code == 200
        cleanup = deleted.json()["delete_cleanup"]
        assert cleanup["source_original"]["action"] == "restored_to_inbox"
        assert cleanup["restored_original_notes"] == 1
        restored = client.get(
            f"/api/notes/{original.json()['id']}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert restored.status_code == 200
        assert restored.json()["kind"] == "inbox"
        assert restored.json()["status"] == "draft"
        assert restored.json()["title"] == "API 기본 복원"

        original_delete = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "archive",
                "status": "archived",
                "title": "원문 - API 함께 삭제",
                "body_markdown": "옵션이 켜지면 함께 삭제할 원문입니다.",
            },
        )
        assert original_delete.status_code == 200
        source_delete = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "API 함께 삭제 소스",
                "body_markdown": "소스 본문",
                "source_note_id": original_delete.json()["id"],
            },
        )
        assert source_delete.status_code == 200
        deleted_with_original = client.post(
            f"/api/notes/{source_delete.json()['id']}/delete",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": source_delete.json()["version"],
                "delete_original_note": True,
                "change_source": "test",
                "created_by": "pytest",
            },
        )
        assert deleted_with_original.status_code == 200
        cleanup_with_original = deleted_with_original.json()["delete_cleanup"]
        assert cleanup_with_original["source_original"]["action"] == "deleted_with_source"
        assert cleanup_with_original["deleted_original_notes"] == 1
        original_deleted = client.get(
            f"/api/notes/{original_delete.json()['id']}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert original_deleted.status_code == 200
        assert original_deleted.json()["status"] == "deleted"
        assert original_deleted.json()["deleted_at"] is not None
    finally:
        app.dependency_overrides.clear()


def test_note_process_reuses_active_request_after_note_is_edited(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        created = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "inbox",
                "status": "active",
                "title": "Active Request Note",
                "body_markdown": "Original body",
                "change_source": "test",
                "created_by": "pytest",
            },
        )
        assert created.status_code == 200
        note = created.json()

        process = client.post(
            f"/api/notes/{note['id']}/process",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 1},
        )
        assert process.status_code == 200
        request = process.json()
        assert request["status"] == "queued"

        updated = client.patch(
            f"/api/notes/{note['id']}",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": 1,
                "body_markdown": "Edited while queued",
                "change_source": "test",
                "created_by": "pytest",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2

        detail = client.get(f"/api/notes/{note['id']}", headers={"Authorization": "Bearer admin-token"})
        assert detail.status_code == 200
        assert detail.json()["latest_processing_request"]["id"] == request["id"]
        assert detail.json()["latest_processing_request"]["note_id"] == note["id"]
        assert detail.json()["latest_processing_request"]["source_revision_id"] == request["source_revision_id"]
        assert detail.json()["latest_processing_request"]["status"] == "queued"

        duplicate_after_edit = client.post(
            f"/api/notes/{note['id']}/process",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 2},
        )
        assert duplicate_after_edit.status_code == 200
        assert duplicate_after_edit.json()["id"] == request["id"]
    finally:
        app.dependency_overrides.clear()


def test_time_suggestion_register_api_rejects_record_only_without_side_effects(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "기록 전용 API 소스",
            "body_markdown": """
# 기록 전용 API 소스

### 일정 제안

| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 검진 완료 기록 | 기록 전용 | reminder | 2026-06-11T12:00:00+09:00 | | | | Asia/Seoul | "검진 완료" | 완료 사실만 있고 등록할 일정이 아니다. |
""",
        },
        settings,
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        suggestions = client.get(
            f"/api/notes/{source['id']}/time-suggestions",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert suggestions.status_code == 200
        item = suggestions.json()["items"][0]
        assert item["registerable"] is False

        response = client.post(
            f"/api/notes/{source['id']}/time-suggestions/register",
            headers={"Authorization": "Bearer admin-token"},
            json={"key": item["key"], "expected_version": source["version"]},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "record-only time suggestion is not an active item"
        assert list_time_items(note_id=source["id"], include_closed=True, settings=settings) == []
        with connect(settings) as conn:
            count = fetch_one(conn, "select count(*) as count from notification_deliveries")
        assert count["count"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("kind", ["source", "topic", "entity", "log"])
def test_note_api_creates_direct_web_note_kinds(db_settings, kind):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        created = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": kind,
                "status": "active",
                "title": f"Direct {kind}",
                "body_markdown": f"{kind} body",
                "metadata": {"channel": "web", "created_kind": kind},
                "change_source": "test",
                "created_by": "pytest",
            },
        )
        assert created.status_code == 200
        note = created.json()
        assert note["kind"] == kind
        assert note["status"] == "active"
        assert note["title"] == f"Direct {kind}"
        assert note["metadata"] == {"channel": "web", "created_kind": kind}

        listed = client.get(
            f"/api/notes?kind={kind}&status=active&q=Direct&limit=5",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()] == [note["id"]]

        process = client.post(
            f"/api/notes/{note['id']}/process",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": note["version"]},
        )
        assert process.status_code == 422
        assert process.json()["detail"] == "note_process_kind_not_supported"
    finally:
        app.dependency_overrides.clear()


def test_note_api_validation_errors(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        assert client.get("/api/notes/bad", headers={"Authorization": "Bearer admin-token"}).status_code == 404
        missing = client.get("/api/notes/note_missing1234", headers={"Authorization": "Bearer admin-token"})
        assert missing.status_code == 404

        invalid_kind = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={"title": "Bad Note", "kind": "folder"},
        )
        assert invalid_kind.status_code == 422
        assert "invalid kind" in invalid_kind.json()["detail"]

        invalid_status = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={"title": "Bad Status", "status": "published"},
        )
        assert invalid_status.status_code == 422
        assert "invalid status" in invalid_status.json()["detail"]

        invalid_metadata = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={"title": "Bad Metadata", "metadata": []},
        )
        assert invalid_metadata.status_code == 422
        assert invalid_metadata.json()["detail"] == "metadata must be a JSON object"

        created = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={"title": "Validation Target", "change_source": "test"},
        ).json()

        missing_version = client.patch(
            f"/api/notes/{created['id']}",
            headers={"Authorization": "Bearer admin-token"},
            json={"body_markdown": "no version"},
        )
        assert missing_version.status_code == 422
        assert missing_version.json()["detail"] == "invalid_expected_version"

        invalid_update_metadata = client.patch(
            f"/api/notes/{created['id']}",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 1, "metadata": []},
        )
        assert invalid_update_metadata.status_code == 422
        assert invalid_update_metadata.json()["detail"] == "metadata_must_be_object"
    finally:
        app.dependency_overrides.clear()


def test_note_feedback_api_creates_feedback_and_reprocess_request(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        source = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "A 방문 일정",
                "body_markdown": "# A 방문 일정\n\nA가 2026년 6월 6일 방문 예정입니다.",
                "metadata": {"channel": "web"},
            },
        )
        assert source.status_code == 200
        source_id = source.json()["id"]

        plugin = client.post(
            f"/api/notes/{source_id}/feedback",
            headers={"Authorization": "Bearer plugin-token"},
            json={"feedback_type": "change", "body_markdown": "blocked"},
        )
        assert plugin.status_code == 401

        feedback = client.post(
            f"/api/notes/{source_id}/feedback",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": source.json()["version"],
                "feedback_type": "change",
                "body_markdown": "A가 2026년 7월 1일에 놀러오기로 변경함",
            },
        )
        assert feedback.status_code == 200
        assert feedback.json()["status"] == "open"
        assert feedback.json()["note_id"] == source_id

        stale = client.post(
            f"/api/notes/{source_id}/feedback",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": 999,
                "feedback_type": "change",
                "body_markdown": "stale",
            },
        )
        assert stale.status_code == 409

        listed = client.get(
            f"/api/notes/{source_id}/feedback?include_closed=true",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == feedback.json()["id"]

        dismiss_target = client.post(
            f"/api/notes/{source_id}/feedback",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": source.json()["version"],
                "feedback_type": "low_priority",
                "body_markdown": "이번 재처리에는 쓰지 않을 피드백",
            },
        )
        assert dismiss_target.status_code == 200
        plugin_dismiss = client.post(
            f"/api/notes/{source_id}/feedback/{dismiss_target.json()['id']}/dismiss",
            headers={"Authorization": "Bearer plugin-token"},
        )
        assert plugin_dismiss.status_code == 401
        dismissed = client.post(
            f"/api/notes/{source_id}/feedback/{dismiss_target.json()['id']}/dismiss",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert dismissed.status_code == 200
        assert dismissed.json()["status"] == "dismissed"
        default_list = client.get(
            f"/api/notes/{source_id}/feedback",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert default_list.status_code == 200
        assert [row["id"] for row in default_list.json()] == [feedback.json()["id"]]
        listed_closed = client.get(
            f"/api/notes/{source_id}/feedback?include_closed=true",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert listed_closed.status_code == 200
        assert dismiss_target.json()["id"] in {row["id"] for row in listed_closed.json()}

        reprocess = client.post(
            f"/api/notes/{source_id}/feedback/reprocess",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": source.json()["version"],
                "feedback_ids": [feedback.json()["id"]],
            },
        )
        assert reprocess.status_code == 200
        payload = reprocess.json()
        assert payload["target_note_id"] == source_id
        assert payload["request"]["input_mode"] == "db-note"
        assert payload["request"]["target_note_id"] == source_id
        assert payload["request"]["note_id"] == payload["reprocess_note"]["id"]
        assert payload["feedback"][0]["status"] == "queued"
        assert get_request(payload["request"]["id"], settings)["target_note_id"] == source_id

        duplicate = client.post(
            f"/api/notes/{source_id}/feedback/reprocess",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": source.json()["version"]},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["request"]["id"] == payload["request"]["id"]

        update_status(payload["request"]["id"], "needs_sync", settings=settings)
        next_feedback = client.post(
            f"/api/notes/{source_id}/feedback",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": source.json()["version"],
                "feedback_type": "additional_info",
                "body_markdown": "이전 재처리 요청이 동기화 필요여도 새 피드백은 다시 큐에 넣을 수 있어야 함",
            },
        )
        assert next_feedback.status_code == 200
        next_reprocess = client.post(
            f"/api/notes/{source_id}/feedback/reprocess",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": source.json()["version"],
                "feedback_ids": [next_feedback.json()["id"]],
            },
        )
        assert next_reprocess.status_code == 200
        assert next_reprocess.json()["request"]["id"] != payload["request"]["id"]

        detail = client.get(f"/api/notes/{source_id}", headers={"Authorization": "Bearer admin-token"})
        assert detail.status_code == 200
        assert detail.json()["latest_target_processing_request"]["id"] == next_reprocess.json()["request"]["id"]
    finally:
        app.dependency_overrides.clear()


def test_source_note_reanalysis_api_creates_targeted_request(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        inbox = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "archive",
                "status": "archived",
                "title": "스타벅스 원본",
                "body_markdown": "오늘 스타벅스에 3만원을 충전함",
            },
        )
        assert inbox.status_code == 200
        source = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "스타벅스 충전 기록",
                "body_markdown": "# 스타벅스 충전 기록\n\n오늘이라고만 적힌 기존 분석입니다.",
                "metadata": {"channel": "web"},
                "source_note_id": inbox.json()["id"],
            },
        )
        assert source.status_code == 200
        source_id = source.json()["id"]
        feedback = client.post(
            f"/api/notes/{source_id}/feedback",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": source.json()["version"],
                "feedback_type": "correction",
                "body_markdown": "원문에 있는 충전 금액을 기준으로 다시 확인",
            },
        )
        assert feedback.status_code == 200

        plugin = client.post(
            f"/api/notes/{source_id}/reanalyze",
            headers={"Authorization": "Bearer plugin-token"},
            json={"expected_version": source.json()["version"]},
        )
        assert plugin.status_code == 401

        stale = client.post(
            f"/api/notes/{source_id}/reanalyze",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 999},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"] == "stale_note_version"

        reanalysis = client.post(
            f"/api/notes/{source_id}/reanalyze",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": source.json()["version"], "sensitivity": "private"},
        )
        assert reanalysis.status_code == 200
        payload = reanalysis.json()
        assert payload["target_note_id"] == source_id
        assert payload["request"]["source"] == "web-note-reanalysis"
        assert payload["request"]["input_mode"] == "db-note"
        assert payload["request"]["target_note_id"] == source_id
        assert payload["request"]["note_id"] == payload["reanalysis_note"]["id"]
        assert payload["request"]["source_revision_id"] == payload["source_revision"]["id"]
        assert payload["reanalysis_note"]["kind"] == "inbox"
        assert payload["reanalysis_note"]["source_note_id"] == inbox.json()["id"]
        assert payload["reanalysis_note"]["parent_id"] == source_id
        assert payload["reanalysis_note"]["metadata"]["source_reanalysis"] is True
        assert payload["reanalysis_note"]["metadata"]["reanalysis_target_note_id"] == source_id
        assert payload["reanalysis_note"]["metadata"]["reanalysis_original_note_id"] == inbox.json()["id"]
        assert payload["reanalysis_note"]["metadata"]["reanalysis_feedback_ids"] == [feedback.json()["id"]]
        reanalysis_body = payload["source_revision"]["body_markdown"]
        assert "## 재분석 지시" in reanalysis_body
        assert "## 원문" in reanalysis_body
        assert "오늘 스타벅스에 3만원을 충전함" in reanalysis_body
        assert "## 현재 소스 노트" in reanalysis_body
        assert "오늘이라고만 적힌 기존 분석입니다." in reanalysis_body
        assert "## 사용자 피드백" in reanalysis_body
        assert "원문에 있는 충전 금액을 기준으로 다시 확인" in reanalysis_body
        assert get_request(payload["request"]["id"], settings)["target_note_id"] == source_id

        visible_inbox = client.get("/api/notes?kind=inbox", headers={"Authorization": "Bearer admin-token"})
        assert visible_inbox.status_code == 200
        assert payload["reanalysis_note"]["id"] not in [row["id"] for row in visible_inbox.json()]
        internal_inbox = client.get(
            "/api/notes?kind=inbox&include_internal=true",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert internal_inbox.status_code == 200
        assert payload["reanalysis_note"]["id"] in [row["id"] for row in internal_inbox.json()]

        duplicate = client.post(
            f"/api/notes/{source_id}/reanalyze",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": source.json()["version"]},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["request"]["id"] == payload["request"]["id"]
        assert duplicate.json()["reanalysis_note"] is None

        detail = client.get(f"/api/notes/{source_id}", headers={"Authorization": "Bearer admin-token"})
        assert detail.status_code == 200
        assert detail.json()["latest_target_processing_request"]["id"] == payload["request"]["id"]

        inbox_reanalysis = client.post(
            f"/api/notes/{inbox.json()['id']}/reanalyze",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": inbox.json()["version"]},
        )
        assert inbox_reanalysis.status_code == 422
        assert inbox_reanalysis.json()["detail"] == "source_reanalysis_requires_source_note"
    finally:
        app.dependency_overrides.clear()


def test_delete_source_note_cancels_queued_targeted_request(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        source = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "Target Delete Source",
                "body_markdown": "# Target Delete Source\n\nQueued reanalysis target.",
                "metadata": {"channel": "pytest"},
            },
        )
        assert source.status_code == 200
        reanalysis = client.post(
            f"/api/notes/{source.json()['id']}/reanalyze",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": source.json()["version"]},
        )
        assert reanalysis.status_code == 200

        deleted = client.post(
            f"/api/notes/{source.json()['id']}/delete",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": source.json()["version"], "change_source": "test", "created_by": "pytest"},
        )

        assert deleted.status_code == 200
        cleanup = deleted.json()["delete_cleanup"]
        cancelled_ids = {row["id"] for row in cleanup["cancelled_processing_requests"]}
        assert reanalysis.json()["request"]["id"] in cancelled_ids
        assert get_request(reanalysis.json()["request"]["id"], settings)["status"] == "cancelled"
    finally:
        app.dependency_overrides.clear()


def test_delete_source_note_blocks_running_targeted_request(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        source = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "Running Target Delete Source",
                "body_markdown": "# Running Target Delete Source\n\nRunning reanalysis target.",
                "metadata": {"channel": "pytest"},
            },
        )
        assert source.status_code == 200
        reanalysis = client.post(
            f"/api/notes/{source.json()['id']}/reanalyze",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": source.json()["version"]},
        )
        assert reanalysis.status_code == 200
        update_status(reanalysis.json()["request"]["id"], "running", settings=settings)

        deleted = client.post(
            f"/api/notes/{source.json()['id']}/delete",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": source.json()["version"], "change_source": "test", "created_by": "pytest"},
        )

        assert deleted.status_code == 422
        assert deleted.json()["detail"] == "note_delete_processing_not_supported"
    finally:
        app.dependency_overrides.clear()


def test_note_suggestion_api_promotes_source_suggestion(db_settings, monkeypatch):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    exported_notes = []

    def fake_export_notes_to_markdown(export_settings, *, scope, note_id, dry_run, sync, push):
        exported_notes.append(
            {
                "settings": export_settings,
                "scope": scope,
                "note_id": note_id,
                "dry_run": dry_run,
                "sync": sync,
                "push": push,
            }
        )
        return {
            "job_id": "export_promoted",
            "status": "succeeded",
            "scope": scope,
            "note_id": note_id,
            "exported_count": 1,
            "changed_paths": [f"wiki/promoted/{note_id}.md"],
            "content_commit_sha": "promoted123",
            "pushed": push,
        }

    monkeypatch.setattr(api, "export_notes_to_markdown", fake_export_notes_to_markdown)
    client = TestClient(app)
    try:
        source = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "Suggestion Source",
                "body_markdown": "\n".join(
                    [
                        "# Suggestion Source",
                        "",
                        "## Related",
                        "",
                        "### Topic Suggestions",
                        "",
                        "| Candidate | Suggested path | Evidence | Review note |",
                        "| --- | --- | --- | --- |",
                        "| Climate Risk | `wiki/topics/climate-risk.md` | Source discusses weather volatility. | Promote if useful. |",
                        "",
                        "### Entity Suggestions",
                        "",
                        "| Candidate | Type | Suggested path | Evidence | Review note |",
                        "| --- | --- | --- | --- | --- |",
                        "| NOAA | organization | `wiki/entities/noaa.md` | Source names NOAA. | Promote if tracked. |",
                        "",
                        "### Tag Suggestions",
                        "",
                        "| Candidate | Evidence | Review note |",
                        "| --- | --- | --- |",
                        "| 기후 | Source discusses weather volatility. | Apply as a tag. |",
                    ]
                ),
                "metadata": {"channel": "web", "manual_tags": ["기후"]},
            },
        )
        assert source.status_code == 200
        source_id = source.json()["id"]

        plugin = client.get(
            f"/api/notes/{source_id}/suggestions",
            headers={"Authorization": "Bearer plugin-token"},
        )
        assert plugin.status_code == 401

        suggestions = client.get(
            f"/api/notes/{source_id}/suggestions",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert suggestions.status_code == 200
        assert suggestions.json()["topics"][0]["candidate"] == "Climate Risk"
        assert suggestions.json()["tags"][0]["candidate"] == "기후"
        assert suggestions.json()["tags"][0]["applied"] is True

        promoted = client.post(
            f"/api/notes/{source_id}/suggestions/promote",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": source.json()["version"],
                "kind": "topic",
                "candidate": "Climate Risk",
                "suggested_path": "wiki/topics/climate-risk.md",
            },
        )
        assert promoted.status_code == 200
        assert promoted.json()["created_note"] is True
        assert promoted.json()["note"]["kind"] == "topic"
        assert promoted.json()["note"]["slug"] == "climate-risk"
        assert "## 요약" in promoted.json()["note"]["body_markdown"]
        assert "## 검토 메모" in promoted.json()["note"]["body_markdown"]
        assert "## Summary" not in promoted.json()["note"]["body_markdown"]
        assert promoted.json()["mirror_error"] is None
        assert promoted.json()["mirror_export"]["content_commit_sha"] == "promoted123"
        assert exported_notes[-1] == {
            "settings": settings,
            "scope": "note-id",
            "note_id": promoted.json()["note"]["id"],
            "dry_run": False,
            "sync": False,
            "push": False,
        }

        promoted_again = client.post(
            f"/api/notes/{source_id}/suggestions/promote",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": promoted.json()["source_note"]["version"],
                "kind": "topic",
                "candidate": "Climate Risk",
                "suggested_path": "wiki/topics/climate-risk.md",
            },
        )
        assert promoted_again.status_code == 200
        assert promoted_again.json()["created_note"] is False
        assert promoted_again.json()["note"]["id"] == promoted.json()["note"]["id"]
        assert promoted_again.json()["mirror_error"] is None
        assert exported_notes[-1]["note_id"] == promoted.json()["note"]["id"]

        stale = client.post(
            f"/api/notes/{source_id}/suggestions/promote",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": 999,
                "kind": "topic",
                "candidate": "Climate Risk",
                "suggested_path": "wiki/topics/climate-risk.md",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"] == "stale_note_version"

        missing = client.post(
            f"/api/notes/{source_id}/suggestions/promote",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": promoted_again.json()["source_note"]["version"],
                "kind": "topic",
                "candidate": "Missing",
                "suggested_path": "wiki/topics/missing.md",
            },
        )
        assert missing.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_global_suggestions_api_lists_source_suggestions(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "제안 API 소스",
            "body_markdown": "\n".join(
                [
                    "# 제안 API 소스",
                    "",
                    "## 주제 제안",
                    "",
                    "| 후보 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- |",
                    "| 제안 모아보기 | `wiki/topics/제안-모아보기.md` | 여러 제안을 한 화면에서 검토한다. | 전역 큐 후보이다. |",
                    "",
                    "## 태그 제안",
                    "",
                    "| 후보 | 근거 | 검토 메모 |",
                    "| --- | --- | --- |",
                    "| 생산성 | 제안 검토 흐름이다. | 태그 적용 후보이다. |",
                    "| 검토 | 여러 후보를 확인한다. | 한글 후보 ID 충돌을 방지해야 한다. |",
                    "",
                    "## 일정 제안",
                    "",
                    "| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
                    "| 제안 검토 | 할 일 | task |  |  | 2026-06-07T09:00:00+09:00 | 2026-06-07T08:30:00+09:00 | Asia/Seoul | 검토가 필요하다. | 등록 가능한 일정이다. |",
                    "| 검토 완료 기록 | 기록 전용 | reminder |  |  |  |  | Asia/Seoul | 검토가 완료되었다. | 등록할 일정이 아니다. |",
                ]
            ),
        },
        settings,
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        unauthenticated = client.get("/api/suggestions")
        assert unauthenticated.status_code == 401

        response = client.get(
            "/api/suggestions?status=pending&limit=20",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response.status_code == 200
        candidates = {item["candidate"]: item for item in response.json()}
        assert candidates["제안 모아보기"]["kind"] == "topic"
        assert candidates["제안 모아보기"]["source_note_id"] == source["id"]
        assert candidates["제안 모아보기"]["source_note_version"] == source["version"]
        assert candidates["제안 모아보기"]["status"] == "pending"
        assert candidates["생산성"]["kind"] == "tag"
        assert candidates["생산성"]["suggestion_key"] == "생산성"
        assert candidates["제안 검토"]["kind"] == "time"
        assert candidates["제안 검토"]["time_intent"] == "task"
        assert "검토 완료 기록" not in candidates
        tag_ids = [item["id"] for item in response.json() if item["kind"] == "tag"]
        assert len(tag_ids) == len(set(tag_ids))

        done_response = client.get(
            "/api/suggestions?status=done&limit=20",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert done_response.status_code == 200
        done_candidates = {item["candidate"]: item for item in done_response.json()}
        assert done_candidates["검토 완료 기록"]["kind"] == "time"
        assert done_candidates["검토 완료 기록"]["time_intent"] == "record"
        assert done_candidates["검토 완료 기록"]["registerable"] is False

        dismissed = client.post(
            "/api/suggestions/dismiss",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "source_note_id": source["id"],
                "kind": "tag",
                "suggestion_key": candidates["생산성"]["suggestion_key"],
                "expected_version": source["version"],
            },
        )
        assert dismissed.status_code == 200
        assert dismissed.json()["decision"]["status"] == "dismissed"

        pending_after_dismiss = client.get(
            "/api/suggestions?status=pending&limit=20",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert pending_after_dismiss.status_code == 200
        assert "생산성" not in {item["candidate"] for item in pending_after_dismiss.json()}

        dismissed_list = client.get(
            "/api/suggestions?status=dismissed&limit=20",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert dismissed_list.status_code == 200
        dismissed_candidates = {item["candidate"]: item for item in dismissed_list.json()}
        assert dismissed_candidates["생산성"]["status"] == "dismissed"
        assert dismissed_candidates["생산성"]["status_label"] == "거절됨"

        restored = client.post(
            "/api/suggestions/restore",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "source_note_id": source["id"],
                "kind": "tag",
                "suggestion_key": candidates["생산성"]["suggestion_key"],
            },
        )
        assert restored.status_code == 200
        assert restored.json()["restored"] is True

        pending_after_restore = client.get(
            "/api/suggestions?status=pending&limit=20",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert pending_after_restore.status_code == 200
        assert "생산성" in {item["candidate"] for item in pending_after_restore.json()}
    finally:
        app.dependency_overrides.clear()


def test_global_suggestions_bulk_actions(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "제안 일괄 처리 소스",
            "body_markdown": "\n".join(
                [
                    "# 제안 일괄 처리 소스",
                    "",
                    "## 주제 제안",
                    "",
                    "| 후보 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- |",
                    "| 일괄 승인 | `wiki/topics/일괄-승인.md` | 여러 제안을 한 번에 처리한다. | 주제 승인 후보이다. |",
                    "",
                    "## 태그 제안",
                    "",
                    "| 후보 | 근거 | 검토 메모 |",
                    "| --- | --- | --- |",
                    "| 자동화 | 반복 처리를 줄인다. | 태그 승인 후보이다. |",
                    "| 정리 | 처리 후 목록을 정리한다. | 거절 복원 후보이다. |",
                ]
            ),
        },
        settings,
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin-token"}
    try:
        listed = client.get("/api/suggestions?status=pending&limit=20", headers=headers)
        assert listed.status_code == 200
        candidates = {item["candidate"]: item for item in listed.json()}

        dismissed = client.post(
            "/api/suggestions/bulk",
            headers=headers,
            json={
                "action": "dismiss",
                "items": [
                    {
                        "source_note_id": source["id"],
                        "kind": "tag",
                        "suggestion_key": candidates["정리"]["suggestion_key"],
                        "expected_version": source["version"],
                    }
                ],
            },
        )
        assert dismissed.status_code == 200
        assert dismissed.json()["succeeded"] == 1
        assert dismissed.json()["failed"] == 0

        dismissed_list = client.get("/api/suggestions?status=dismissed&limit=20", headers=headers)
        assert dismissed_list.status_code == 200
        assert "정리" in {item["candidate"] for item in dismissed_list.json()}

        restored = client.post(
            "/api/suggestions/bulk",
            headers=headers,
            json={
                "action": "restore",
                "items": [
                    {
                        "source_note_id": source["id"],
                        "kind": "tag",
                        "suggestion_key": candidates["정리"]["suggestion_key"],
                    }
                ],
            },
        )
        assert restored.status_code == 200
        assert restored.json()["succeeded"] == 1

        approved = client.post(
            "/api/suggestions/bulk",
            headers=headers,
            json={
                "action": "approve",
                "items": [
                    {
                        "source_note_id": source["id"],
                        "kind": "tag",
                        "suggestion_key": candidates["자동화"]["suggestion_key"],
                        "expected_version": source["version"],
                    },
                    {
                        "source_note_id": source["id"],
                        "kind": "topic",
                        "suggestion_key": candidates["일괄 승인"]["suggestion_key"],
                        "expected_version": source["version"],
                    },
                ],
            },
        )
        assert approved.status_code == 200
        payload = approved.json()
        assert payload["succeeded"] == 2
        assert payload["failed"] == 0

        source_detail = client.get(f"/api/notes/{source['id']}", headers=headers)
        assert source_detail.status_code == 200
        assert "자동화" in source_detail.json()["metadata"]["manual_tags"]

        done = client.get("/api/suggestions?status=done&limit=20", headers=headers)
        assert done.status_code == 200
        done_candidates = {item["candidate"]: item for item in done.json()}
        assert done_candidates["자동화"]["status"] == "done"
        assert done_candidates["일괄 승인"]["status"] == "done"
        assert done_candidates["일괄 승인"]["promoted_note_id"]
    finally:
        app.dependency_overrides.clear()


def test_home_summary_api_collects_personal_work_items(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    update_personalization_settings({"default_schedule_days": 2}, settings)
    today_due = datetime.now(ZoneInfo("Asia/Seoul")).replace(hour=18, minute=0, second=0, microsecond=0)
    today_reminder = today_due.replace(hour=17, minute=30)
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "홈 요약 소스",
            "body_markdown": "\n".join(
                [
                    "# 홈 요약 소스",
                    "",
                    "## 주제 제안",
                    "",
                    "| 후보 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- |",
                    "| 홈 화면 개선 | `wiki/topics/홈-화면-개선.md` | 작업을 한 곳에서 본다. | 개인 홈 후보이다. |",
                ]
            ),
        },
        settings,
    )
    draft = create_note(
        {
            "kind": "inbox",
            "status": "draft",
            "title": "작성중 홈 노트",
            "body_markdown": "나중에 정리할 메모",
        },
        settings,
    )
    stale_draft = create_note(
        {
            "kind": "inbox",
            "status": "draft",
            "title": "오래된 작성중 홈 노트",
            "body_markdown": "며칠째 정리하지 않은 메모",
        },
        settings,
    )
    item = create_time_item(
        {
            "note_id": source["id"],
            "source_note_id": source["id"],
            "kind": "task",
            "status": "active",
            "title": "홈 화면 검토",
            "body_markdown": "개인 홈 요약 확인",
            "due_at": today_due.isoformat(),
            "remind_at": today_reminder.isoformat(),
            "notification_channels": ["pwa"],
        },
        settings,
    )
    future_within = create_time_item(
        {
            "note_id": source["id"],
            "source_note_id": source["id"],
            "kind": "event",
            "status": "active",
            "title": "설정 범위 안 일정",
            "start_at": (today_due + timedelta(days=2)).isoformat(),
            "notification_channels": ["pwa"],
        },
        settings,
    )
    future_outside = create_time_item(
        {
            "note_id": source["id"],
            "source_note_id": source["id"],
            "kind": "event",
            "status": "active",
            "title": "설정 범위 밖 일정",
            "start_at": (today_due + timedelta(days=3)).isoformat(),
            "notification_channels": ["pwa"],
        },
        settings,
    )
    failed_request = create_request(
        {
            "id": "req_home_failed",
            "source": "web",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": source["id"],
        },
        settings,
    )
    update_status(failed_request["id"], "failed", error_message="홈 요약 테스트 실패", settings=settings)
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update notes set updated_at = now() - interval '5 days' where id = %s",
                (stale_draft["id"],),
            )
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values (
                  'ntf_home_failed1234',
                  %s,
                  'pwa',
                  'failed',
                  %s,
                  '{"title": "홈 알림", "body": "홈 화면 검토"}'::jsonb
                )
                """,
                (item["id"], today_reminder.isoformat()),
            )
            cur.execute(
                """
                update notification_deliveries
                   set created_at = now() - interval '5 days'
                 where id = 'ntf_home_failed1234'
                """
            )
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                select
                  'ntf_home_newer_' || lpad(seq::text, 4, '0'),
                  null,
                  'pwa',
                  'queued',
                  %s,
                  '{"title": "홈 알림", "body": "최신 정상 알림"}'::jsonb
                from generate_series(1, 200) as seq
                """,
                (today_reminder.isoformat(),),
            )
        conn.commit()

    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        unauthenticated = client.get("/api/home/summary")
        assert unauthenticated.status_code == 401

        response = client.get("/api/home/summary", headers={"Authorization": "Bearer admin-token"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["counts"]["pending_suggestions"] >= 1
        assert payload["counts"]["active_time_items"] >= 1
        assert payload["counts"]["failed_notifications"] >= 1
        assert payload["counts"]["failed_processing_requests"] >= 1
        assert payload["counts"]["draft_notes"] >= 1
        assert payload["counts"]["stale_draft_notes"] >= 1
        assert payload["counts"]["priority_items"] >= 1
        assert payload["today"]["counts"]["failed_processing_requests"] >= 1
        assert payload["today"]["counts"]["stale_draft_notes"] >= 1
        assert payload["stale_draft_days"] == 3
        assert payload["pending_suggestions"][0]["candidate"] == "홈 화면 개선"
        assert payload["active_time_items"][0]["title"] == "홈 화면 검토"
        assert payload["failed_notifications"][0]["id"] == "ntf_home_failed1234"
        assert payload["today"]["date"] == today_due.date().isoformat()
        assert payload["today"]["timezone"] == "Asia/Seoul"
        assert payload["today"]["upcoming_days"] == 2
        assert payload["today"]["counts"]["today_time_items"] >= 1
        assert payload["counts"]["upcoming_time_items"] >= 1
        assert payload["today"]["today_time_items"][0]["title"] == "홈 화면 검토"
        upcoming_ids = {item["id"] for item in payload["today"]["upcoming_time_items"]}
        assert future_within["id"] in upcoming_ids
        assert future_outside["id"] not in upcoming_ids
        top_level_upcoming_ids = {item["id"] for item in payload["upcoming_time_items"]}
        assert future_within["id"] in top_level_upcoming_ids
        assert future_outside["id"] not in top_level_upcoming_ids
        assert payload["today"]["pending_suggestions"][0]["candidate"] == "홈 화면 개선"
        assert payload["failed_processing_requests"][0]["id"] == "req_home_failed"
        assert payload["today"]["failed_processing_requests"][0]["id"] == "req_home_failed"
        assert payload["today"]["failed_processing_requests"][0]["error_message"] == "홈 요약 테스트 실패"
        assert payload["priority_items"] == payload["today"]["priority_items"]
        assert payload["priority_items"][0]["bucket"] == "failed_processing_requests"
        assert payload["priority_items"][0]["item_type"] == "processing_request"
        assert payload["priority_items"][0]["item"]["id"] == "req_home_failed"
        priority_buckets = [item["bucket"] for item in payload["priority_items"]]
        assert "today_time_items" in priority_buckets
        assert "pending_suggestions" in priority_buckets
        assert "stale_draft_notes" in priority_buckets
        assert draft["id"] in {note["id"] for note in payload["draft_notes"]}
        assert stale_draft["id"] in {note["id"] for note in payload["stale_draft_notes"]}
        assert stale_draft["id"] in {note["id"] for note in payload["today"]["stale_draft_notes"]}
        assert stale_draft["id"] not in {note["id"] for note in payload["today"]["draft_notes"]}
        assert draft["id"] in {note["id"] for note in payload["today"]["draft_notes"]}
        assert source["id"] in {note["id"] for note in payload["recent_notes"]}
    finally:
        app.dependency_overrides.clear()


def test_notes_api_filters_stale_drafts(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    recent = create_note(
        {
            "kind": "inbox",
            "status": "draft",
            "title": "최근 작성중 노트",
            "body_markdown": "최근에 수정한 작성중 노트",
        },
        settings,
    )
    stale = create_note(
        {
            "kind": "inbox",
            "status": "draft",
            "title": "오래된 작성중 필터 노트",
            "body_markdown": "오래 방치된 작성중 노트",
        },
        settings,
    )
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "오래된 소스 노트",
            "body_markdown": "작성중이 아니므로 오래되어도 제외되어야 한다.",
        },
        settings,
    )
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update notes set updated_at = now() - interval '5 days' where id in (%s, %s)",
                (stale["id"], source["id"]),
            )
        conn.commit()

    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        response = client.get(
            "/api/notes?stale_drafts=true&limit=20",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response.status_code == 200
        ids = {note["id"] for note in response.json()}
        assert stale["id"] in ids
        assert recent["id"] not in ids
        assert source["id"] not in ids

        filtered = client.get(
            "/api/notes",
            params={"stale_drafts": "true", "q": "오래된 작성중", "limit": "20"},
            headers={"Authorization": "Bearer admin-token"},
        )
        assert filtered.status_code == 200
        assert [note["id"] for note in filtered.json()] == [stale["id"]]
    finally:
        app.dependency_overrides.clear()


def test_classification_change_suggestion_api_applies_and_lists_done(db_settings, monkeypatch):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    monkeypatch.setattr(
        api,
        "export_notes_to_markdown",
        lambda *args, **kwargs: {
            "job_id": "export_classification",
            "status": "succeeded",
            "scope": kwargs.get("scope"),
            "note_id": kwargs.get("note_id"),
            "changed_paths": ["wiki/sources/source.md"],
            "content_commit_sha": "classification123",
            "pushed": True,
        },
    )
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "분류 변경 API 소스",
            "body_markdown": "\n".join(
                [
                    "# 분류 변경 API 소스",
                    "",
                    "## 관련",
                    "",
                    "### 분류 변경 제안",
                    "",
                    "| 동작 | 분류 | 현재 값 | 변경 값 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                    "| 추가 | 태그 |  | 예약 |  | 사용자가 예약 메모라고 피드백했다. | 태그를 추가한다. |",
                ]
            ),
            "metadata": {},
        },
        settings,
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        pending = client.get(
            "/api/suggestions?kind=classification_change&status=pending&limit=20",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert pending.status_code == 200
        assert len(pending.json()) == 1
        item = pending.json()[0]
        assert item["candidate"] == "태그 추가: 예약"
        assert item["suggestion_type_label"] == "분류 변경"

        applied = client.post(
            f"/api/notes/{source['id']}/classification-changes/apply",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": source["version"],
                "suggestion_key": item["suggestion_key"],
            },
        )
        assert applied.status_code == 200
        assert applied.json()["source_note"]["metadata"]["manual_tags"] == ["예약"]
        assert applied.json()["mirror_error"] is None
        assert applied.json()["mirror_export"]["scope"] == "changed-notes"

        done = client.get(
            "/api/suggestions?kind=classification_change&status=done&limit=20",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert done.status_code == 200
        assert done.json()[0]["status"] == "done"
    finally:
        app.dependency_overrides.clear()


def test_global_suggestions_treats_existing_target_link_as_done(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    topic = create_note(
        {
            "kind": "topic",
            "status": "active",
            "title": "Dividend yield",
            "slug": "배당률",
            "body_markdown": "Existing topic page",
        },
        settings,
    )
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "QQQI 배당률",
            "body_markdown": "\n".join(
                [
                    "# QQQI 배당률",
                    "",
                    "## Related",
                    "",
                    "### Topic Suggestions",
                    "",
                    "| Candidate | Suggested path | Evidence | Review note |",
                    "| --- | --- | --- | --- |",
                    "| 배당률 | `wiki/topics/배당률.md` | 연 배당율 | Candidate label changed after approval. |",
                ]
            ),
        },
        settings,
    )
    add_note_link(
        source["id"],
        target_text="Dividend yield",
        to_note_id=topic["id"],
        link_type="topic_suggestion",
        settings=settings,
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        pending = client.get(
            "/api/suggestions?status=pending&q=%EB%B0%B0%EB%8B%B9%EB%A5%A0&limit=20",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert pending.status_code == 200
        assert pending.json() == []

        done = client.get(
            "/api/suggestions?status=done&q=%EB%B0%B0%EB%8B%B9%EB%A5%A0&limit=20",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert done.status_code == 200
        assert len(done.json()) == 1
        assert done.json()[0]["candidate"] == "배당률"
        assert done.json()[0]["status"] == "done"
        assert done.json()[0]["promoted_note_id"] == topic["id"]
    finally:
        app.dependency_overrides.clear()


def test_note_delete_cancels_related_items_requeues_supported_references_and_deletes_orphans(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "삭제 대상 소스",
            "body_markdown": "일정과 주제를 만든 소스입니다.",
        },
        settings,
    )
    other_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "남은 소스",
            "body_markdown": "같은 주제를 계속 뒷받침하는 다른 소스입니다.",
        },
        settings,
    )
    topic = create_note(
        {
            "kind": "topic",
            "status": "active",
            "title": "삭제 출처 주제",
            "body_markdown": "이 주제는 삭제할 소스에서 만들어졌습니다.",
            "metadata": {"promoted_from_source_note_id": source["id"]},
            "source_note_id": source["id"],
        },
        settings,
    )
    add_note_link(
        source["id"],
        target_text="삭제 출처 주제",
        to_note_id=topic["id"],
        link_type="topic_suggestion",
        settings=settings,
    )
    add_note_link(
        other_source["id"],
        target_text="삭제 출처 주제",
        to_note_id=topic["id"],
        link_type="topic_suggestion",
        settings=settings,
    )
    entity = create_note(
        {
            "kind": "entity",
            "status": "active",
            "title": "고아 대상",
            "body_markdown": "삭제할 소스만 근거로 가진 대상입니다.",
            "metadata": {"promoted_from_source_note_id": source["id"]},
            "source_note_id": source["id"],
        },
        settings,
    )
    add_note_link(
        source["id"],
        target_text="고아 대상",
        to_note_id=entity["id"],
        link_type="entity_suggestion",
        settings=settings,
    )
    item = create_time_item(
        {
            "note_id": source["id"],
            "source_note_id": source["id"],
            "source_suggestion_key": "delete-source-event",
            "kind": "event",
            "status": "active",
            "title": "삭제 소스 일정",
            "body_markdown": "삭제 시 취소되어야 합니다.",
            "start_at": "2026-07-01T10:00:00+09:00",
            "remind_at": "2026-07-01T09:00:00+09:00",
            "notification_channels": ["pwa"],
        },
        settings,
    )
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values (
                  'ntf_delete_note_linked1234',
                  %s,
                  'pwa',
                  'queued',
                  '2026-07-01T09:00:00+09:00',
                  '{}'::jsonb
                )
                """,
                (item["id"],),
            )
        conn.commit()
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        deleted = client.post(
            f"/api/notes/{source['id']}/delete",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": source["version"], "change_source": "test", "created_by": "pytest"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "deleted"
        cleanup = deleted.json()["delete_cleanup"]
        assert cleanup["cancelled_time_items"] == 1
        assert cleanup["cancelled_notification_deliveries"] == 1
        assert cleanup["review_notes"] == 1
        assert cleanup["deleted_generated_notes"] == 1
        assert cleanup["reanalysis_source_note_ids"] == [other_source["id"]]
        assert cleanup["queued_reanalysis_requests"] == 1
        assert cleanup["auto_reanalysis_requests"][0]["source_note_id"] == other_source["id"]
        assert cleanup["auto_reanalysis_requests"][0]["status"] == "queued"

        with connect(settings) as conn:
            time_row = fetch_one(conn, "select status, metadata from time_items where id = %s", (item["id"],))
            delivery_row = fetch_one(
                conn,
                "select status, error_message from notification_deliveries where id = 'ntf_delete_note_linked1234'",
            )
            topic_row = fetch_one(conn, "select status, metadata from notes where id = %s", (topic["id"],))
            entity_row = fetch_one(conn, "select status, deleted_at, metadata from notes where id = %s", (entity["id"],))
            reanalysis_request = fetch_one(
                conn,
                "select id, source, status, target_note_id from processing_requests where target_note_id = %s",
                (other_source["id"],),
            )
        assert time_row["status"] == "cancelled"
        assert time_row["metadata"]["cancelled_by"] == "note_delete"
        assert delivery_row["status"] == "cancelled"
        assert topic_row["status"] == "needs_review"
        assert topic_row["metadata"]["review_reason"] == "source_note_deleted"
        assert topic_row["metadata"]["review_source_note_id"] == source["id"]
        assert topic_row["metadata"]["auto_reanalysis_status"] == "queued"
        assert topic_row["metadata"]["remaining_source_note_ids"] == [other_source["id"]]
        assert entity_row["status"] == "deleted"
        assert entity_row["deleted_at"] is not None
        assert entity_row["metadata"]["deleted_reason"] == "no_remaining_source_links"
        assert reanalysis_request["source"] == "source-delete-auto-reanalysis"
        assert reanalysis_request["status"] == "queued"
        assert reanalysis_request["target_note_id"] == other_source["id"]
    finally:
        app.dependency_overrides.clear()


def test_note_suggestion_promotion_keeps_db_change_when_mirror_export_fails(db_settings, monkeypatch):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings

    def failing_export_notes_to_markdown(export_settings, *, scope, note_id, dry_run, sync, push):
        raise RuntimeError("mirror unavailable")

    monkeypatch.setattr(api, "export_notes_to_markdown", failing_export_notes_to_markdown)
    client = TestClient(app)
    try:
        source = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "Mirror Failure Source",
                "body_markdown": "\n".join(
                    [
                        "# Mirror Failure Source",
                        "",
                        "## Related",
                        "",
                        "### Entity Suggestions",
                        "",
                        "| Candidate | Type | Suggested path | Evidence | Review note |",
                        "| --- | --- | --- | --- | --- |",
                        "| OpenAI | organization | `wiki/entities/openai.md` | Source names OpenAI. | Promote if useful. |",
                    ]
                ),
                "metadata": {"channel": "web"},
            },
        )
        assert source.status_code == 200

        promoted = client.post(
            f"/api/notes/{source.json()['id']}/suggestions/promote",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": source.json()["version"],
                "kind": "entity",
                "candidate": "OpenAI",
                "suggested_path": "wiki/entities/openai.md",
            },
        )
        assert promoted.status_code == 200
        assert promoted.json()["created_note"] is True
        assert promoted.json()["note"]["kind"] == "entity"
        assert promoted.json()["mirror_export"] is None
        assert promoted.json()["mirror_error"] == "mirror unavailable"

        target = client.get(
            f"/api/notes/{promoted.json()['note']['id']}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert target.status_code == 200
        assert target.json()["slug"] == "openai"
    finally:
        app.dependency_overrides.clear()


def test_note_suggestion_promotion_treats_mirror_permission_error_as_export_failure(db_settings, monkeypatch):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings

    def permission_denied_export(export_settings, *, scope, note_id, dry_run, sync, push):
        raise PermissionError("permission denied: mirror path")

    monkeypatch.setattr(api, "export_notes_to_markdown", permission_denied_export)
    client = TestClient(app)
    try:
        source = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "Mirror Permission Source",
                "body_markdown": "\n".join(
                    [
                        "# Mirror Permission Source",
                        "",
                        "## Related",
                        "",
                        "### Topic Suggestions",
                        "",
                        "| Candidate | Suggested path | Evidence | Review note |",
                        "| --- | --- | --- | --- |",
                        "| Mirror Permission | `wiki/topics/mirror-permission.md` | Mirror directory is not writable. | Promotion must still succeed. |",
                    ]
                ),
                "metadata": {"channel": "web"},
            },
        )
        assert source.status_code == 200

        promoted = client.post(
            f"/api/notes/{source.json()['id']}/suggestions/promote",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "expected_version": source.json()["version"],
                "kind": "topic",
                "candidate": "Mirror Permission",
                "suggested_path": "wiki/topics/mirror-permission.md",
            },
        )
        assert promoted.status_code == 200
        assert promoted.json()["created_note"] is True
        assert promoted.json()["mirror_export"] is None
        assert promoted.json()["mirror_error"] == "permission denied: mirror path"
    finally:
        app.dependency_overrides.clear()


def test_note_export_api_uses_admin_scope_and_note_id(db_settings, monkeypatch):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    captured = {}

    def fake_export_notes_to_markdown(export_settings, *, scope, note_id, dry_run, sync, push):
        captured.update(
            {
                "settings": export_settings,
                "scope": scope,
                "note_id": note_id,
                "dry_run": dry_run,
                "sync": sync,
                "push": push,
            }
        )
        return {
            "job_id": "export_test",
            "status": "succeeded",
            "scope": scope,
            "note_id": note_id,
            "exported_count": 1,
            "changed_paths": ["wiki/sources/export-me.md"],
            "content_commit_sha": "abc123",
            "pushed": push,
        }

    monkeypatch.setattr(api, "export_notes_to_markdown", fake_export_notes_to_markdown)
    client = TestClient(app)
    try:
        created = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "Export Me",
                "body_markdown": "Body",
                "change_source": "test",
                "created_by": "pytest",
            },
        )
        assert created.status_code == 200
        note = created.json()

        inbox = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "inbox",
                "status": "active",
                "title": "Raw Inbox",
                "body_markdown": "AI 처리 전 원본",
                "change_source": "test",
                "created_by": "pytest",
            },
        )
        assert inbox.status_code == 200
        inbox_export = client.post(
            f"/api/notes/{inbox.json()['id']}/export",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": inbox.json()["version"]},
        )
        assert inbox_export.status_code == 422
        assert inbox_export.json()["detail"] == "note_export_kind_not_supported"
        assert captured == {}

        plugin = client.post(
            f"/api/notes/{note['id']}/export",
            headers={"Authorization": "Bearer plugin-token"},
            json={},
        )
        assert plugin.status_code == 401

        exported = client.post(
            f"/api/notes/{note['id']}/export",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": note["version"]},
        )
        assert exported.status_code == 200
        assert exported.json()["changed_paths"] == ["wiki/sources/export-me.md"]
        assert captured == {
            "settings": settings,
            "scope": "note-id",
            "note_id": note["id"],
            "dry_run": False,
            "sync": False,
            "push": False,
        }

        stale = client.post(
            f"/api/notes/{note['id']}/export",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": note["version"] + 1},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"] == "stale_note_version"

        missing = client.post(
            "/api/notes/note_missing1234/export",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": 1},
        )
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_note_export_status_api_returns_latest_job(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        created = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "source",
                "status": "active",
                "title": "Export Status",
                "body_markdown": "Body",
                "change_source": "test",
            },
        )
        assert created.status_code == 200
        note = created.json()

        no_job = client.get(
            f"/api/notes/{note['id']}/export/status",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert no_job.status_code == 200
        assert no_job.json() == {"note_id": note["id"], "latest_export_job": None}

        first = create_export_job(scope="note-id", note_id=note["id"], settings=settings)
        update_export_job(first["id"], status="succeeded", content_commit_sha="old", settings=settings)
        second = create_export_job(scope="note-id", note_id=note["id"], settings=settings)
        update_export_job(second["id"], status="succeeded", content_commit_sha="new", settings=settings)

        status = client.get(
            f"/api/notes/{note['id']}/export/status",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert status.status_code == 200
        payload = status.json()
        assert payload["note_id"] == note["id"]
        assert payload["latest_export_job"]["id"] == second["id"]
        assert payload["latest_export_job"]["status"] == "succeeded"
        assert payload["latest_export_job"]["content_commit_sha"] == "new"

        plugin = client.get(
            f"/api/notes/{note['id']}/export/status",
            headers={"Authorization": "Bearer plugin-token"},
        )
        assert plugin.status_code == 401

        missing = client.get(
            "/api/notes/note_missing1234/export/status",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_note_attachment_upload_and_list_use_admin_scope(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        api_admin_token="admin-token",
        api_plugin_token="plugin-token",
        max_attachment_bytes=1024,
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    captured = {}

    def fake_upload_bytes(data, *, file_name, content_type, prefix, settings):
        captured.update(
            {
                "data": data,
                "file_name": file_name,
                "content_type": content_type,
                "prefix": prefix,
                "settings": settings,
            }
        )
        return {
            "id": "att_fake",
            "bucket": settings.s3_bucket,
            "object_key": f"{prefix}/fake-asset.txt",
            "object_ref": f"s3://{settings.s3_bucket}/{prefix}/fake-asset.txt",
            "file_name": file_name,
            "content_type": content_type,
            "size_bytes": len(data),
            "sha256": "abc123",
        }

    monkeypatch.setattr(api, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(
        api,
        "get_object_bytes",
        lambda key, settings: (b"downloaded", {"content_type": "text/plain", "size_bytes": 10}),
    )
    client = TestClient(app)
    try:
        created = client.post(
            "/api/notes",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "kind": "inbox",
                "status": "active",
                "title": "Attachment Note",
                "body_markdown": "Body",
                "change_source": "test",
                "created_by": "pytest",
            },
        )
        assert created.status_code == 200
        note = created.json()

        plugin_list = client.get(
            f"/api/notes/{note['id']}/attachments",
            headers={"Authorization": "Bearer plugin-token"},
        )
        assert plugin_list.status_code == 401

        empty = client.get(
            f"/api/notes/{note['id']}/attachments",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert empty.status_code == 200
        assert empty.json() == []

        plugin_upload = client.post(
            f"/api/notes/{note['id']}/attachments/upload",
            headers={"Authorization": "Bearer plugin-token"},
            files={"file": ("asset.txt", b"hello", "text/plain")},
        )
        assert plugin_upload.status_code == 401

        uploaded = client.post(
            f"/api/notes/{note['id']}/attachments/upload",
            headers={"Authorization": "Bearer admin-token"},
            files={"file": ("asset.txt", b"hello", "text/plain")},
        )
        assert uploaded.status_code == 200
        asset = uploaded.json()
        assert asset["note_id"] == note["id"]
        assert asset["file_name"] == "asset.txt"
        assert asset["content_type"] == "text/plain"
        assert asset["size_bytes"] == 5
        assert asset["object_key"] == f"assets/notes/{note['id']}/fake-asset.txt"
        assert asset["object_ref"] == f"s3://{settings.s3_bucket}/assets/notes/{note['id']}/fake-asset.txt"
        assert asset["download_url"] == f"/api/notes/{note['id']}/attachments/{asset['id']}/download"
        assert captured == {
            "data": b"hello",
            "file_name": "asset.txt",
            "content_type": "text/plain",
            "prefix": f"assets/notes/{note['id']}",
            "settings": settings,
        }

        listed = client.get(
            f"/api/notes/{note['id']}/attachments",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()] == [asset["id"]]
        assert listed.json()[0]["download_url"] == asset["download_url"]

        plugin_download = client.get(
            asset["download_url"],
            headers={"Authorization": "Bearer plugin-token"},
        )
        assert plugin_download.status_code == 401

        downloaded = client.get(
            asset["download_url"],
            headers={"Authorization": "Bearer admin-token"},
        )
        assert downloaded.status_code == 200
        assert downloaded.content == b"downloaded"
        assert downloaded.headers["content-type"].startswith("text/plain")
        assert "filename*=UTF-8''asset.txt" in downloaded.headers["content-disposition"]

        archived = client.post(
            f"/api/notes/{note['id']}/archive",
            headers={"Authorization": "Bearer admin-token"},
            json={"expected_version": note["version"], "change_source": "test"},
        )
        assert archived.status_code == 200
        blocked = client.post(
            f"/api/notes/{note['id']}/attachments/upload",
            headers={"Authorization": "Bearer admin-token"},
            files={"file": ("after.txt", b"blocked", "text/plain")},
        )
        assert blocked.status_code == 422
        assert blocked.json()["detail"] == "note_attachment_status_not_supported"
    finally:
        app.dependency_overrides.clear()


def test_note_api_auth_scopes_before_db(monkeypatch, tmp_path: Path):
    settings = _settings(
        tmp_path,
        admin_token="admin-token",
        plugin_token="plugin-token",
        api_token="legacy-token",
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    monkeypatch.setattr(api, "list_notes", lambda **kwargs: [{"id": "note_auth_ok"}])
    monkeypatch.setattr(api, "get_note", lambda note_id, settings: {"id": note_id, "status": "active"})
    monkeypatch.setattr(api, "list_note_assets", lambda note_id, settings: [])
    monkeypatch.setattr(api, "list_chat_sessions", lambda **kwargs: [{"id": "chat_auth_ok", "turns": []}])
    monkeypatch.setattr(api, "get_chat_session", lambda session_id, settings: {"id": session_id, "turns": []})
    monkeypatch.setattr(api, "delete_chat_session", lambda session_id, settings: {"id": session_id})
    client = TestClient(app)
    try:
        assert client.get("/api/notes").status_code == 401
        assert client.get("/api/notes", headers={"Authorization": "Bearer plugin-token"}).status_code == 401
        assert client.get("/api/notes", headers={"Authorization": "Bearer admin-token"}).status_code == 200
        assert client.get("/api/notes", headers={"Authorization": "Bearer legacy-token"}).status_code == 200
        assert client.get("/api/chat/sessions").status_code == 401
        assert client.get("/api/chat/sessions", headers={"Authorization": "Bearer plugin-token"}).status_code == 401
        assert client.get("/api/chat/sessions", headers={"Authorization": "Bearer admin-token"}).status_code == 200
        assert client.get(
            "/api/chat/sessions/chat_auth_ok",
            headers={"Authorization": "Bearer admin-token"},
        ).status_code == 200
        assert client.delete(
            "/api/chat/sessions/chat_auth_ok",
            headers={"Authorization": "Bearer admin-token"},
        ).status_code == 200
        assert (
            client.get(
                "/api/notes/note_auth_ok/attachments",
                headers={"Authorization": "Bearer plugin-token"},
            ).status_code
            == 401
        )
        attachments = client.get(
            "/api/notes/note_auth_ok/attachments",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert attachments.status_code == 200
        assert attachments.json() == []
    finally:
        app.dependency_overrides.clear()


def _settings(
    tmp_path: Path,
    *,
    admin_token: str | None = None,
    plugin_token: str | None = None,
    api_token: str | None = None,
) -> Settings:
    return Settings(
        database_url="postgresql://unused",
        api_token=api_token,
        vault_path=tmp_path / "vault",
        app_base_url="http://127.0.0.1:8080",
        repo_full_name="example-owner/llm-wiki",
        s3_endpoint=None,
        s3_bucket="llm-wiki",
        s3_access_key_id=None,
        s3_secret_access_key=None,
        s3_region="us-east-1",
        worker_max_attempts=3,
        worker_retry_backoff_seconds=300,
        worker_heartbeat_interval=15,
        api_plugin_token=plugin_token,
        api_admin_token=admin_token,
    )
