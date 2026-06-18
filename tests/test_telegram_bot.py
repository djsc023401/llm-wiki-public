from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import llm_wiki.telegram_bot as telegram_bot
from llm_wiki.api import app, settings_dep
from llm_wiki import chat_service
from llm_wiki.db import connect, fetch_all
from llm_wiki.notifications import list_notification_deliveries
from llm_wiki.notes_store import create_note, get_note, list_source_suggestions
from llm_wiki.personalization import update_personalization_settings
from llm_wiki.requests_store import content_sha256, create_request, update_status
from llm_wiki.telegram_bot import build_telegram_message, build_telegram_reply, list_telegram_suggestions
from llm_wiki.time_store import create_time_item, list_time_items


class _TelegramResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload or "")

    def json(self):
        if self._payload is None:
            raise ValueError("invalid json")
        return self._payload


def test_telegram_webhook_requires_secret_and_allowed_chat(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
        telegram_webhook_secret="webhook-secret",
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    sent: list[str] = []
    monkeypatch.setattr(telegram_bot, "send_telegram_message", lambda text, settings: sent.append(text))
    client = TestClient(app)
    try:
        no_secret = client.post(
            "/api/telegram/webhook",
            json={"message": {"chat": {"id": 1234}, "text": "/help"}},
        )
        assert no_secret.status_code == 401

        other_chat = client.post(
            "/api/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"},
            json={"message": {"chat": {"id": 9999}, "text": "/help"}},
        )
        assert other_chat.status_code == 200
        assert other_chat.json()["status"] == "ignored"
        assert sent == []

        ok = client.post(
            "/api/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"},
            json={"message": {"chat": {"id": 1234}, "text": "/help"}},
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "sent"
        assert "llm-wiki Telegram 명령" in sent[-1]
    finally:
        app.dependency_overrides.clear()


def test_telegram_poll_once_handles_updates_and_advances_offset(db_settings, monkeypatch, tmp_path):
    settings = replace(
        db_settings,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
        telegram_polling_enabled=True,
        telegram_polling_timeout_seconds=0,
        telegram_polling_limit=2,
        telegram_polling_offset_path=tmp_path / "telegram-offset.json",
    )
    calls = {}
    handled: list[str] = []
    stored_offsets: list[int] = []

    def fake_get(url, *, params, timeout):
        calls.update({"url": url, "params": params, "timeout": timeout})
        return _TelegramResponse(
            200,
            {
                "ok": True,
                "result": [
                    {"update_id": 20, "message": {"chat": {"id": 1234}, "text": "/schedule"}},
                    {"update_id": 21, "message": {"chat": {"id": 1234}, "text": "/notifications"}},
                ],
            },
        )

    def fake_handle(update, loaded_settings):
        handled.append(str(update["message"]["text"]))
        assert loaded_settings is settings
        return {"status": "sent"}

    monkeypatch.setattr(telegram_bot.requests, "get", fake_get)
    monkeypatch.setattr(telegram_bot, "handle_telegram_update", fake_handle)

    result = telegram_bot.poll_telegram_updates(settings, offset=10, offset_callback=stored_offsets.append)

    assert result["status"] == "ok"
    assert result["fetched"] == 2
    assert result["handled"] == 2
    assert result["next_offset"] == 22
    assert handled == ["/schedule", "/notifications"]
    assert stored_offsets == [21, 22]
    assert calls["params"]["offset"] == 10
    assert calls["params"]["limit"] == 2
    assert calls["params"]["allowed_updates"] == '["message", "edited_message", "callback_query"]'
    assert calls["timeout"] == 15


def test_telegram_poll_does_not_advance_offset_after_failed_update(db_settings, monkeypatch, tmp_path):
    settings = replace(
        db_settings,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
        telegram_polling_enabled=True,
        telegram_polling_timeout_seconds=0,
        telegram_polling_limit=2,
        telegram_polling_offset_path=tmp_path / "telegram-offset.json",
    )
    stored_offsets: list[int] = []

    def fake_get(url, *, params, timeout):
        return _TelegramResponse(
            200,
            {
                "ok": True,
                "result": [
                    {"update_id": 20, "message": {"chat": {"id": 1234}, "text": "/schedule"}},
                    {"update_id": 21, "message": {"chat": {"id": 1234}, "text": "/notifications"}},
                ],
            },
        )

    def fake_handle(update, loaded_settings):
        if update["update_id"] == 20:
            raise RuntimeError("boom")
        return {"status": "sent"}

    monkeypatch.setattr(telegram_bot.requests, "get", fake_get)
    monkeypatch.setattr(telegram_bot, "handle_telegram_update", fake_handle)

    result = telegram_bot.poll_telegram_updates(settings, offset=10, offset_callback=stored_offsets.append)

    assert result["status"] == "ok"
    assert result["handled"] == 1
    assert result["next_offset"] == 10
    assert result["results"][0]["status"] == "failed"
    assert stored_offsets == []


def test_telegram_poll_clears_webhook_conflict_and_retries(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
        telegram_polling_enabled=True,
        telegram_polling_delete_webhook_on_conflict=True,
    )
    get_calls = []
    post_calls = []

    def fake_get(url, *, params, timeout):
        get_calls.append((url, params, timeout))
        if len(get_calls) == 1:
            return _TelegramResponse(409, {"ok": False}, "Conflict: webhook is active")
        return _TelegramResponse(200, {"ok": True, "result": []})

    def fake_post(url, *, json, timeout):
        post_calls.append((url, json, timeout))
        return _TelegramResponse(200, {"ok": True, "result": True})

    monkeypatch.setattr(telegram_bot.requests, "get", fake_get)
    monkeypatch.setattr(telegram_bot.requests, "post", fake_post)

    result = telegram_bot.poll_telegram_updates(settings, timeout_seconds=0, limit=1)

    assert result["status"] == "ok"
    assert len(get_calls) == 2
    assert len(post_calls) == 1
    assert post_calls[0][0].endswith("/deleteWebhook")
    assert post_calls[0][1] == {"drop_pending_updates": False}


def test_telegram_poll_offset_helpers_ignore_bad_state_and_save(tmp_path):
    offset_path = tmp_path / "offset.json"
    assert telegram_bot._load_polling_offset(offset_path) is None
    offset_path.write_text("not-json", encoding="utf-8")
    assert telegram_bot._load_polling_offset(offset_path) is None

    telegram_bot._save_polling_offset(offset_path, 123)

    assert telegram_bot._load_polling_offset(offset_path) == 123


def test_telegram_quick_capture_creates_note_and_processing_request(db_settings):
    reply = build_telegram_reply("/note 치약 구매 필요\n내일 오전에 확인", db_settings)

    assert "작성중 메모를 저장하고 AI 처리를 요청했습니다." in reply
    with connect(db_settings) as conn:
        note = fetch_all(conn, "select * from notes order by created_at desc limit 1")[0]
        revision = fetch_all(conn, "select * from note_revisions where note_id = %s", (note["id"],))[0]
        request = fetch_all(conn, "select * from processing_requests where note_id = %s", (note["id"],))[0]

    assert note["kind"] == "inbox"
    assert note["status"] == "draft"
    assert note["title"] == "치약 구매 필요"
    assert note["body_markdown"] == "치약 구매 필요\n내일 오전에 확인"
    assert note["metadata"]["channel"] == "telegram"
    assert note["metadata"]["captured_at"]
    assert revision["change_source"] == "operator"
    assert revision["created_by"] == "telegram"
    assert request["source"] == "telegram-note"
    assert request["operation"] == "ingest"
    assert request["input_mode"] == "db-note"
    assert request["status"] == "queued"
    assert request["source_revision_id"] == revision["id"]
    assert request["content_hash"] == content_sha256(revision["body_markdown"])


def test_telegram_quick_capture_requires_body(db_settings):
    reply = build_telegram_reply("/capture", db_settings)

    assert "저장할 메모 내용을 함께 입력해주세요" in reply
    with connect(db_settings) as conn:
        assert fetch_all(conn, "select id from notes") == []
        assert fetch_all(conn, "select id from processing_requests") == []


def test_telegram_chat_command_stores_turns_and_uses_context(db_settings, monkeypatch):
    contexts: list[dict | None] = []

    def fake_run_chat_search(query, *, limit, settings, context=None):
        contexts.append(context)
        return {
            "query": query,
            "answer_mode": "planned_retrieval",
            "answer": f"{query} 답변",
            "answer_refs": [{"note_id": "note_demo", "title": "근거"}],
            "items": [{"item_type": "note", "note_id": "note_demo", "title": "근거"}],
            "followups": ["근거만 보여줘"],
            "meta": {"query_plan": {"context_used": bool(context)}},
        }

    monkeypatch.setattr(chat_service, "run_chat_search", fake_run_chat_search)

    first = build_telegram_reply("/chat 첫 질문", db_settings)
    second = build_telegram_reply("/ask 추가 질문", db_settings)

    assert "첫 질문 답변" in first
    assert "근거 1건 · 대화 1턴" in first
    assert "추가 질문 답변" in second
    assert "근거 1건 · 대화 2턴" in second
    assert contexts[0] is None
    assert contexts[1]
    assert contexts[1]["messages"][0]["query"] == "첫 질문"
    with connect(db_settings) as conn:
        session = fetch_all(conn, "select * from chat_sessions where id = 'chat_telegram'")[0]
        turns = fetch_all(conn, "select query, turn_index from chat_turns order by turn_index")
    assert session["source"] == "telegram"
    assert [turn["query"] for turn in turns] == ["첫 질문", "추가 질문"]
    assert [turn["turn_index"] for turn in turns] == [1, 2]


def test_telegram_chat_command_requires_query(db_settings, monkeypatch):
    called = False

    def fake_run_chat_search(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(chat_service, "run_chat_search", fake_run_chat_search)

    reply = build_telegram_reply("/chat", db_settings)

    assert "질문 내용을 함께 입력해주세요" in reply
    assert called is False
    with connect(db_settings) as conn:
        assert fetch_all(conn, "select id from chat_turns") == []


def test_telegram_suggestion_list_approve_and_reject(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
        telegram_webhook_secret="webhook-secret",
    )
    monkeypatch.setattr(telegram_bot, "export_notes_to_markdown", lambda *args, **kwargs: {"status": "succeeded"})
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "텔레그램 제안 소스",
            "body_markdown": "\n".join(
                [
                    "# 텔레그램 제안 소스",
                    "",
                    "## Related",
                    "",
                    "### Topic Suggestions",
                    "",
                    "| Candidate | Suggested path | Evidence | Review note |",
                    "| --- | --- | --- | --- |",
                    "| 여행 준비 | `wiki/topics/travel-prep.md` | 여행 준비를 언급함. | 승인 후보. |",
                    "",
                    "### Tag Suggestions",
                    "",
                    "| Candidate | Evidence | Review note |",
                    "| --- | --- | --- |",
                    "| 여행 | 여행 준비를 언급함. | 태그 후보. |",
                ]
            ),
            "metadata": {"channel": "web"},
            "change_source": "test",
        },
        settings,
    )

    pending = list_telegram_suggestions(status="pending", settings=settings)
    tokens = {item["candidate"]: item["telegram_id"] for item in pending}

    listing = build_telegram_reply("/suggestions", settings)
    assert "미검토 제안" in listing
    assert "각 항목 아래 버튼으로 바로 처리하세요." in listing
    assert "버튼이 보이지 않으면 짧은 ID로 처리하세요: /approve <id>, /reject <id>" in listing
    assert "여행 준비" in listing
    assert f"[{tokens['여행 준비']}]" in listing
    assert f"/approve {tokens['여행 준비']}" not in listing
    assert f"/reject {tokens['여행 준비']}" not in listing

    button_message = build_telegram_message("/suggestions", settings)
    keyboard = button_message["reply_markup"]["inline_keyboard"]
    assert keyboard[0][0] == {"text": "승인 1", "callback_data": f"sg:a:{tokens['여행 준비']}"}
    assert keyboard[0][1] == {"text": "거절 1", "callback_data": f"sg:r:{tokens['여행 준비']}"}

    approved_topic = build_telegram_reply(f"/approve {tokens['여행 준비']}", settings)
    assert "승인했습니다: 여행 준비" in approved_topic
    assert list_source_suggestions(source["id"], settings)["topics"][0]["promoted_note_id"]

    approved_tag = build_telegram_reply(f"승인 {tokens['여행']}", settings)
    assert "태그를 적용했습니다: 여행" in approved_tag
    source_after_tag = get_note(source["id"], settings)
    assert "여행" in source_after_tag["metadata"]["manual_tags"]

    tag_again = build_telegram_reply(f"/reject {tokens['여행']}", settings)
    assert "이미 반영된 제안은 거절할 수 없습니다" in tag_again


def test_telegram_suggestion_callback_buttons(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
        telegram_webhook_secret="webhook-secret",
    )
    monkeypatch.setattr(telegram_bot, "export_notes_to_markdown", lambda *args, **kwargs: {"status": "succeeded"})
    create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "텔레그램 버튼 소스",
            "body_markdown": "\n".join(
                [
                    "# 텔레그램 버튼 소스",
                    "",
                    "## Related",
                    "",
                    "### Topic Suggestions",
                    "",
                    "| Candidate | Suggested path | Evidence | Review note |",
                    "| --- | --- | --- | --- |",
                    "| 버튼 테스트 | `wiki/topics/button-test.md` | 버튼을 검증함. | 승인 후보. |",
                ]
            ),
            "metadata": {"channel": "web"},
            "change_source": "test",
        },
        settings,
    )
    token = list_telegram_suggestions(status="pending", settings=settings)[0]["telegram_id"]
    sent: list[str] = []
    answered: list[dict] = []

    def fake_answer(url, *, json, timeout):
        answered.append({"url": url, "json": json, "timeout": timeout})
        return _TelegramResponse(200, {"ok": True, "result": True})

    monkeypatch.setattr(telegram_bot, "send_telegram_message", lambda text, settings: sent.append(text))
    monkeypatch.setattr(telegram_bot.requests, "post", fake_answer)

    result = telegram_bot.handle_telegram_update(
        {
            "callback_query": {
                "id": "callback-1",
                "message": {"chat": {"id": 1234}, "message_id": 77},
                "data": f"sg:a:{token}",
            }
        },
        settings,
    )

    assert result["status"] == "callback_sent"
    assert sent[-1] == "승인했습니다: 버튼 테스트 (주제)"
    assert answered[0]["url"].endswith("/answerCallbackQuery")
    assert answered[0]["json"]["callback_query_id"] == "callback-1"
    assert answered[1]["url"].endswith("/editMessageText")
    assert answered[1]["json"]["message_id"] == 77
    assert answered[1]["json"]["text"] == "미검토 제안이 없습니다."


def test_telegram_suggestion_callback_reject_button(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
        telegram_webhook_secret="webhook-secret",
    )
    create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "텔레그램 거절 버튼 소스",
            "body_markdown": "\n".join(
                [
                    "# 텔레그램 거절 버튼 소스",
                    "",
                    "## Related",
                    "",
                    "### Tag Suggestions",
                    "",
                    "| Candidate | Evidence | Review note |",
                    "| --- | --- | --- |",
                    "| 거절 테스트 | 버튼 거절을 검증함. | 거절 후보. |",
                ]
            ),
            "metadata": {"channel": "web"},
            "change_source": "test",
        },
        settings,
    )
    token = list_telegram_suggestions(status="pending", settings=settings)[0]["telegram_id"]
    sent: list[str] = []
    answered: list[dict] = []

    def fake_answer(url, *, json, timeout):
        answered.append({"url": url, "json": json, "timeout": timeout})
        return _TelegramResponse(200, {"ok": True, "result": True})

    monkeypatch.setattr(telegram_bot, "send_telegram_message", lambda text, settings: sent.append(text))
    monkeypatch.setattr(telegram_bot.requests, "post", fake_answer)

    result = telegram_bot.handle_telegram_update(
        {
            "callback_query": {
                "id": "callback-reject",
                "message": {"chat": {"id": 1234}, "message_id": 78},
                "data": f"sg:r:{token}",
            }
        },
        settings,
    )

    assert result["status"] == "callback_sent"
    assert sent[-1] == "거절했습니다: 거절 테스트"
    assert answered[0]["url"].endswith("/answerCallbackQuery")
    assert answered[0]["json"]["callback_query_id"] == "callback-reject"
    assert answered[1]["url"].endswith("/editMessageText")
    assert answered[1]["json"]["message_id"] == 78
    assert answered[1]["json"]["text"] == "미검토 제안이 없습니다."


def test_telegram_today_suggestion_callback_refreshes_today_message(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
        telegram_webhook_secret="webhook-secret",
    )
    monkeypatch.setattr(telegram_bot, "export_notes_to_markdown", lambda *args, **kwargs: {"status": "succeeded"})
    create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "오늘 브리핑 제안 버튼 소스",
            "body_markdown": "\n".join(
                [
                    "# 오늘 브리핑 제안 버튼 소스",
                    "",
                    "## Related",
                    "",
                    "### Topic Suggestions",
                    "",
                    "| Candidate | Suggested path | Evidence | Review note |",
                    "| --- | --- | --- | --- |",
                    "| 오늘 버튼 처리 | `wiki/topics/today-button.md` | 오늘 버튼을 검증함. | 승인 후보. |",
                ]
            ),
            "metadata": {"channel": "web"},
            "change_source": "test",
        },
        settings,
    )
    token = list_telegram_suggestions(status="pending", settings=settings)[0]["telegram_id"]
    sent: list[str] = []
    answered: list[dict] = []

    def fake_answer(url, *, json, timeout):
        answered.append({"url": url, "json": json, "timeout": timeout})
        return _TelegramResponse(200, {"ok": True, "result": True})

    monkeypatch.setattr(telegram_bot, "send_telegram_message", lambda text, settings: sent.append(text))
    monkeypatch.setattr(telegram_bot.requests, "post", fake_answer)

    result = telegram_bot.handle_telegram_update(
        {
            "callback_query": {
                "id": "callback-today-suggestion",
                "message": {"chat": {"id": 1234}, "message_id": 79},
                "data": f"sg:t:a:{token}",
            }
        },
        settings,
    )

    assert result["status"] == "callback_sent"
    assert result["group"] == "suggestion"
    assert sent[-1] == "승인했습니다: 오늘 버튼 처리 (주제)"
    assert answered[0]["url"].endswith("/answerCallbackQuery")
    assert answered[1]["url"].endswith("/editMessageText")
    assert answered[1]["json"]["message_id"] == 79
    assert "오늘 브리핑" in answered[1]["json"]["text"]
    assert "지금 먼저 처리할 것" not in answered[1]["json"]["text"]


def test_telegram_today_notification_callback_refreshes_today_message(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
        telegram_webhook_secret="webhook-secret",
    )
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "오늘 취소 대상",
            "remind_at": now,
            "notification_channels": ["telegram"],
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
                  'ntf_today_callback1234',
                  %s,
                  'telegram',
                  'failed',
                  %s,
                  '{"title":"오늘 취소 대상","body":"오늘 브리핑에서 처리할 알림"}'::jsonb
                )
                """,
                (item["id"], now),
            )
        conn.commit()
    message = build_telegram_message("/today", settings)
    callbacks = [
        button["callback_data"]
        for row in message["reply_markup"]["inline_keyboard"]
        for button in row
    ]
    callback_data = next(callback for callback in callbacks if callback.startswith("nd:t:c:"))
    sent: list[str] = []
    answered: list[dict] = []

    def fake_answer(url, *, json, timeout):
        answered.append({"url": url, "json": json, "timeout": timeout})
        return _TelegramResponse(200, {"ok": True, "result": True})

    monkeypatch.setattr(telegram_bot, "send_telegram_message", lambda text, settings: sent.append(text))
    monkeypatch.setattr(telegram_bot.requests, "post", fake_answer)

    result = telegram_bot.handle_telegram_update(
        {
            "callback_query": {
                "id": "callback-today-notification",
                "message": {"chat": {"id": 1234}, "message_id": 81},
                "data": callback_data,
            }
        },
        settings,
    )

    assert result["status"] == "callback_sent"
    assert result["group"] == "notification_delivery"
    assert sent[-1] == "알림을 취소했습니다: 오늘 브리핑에서 처리할 알림"
    assert list_notification_deliveries(status="cancelled", settings=settings)[0]["id"] == "ntf_today_callback1234"
    assert answered[0]["url"].endswith("/answerCallbackQuery")
    assert answered[1]["url"].endswith("/editMessageText")
    assert answered[1]["json"]["message_id"] == 81
    assert "오늘 브리핑" in answered[1]["json"]["text"]
    assert "실패 알림" not in answered[1]["json"]["text"]


def test_telegram_time_and_notification_commands(db_settings):
    update_personalization_settings({"default_schedule_days": 2}, db_settings)
    today = datetime.now(ZoneInfo("Asia/Seoul")).replace(hour=14, minute=0, second=0, microsecond=0)
    travel_item = create_time_item(
        {
            "kind": "event",
            "title": "강릉 여행",
            "start_at": today + timedelta(days=2),
            "notification_channels": ["telegram"],
        },
        db_settings,
    )
    create_time_item(
        {
            "kind": "event",
            "title": "먼 일정",
            "start_at": today + timedelta(days=3),
            "notification_channels": ["telegram"],
        },
        db_settings,
    )

    schedule = build_telegram_reply("/schedule", db_settings)
    assert "남은 일정/할 일 (2일 이내)" in schedule
    assert "강릉 여행" in schedule
    assert "먼 일정" not in schedule

    notifications = build_telegram_reply("/notifications", db_settings)
    assert "알림" in notifications
    assert "강릉 여행" in notifications
    assert "먼 일정" not in notifications

    create_time_item(
        {
            "kind": "task",
            "title": "오늘 브리핑 확인",
            "due_at": today,
            "notification_channels": ["telegram"],
        },
        db_settings,
    )
    create_note(
        {
            "kind": "inbox",
            "status": "draft",
            "title": "최근 작성중 메모",
            "body_markdown": "오늘 이어서 정리할 메모",
        },
        db_settings,
    )
    failed_request = create_request(
        {
            "id": "req_today_failed",
            "source": "telegram-test",
            "operation": "ingest",
            "input_mode": "snapshot",
            "content_snapshot": "실패 요청 테스트",
        },
        db_settings,
    )
    update_status(failed_request["id"], "failed", error_message="테스트 AI 처리 실패", settings=db_settings)
    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values (
                  'ntf_today_failed1234',
                  %s,
                  'telegram',
                  'failed',
                  %s,
                  '{"title":"오늘 실패 알림","body":"오늘 처리할 실패 알림"}'::jsonb
                )
                """,
                (travel_item["id"], today),
            )
        conn.commit()
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "오늘 제안 소스",
            "body_markdown": "\n".join(
                [
                    "# 오늘 제안 소스",
                    "",
                    "## Related",
                    "",
                    "### Tag Suggestions",
                    "",
                    "| Candidate | Evidence | Review note |",
                    "| --- | --- | --- |",
                    "| 오늘처리 | 오늘 브리핑에서 검토할 태그. | 검토 후보. |",
                ]
            ),
        },
        db_settings,
    )
    old_draft = create_note(
        {
            "kind": "inbox",
            "status": "draft",
            "title": "오래된 작성중 메모",
            "body_markdown": "며칠째 방치된 메모",
        },
        db_settings,
    )
    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update notes set updated_at = now() - interval '5 days' where id = %s",
                (old_draft["id"],),
            )
        conn.commit()

    briefing = build_telegram_reply("/today", db_settings)
    assert "오늘 브리핑" in briefing
    assert "Asia/Seoul" in briefing
    assert "2일 이내" in briefing
    assert "하루 요약 08:00" in briefing
    assert "지금 먼저 처리할 것" in briefing
    assert "오늘 일정/할 일" in briefing
    assert "2일 이내 예정" in briefing
    assert "AI 처리 실패" in briefing
    assert "telegram-test - 테스트 AI 처리 실패" in briefing
    assert "실패 알림" in briefing
    assert "오늘 처리할 실패 알림" in briefing
    assert "오늘 브리핑 확인" in briefing
    assert "오늘처리" in briefing
    assert "작성중 노트" in briefing
    assert "최근 작성중 메모" in briefing
    assert "오래된 작성중 노트 (3일 이상)" in briefing
    assert "오래된 작성중 메모 - 마지막 수정" in briefing
    assert briefing.index("최근 작성중 메모") < briefing.index("오래된 작성중 노트")

    today_message = build_telegram_message("/today", db_settings)
    keyboard = today_message["reply_markup"]["inline_keyboard"]
    callbacks = [button["callback_data"] for row in keyboard for button in row]
    tokens = {item["candidate"]: item["telegram_id"] for item in list_telegram_suggestions(settings=db_settings)}
    failed_notification = list_notification_deliveries(status="failed", settings=db_settings)[0]
    notification_token = telegram_bot._telegram_notification_delivery_id(failed_notification)
    assert "지금 먼저 처리할 것" in today_message["text"]
    assert any(callback.startswith("ti:t:c:") for callback in callbacks)
    assert any(callback.startswith("ti:t:x:") for callback in callbacks)
    assert f"nd:t:c:{notification_token}" in callbacks
    assert f"nd:t:d:{notification_token}" in callbacks
    assert f"sg:t:a:{tokens['오늘처리']}" in callbacks
    assert f"sg:t:r:{tokens['오늘처리']}" in callbacks
    assert get_note(source["id"], db_settings)


def test_telegram_today_briefing_groups_related_time_items(db_settings):
    update_personalization_settings({"default_schedule_days": 7}, db_settings)
    now = datetime.now(ZoneInfo("Asia/Seoul")).replace(hour=10, minute=0, second=0, microsecond=0)
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "강릉 여행 계획",
            "body_markdown": "강릉 여행을 준비한다.",
        },
        db_settings,
    )
    create_time_item(
        {
            "source_note_id": source["id"],
            "kind": "deadline",
            "title": "강릉 여행 준비 1차",
            "due_at": now + timedelta(days=1),
            "notification_channels": ["telegram"],
        },
        db_settings,
    )
    create_time_item(
        {
            "source_note_id": source["id"],
            "kind": "deadline",
            "title": "강릉 여행 준비 2차",
            "due_at": now + timedelta(days=2),
            "notification_channels": ["telegram"],
        },
        db_settings,
    )
    create_time_item(
        {
            "source_note_id": source["id"],
            "kind": "event",
            "title": "강릉 여행",
            "start_at": now + timedelta(days=3),
            "notification_channels": ["telegram"],
        },
        db_settings,
    )

    briefing = build_telegram_reply("/today", db_settings)

    assert "강릉 여행" in briefing
    assert "관련 마감 2건" in briefing
    assert "강릉 여행 준비 1차" not in briefing
    assert "강릉 여행 준비 2차" not in briefing


def test_telegram_schedule_message_includes_time_item_action_buttons(db_settings):
    upcoming = datetime.now(ZoneInfo("Asia/Seoul")).replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
    create_time_item(
        {
            "kind": "event",
            "title": "버튼 일정",
            "start_at": upcoming,
            "notification_channels": ["telegram"],
        },
        db_settings,
    )

    message = build_telegram_message("/schedule", db_settings)
    keyboard = message["reply_markup"]["inline_keyboard"]

    assert "버튼 일정" in message["text"]
    assert keyboard[0][0]["text"] == "1 완료"
    assert keyboard[0][0]["callback_data"].startswith("ti:s:c:")
    assert keyboard[0][1]["text"] == "1 취소"
    assert keyboard[1][0]["callback_data"].startswith("ti:s:p1:")
    assert keyboard[1][1]["callback_data"].startswith("ti:s:tm:")


def test_telegram_time_and_notification_text_fallback_commands(db_settings):
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    schedule_item = create_time_item(
        {
            "kind": "event",
            "title": "텍스트 명령 일정",
            "start_at": now + timedelta(days=1),
            "remind_at": now + timedelta(hours=12),
            "notification_channels": ["telegram"],
        },
        db_settings,
    )
    cancel_item = create_time_item(
        {
            "kind": "task",
            "title": "텍스트 명령 취소",
            "due_at": now + timedelta(days=1),
            "notification_channels": ["telegram"],
        },
        db_settings,
    )
    delivery_item = create_time_item(
        {
            "kind": "reminder",
            "title": "텍스트 명령 알림",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["telegram"],
        },
        db_settings,
    )
    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values (
                  'ntf_telegram_text1234',
                  %s,
                  'telegram',
                  'queued',
                  %s,
                  '{"title":"llm-wiki 알림","body":"텍스트 명령 알림"}'::jsonb
                )
                """,
                (delivery_item["id"], now + timedelta(hours=1)),
            )
        conn.commit()

    schedule_token = telegram_bot._telegram_time_item_id(schedule_item)
    cancel_token = telegram_bot._telegram_time_item_id(cancel_item)
    delivery = next(
        item
        for item in list_notification_deliveries(limit=20, settings=db_settings)
        if item["id"] == "ntf_telegram_text1234"
    )
    delivery_token = telegram_bot._telegram_notification_delivery_id(delivery)

    schedule = build_telegram_reply("/schedule", db_settings)
    assert f"[{schedule_token}]" in schedule
    assert "/done <id>" in schedule
    assert "/cancel-time <id>" in schedule
    assert "/snooze1 <id>" in schedule
    assert "/tomorrow <id>" in schedule

    postponed = build_telegram_reply(f"/snooze1 {schedule_token}", db_settings)
    assert "1시간 미뤘습니다: 텍스트 명령 일정" in postponed
    completed = build_telegram_reply(f"/done {schedule_token}", db_settings)
    assert "완료했습니다: 텍스트 명령 일정" in completed
    cancelled = build_telegram_reply(f"/cancel-time {cancel_token}", db_settings)
    assert "취소했습니다: 텍스트 명령 취소" in cancelled

    notifications = build_telegram_reply("/notifications", db_settings)
    assert f"[{delivery_token}]" in notifications
    assert "/cancel-notification <id>" in notifications
    assert "/delete-notification <id>" in notifications
    notification_cancelled = build_telegram_reply(f"/cancel-notification {delivery_token}", db_settings)
    assert "알림을 취소했습니다: 텍스트 명령 알림" in notification_cancelled
    notification_deleted = build_telegram_reply(f"/delete-notification {delivery_token}", db_settings)
    assert "알림을 삭제했습니다: 텍스트 명령 알림" in notification_deleted

    statuses = {item["title"]: item["status"] for item in list_time_items(include_closed=True, settings=db_settings)}
    assert statuses["텍스트 명령 일정"] == "completed"
    assert statuses["텍스트 명령 취소"] == "cancelled"
    assert all(
        item["id"] != "ntf_telegram_text1234"
        for item in list_notification_deliveries(status="cancelled", settings=db_settings)
    )
    with connect(db_settings) as conn:
        deleted_delivery = fetch_all(
            conn,
            "select status, hidden_at from notification_deliveries where id = 'ntf_telegram_text1234'",
        )
    assert deleted_delivery[0]["status"] == "cancelled"
    assert deleted_delivery[0]["hidden_at"] is not None


def test_telegram_time_item_callback_complete_marks_completed_and_cancels_delivery(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
        telegram_webhook_secret="webhook-secret",
    )
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "텔레그램 완료",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["telegram"],
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
                values ('ntf_telegram_complete1234', %s, 'telegram', 'queued', %s, '{}'::jsonb)
                """,
                (item["id"], now + timedelta(hours=1)),
            )
        conn.commit()
    callback_data = build_telegram_message("/schedule", settings)["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    sent: list[str] = []
    answered: list[dict] = []

    def fake_post(url, *, json, timeout):
        answered.append({"url": url, "json": json, "timeout": timeout})
        return _TelegramResponse(200, {"ok": True, "result": True})

    monkeypatch.setattr(telegram_bot, "send_telegram_message", lambda text, settings: sent.append(text))
    monkeypatch.setattr(telegram_bot.requests, "post", fake_post)

    result = telegram_bot.handle_telegram_update(
        {
            "callback_query": {
                "id": "time-complete",
                "message": {"chat": {"id": 1234}, "message_id": 79},
                "data": callback_data,
            }
        },
        settings,
    )

    assert result["status"] == "callback_sent"
    assert result["group"] == "time_item"
    assert sent[-1] == "완료했습니다: 텔레그램 완료"
    rows = list_time_items(include_closed=True, settings=settings)
    assert rows[0]["status"] == "completed"
    with connect(settings) as conn:
        deliveries = fetch_all(
            conn,
            "select status from notification_deliveries where id = 'ntf_telegram_complete1234'",
        )
    assert deliveries[0]["status"] == "cancelled"
    assert answered[0]["url"].endswith("/answerCallbackQuery")
    assert answered[1]["url"].endswith("/editMessageText")
    assert answered[1]["json"]["text"] == "남은 일정/할 일이 없습니다."


def test_telegram_notification_callback_cancel_and_delete_buttons(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
        telegram_webhook_secret="webhook-secret",
    )
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "텔레그램 알림",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["telegram"],
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
                  'ntf_telegram_cancel1234',
                  %s,
                  'telegram',
                  'queued',
                  %s,
                  '{"title":"llm-wiki 알림","body":"텔레그램 알림"}'::jsonb
                )
                """,
                (item["id"], now + timedelta(hours=1)),
            )
        conn.commit()
    message = build_telegram_message("/notifications", settings)
    assert message["text"].count("텔레그램 알림") == 1
    assert "대기 / 텔레그램" in message["text"]
    notification_row = next(
        row
        for row in message["reply_markup"]["inline_keyboard"]
        if row[0]["callback_data"].startswith("nd:c:")
    )
    sent: list[str] = []
    answered: list[dict] = []

    def fake_post(url, *, json, timeout):
        answered.append({"url": url, "json": json, "timeout": timeout})
        return _TelegramResponse(200, {"ok": True, "result": True})

    monkeypatch.setattr(telegram_bot, "send_telegram_message", lambda text, settings: sent.append(text))
    monkeypatch.setattr(telegram_bot.requests, "post", fake_post)

    cancel_result = telegram_bot.handle_telegram_update(
        {
            "callback_query": {
                "id": "notification-cancel",
                "message": {"chat": {"id": 1234}, "message_id": 80},
                "data": notification_row[0]["callback_data"],
            }
        },
        settings,
    )

    assert cancel_result["status"] == "callback_sent"
    assert sent[-1] == "알림을 취소했습니다: 텔레그램 알림"
    assert list_notification_deliveries(status="cancelled", settings=settings)[0]["id"] == "ntf_telegram_cancel1234"

    delete_data = next(
        button["callback_data"]
        for row in build_telegram_message("/notifications", settings)["reply_markup"]["inline_keyboard"]
        for button in row
        if button["callback_data"].startswith("nd:d:")
    )
    delete_result = telegram_bot.handle_telegram_update(
        {
            "callback_query": {
                "id": "notification-delete",
                "message": {"chat": {"id": 1234}, "message_id": 80},
                "data": delete_data,
            }
        },
        settings,
    )

    assert delete_result["status"] == "callback_sent"
    assert sent[-1] == "알림을 삭제했습니다: 텔레그램 알림"
    assert list_notification_deliveries(status="cancelled", settings=settings) == []
    assert answered[0]["url"].endswith("/answerCallbackQuery")
    assert answered[1]["url"].endswith("/editMessageText")
