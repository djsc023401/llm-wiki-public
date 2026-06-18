from __future__ import annotations

import pytest

from llm_wiki import chat_service
from llm_wiki.config import Settings


@pytest.fixture
def unit_settings(tmp_path):
    return Settings(
        database_url="postgresql://unused",
        api_token=None,
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
    )


def test_ask_chat_uses_existing_session_context(unit_settings, monkeypatch):
    calls = {}

    def fake_get_chat_session(session_id, *, settings):
        calls["get_session"] = (session_id, settings)
        return {"id": session_id}

    def fake_build_context(session_id, *, settings):
        calls["context_session"] = session_id
        return {"parent_query": "이전 질문"}

    def fake_run_chat_search(query, *, limit, settings, context):
        calls["search"] = {"query": query, "limit": limit, "context": context, "settings": settings}
        return {"answer": "답변", "answer_mode": "planned_retrieval", "answer_refs": [], "items": [], "followups": [], "meta": {}}

    def fake_append_chat_turn(**kwargs):
        calls["append"] = kwargs
        return {"id": kwargs["session_id"], "turns": [{"id": "turn_1"}]}

    monkeypatch.setattr(chat_service, "get_chat_session", fake_get_chat_session)
    monkeypatch.setattr(chat_service, "build_chat_context_from_session", fake_build_context)
    monkeypatch.setattr(chat_service, "run_chat_search", fake_run_chat_search)
    monkeypatch.setattr(chat_service, "append_chat_turn", fake_append_chat_turn)

    response = chat_service.ask_chat("이어 질문", limit=3, session_id="chat_existing", settings=unit_settings)

    assert response["session_id"] == "chat_existing"
    assert response["turn_id"] == "turn_1"
    assert calls["search"]["context"] == {"parent_query": "이전 질문"}
    assert calls["append"]["source"] == "web"


def test_ask_chat_requires_existing_session_unless_create_enabled(unit_settings, monkeypatch):
    monkeypatch.setattr(chat_service, "get_chat_session", lambda session_id, *, settings: None)

    with pytest.raises(ValueError, match="chat_session_not_found"):
        chat_service.ask_chat("질문", session_id="chat_missing", settings=unit_settings)


def test_ask_chat_validates_session_before_using_explicit_context(unit_settings, monkeypatch):
    called = False
    monkeypatch.setattr(chat_service, "get_chat_session", lambda session_id, *, settings: None)

    def fake_run_chat_search(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(chat_service, "run_chat_search", fake_run_chat_search)

    with pytest.raises(ValueError, match="chat_session_not_found"):
        chat_service.ask_chat(
            "질문",
            session_id="chat_missing",
            context={"parent_query": "이전 질문"},
            settings=unit_settings,
        )

    assert called is False


def test_ask_chat_can_create_named_session_without_context(unit_settings, monkeypatch):
    calls = {}
    monkeypatch.setattr(chat_service, "get_chat_session", lambda session_id, *, settings: None)

    def fake_run_chat_search(query, *, limit, settings, context):
        calls["context"] = context
        return {"answer": "답변", "answer_mode": "planned_retrieval", "answer_refs": [], "items": [], "followups": [], "meta": {}}

    def fake_append_chat_turn(**kwargs):
        calls["append"] = kwargs
        return {"id": kwargs["session_id"], "turns": [{"id": "turn_created"}]}

    monkeypatch.setattr(chat_service, "run_chat_search", fake_run_chat_search)
    monkeypatch.setattr(chat_service, "append_chat_turn", fake_append_chat_turn)

    response = chat_service.ask_chat(
        "첫 질문",
        session_id="chat_telegram",
        create_session_if_missing=True,
        source="telegram",
        settings=unit_settings,
    )

    assert calls["context"] is None
    assert calls["append"]["create_session_if_missing"] is True
    assert calls["append"]["source"] == "telegram"
    assert response["session_id"] == "chat_telegram"
