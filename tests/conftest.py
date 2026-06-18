from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from llm_wiki.config import Settings, load_settings
from llm_wiki.db import connect
from llm_wiki.migrations import migrate


@pytest.fixture
def db_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    database_url = os.getenv("APP_DATABASE_URL")
    if not database_url:
        pytest.skip("APP_DATABASE_URL is required for DB-backed tests")
    if not _is_dedicated_test_database(database_url):
        pytest.fail(
            "DB-backed tests require a dedicated test database. "
            "Set APP_DATABASE_URL to a database whose name contains 'test'."
        )
    if os.getenv("LLM_WIKI_ALLOW_DESTRUCTIVE_TESTS") != "1":
        pytest.fail(
            "DB-backed tests truncate tables. Set LLM_WIKI_ALLOW_DESTRUCTIVE_TESTS=1 "
            "after confirming APP_DATABASE_URL points to a dedicated test database."
        )
    monkeypatch.setenv("MIRROR_PATH", str(tmp_path / "mirror"))
    monkeypatch.delenv("VAULT_PATH", raising=False)
    monkeypatch.setenv("APP_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.delenv("APP_REPO_FULL_NAME", raising=False)
    monkeypatch.setenv("S3_BUCKET", "llm-wiki")
    monkeypatch.setenv("DB_NOTE_RUN_ROOT", str(tmp_path / "db-note-runs"))
    settings = load_settings()
    migrate(settings)
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "truncate personalization_settings, chat_turns, chat_sessions, "
                "daily_digest_runs, "
                "notification_deliveries, notification_subscriptions, time_items, "
                "note_feedback, note_assets, note_links, note_revisions, export_jobs, notes, "
                "processing_attachments, processing_request_reviews, processing_requests, worker_state "
                "restart identity cascade"
            )
        conn.commit()
    return settings


def _is_dedicated_test_database(database_url: str) -> bool:
    parsed = urlparse(database_url)
    database_name = Path(parsed.path).name.lower()
    return bool(database_name and "test" in database_name)
