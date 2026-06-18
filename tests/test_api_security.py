from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from llm_wiki.api import (
    ADMIN_SCOPE,
    PLUGIN_SCOPE,
    ValidationError,
    _authorization_scopes,
    validate_attachment_metadata,
    validate_request_payload,
    validate_vault_markdown_path,
)
from llm_wiki.config import Settings


def test_authorization_scopes_split_plugin_admin_and_legacy_tokens(tmp_path: Path):
    settings = _settings(tmp_path, plugin_token="plugin-token", admin_token="admin-token")

    assert _authorization_scopes(settings, "Bearer plugin-token") == {PLUGIN_SCOPE}
    assert _authorization_scopes(settings, "Bearer admin-token") == {ADMIN_SCOPE}
    assert _authorization_scopes(settings, "Bearer wrong-token") == set()

    legacy = _settings(tmp_path, api_token="legacy-token")
    assert _authorization_scopes(legacy, "Bearer legacy-token") == {PLUGIN_SCOPE, ADMIN_SCOPE}


def test_validate_request_payload_normalizes_and_defaults(tmp_path: Path):
    settings = _settings(tmp_path)
    payload = validate_request_payload(
        {
            "id": "req_12345678",
            "file_path": "inbox/mobile/capture.md",
            "content_hash": "a" * 64,
            "content_snapshot": "# Capture\n",
        },
        settings,
    )

    assert payload["operation"] == "ingest"
    assert payload["sensitivity"] == "private"
    assert payload["repo_full_name"] == "example-owner/llm-wiki"
    assert payload["branch"] == "main"
    assert payload["file_path"] == "inbox/mobile/capture.md"


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        ("../secret.md", "invalid_file_path"),
        ("inbox/../secret.md", "invalid_file_path"),
        ("/vault/inbox/capture.md", "invalid_file_path"),
        ("inbox\\capture.md", "invalid_file_path"),
        (".obsidian/plugins/llm-wiki/main.md", "file_path_not_allowed"),
        ("inbox/.private.md", "file_path_not_allowed"),
        ("sources/legacy.md", "file_path_not_allowed"),
        ("assets/file.png", "file_path_must_be_markdown"),
    ],
)
def test_validate_vault_markdown_path_rejects_unsafe_paths(path: str, detail: str):
    with pytest.raises(ValidationError, match=detail):
        validate_vault_markdown_path(path)


@pytest.mark.parametrize(
    "payload",
    [
        {"file_path": "inbox/test.md", "operation": "rewrite"},
        {"file_path": "inbox/test.md", "sensitivity": "secret"},
        {"file_path": "inbox/test.md", "repo_full_name": "other/repo"},
        {"file_path": "inbox/test.md", "branch": "feature"},
        {"id": "bad", "file_path": "inbox/test.md"},
        {"file_path": "inbox/test.md", "content_hash": "not-a-sha"},
        {"file_path": "inbox/test.md", "commit_sha": "zzzzzzz"},
    ],
)
def test_validate_request_payload_rejects_invalid_fields(tmp_path: Path, payload: dict):
    with pytest.raises(ValidationError):
        validate_request_payload(payload, _settings(tmp_path))


def test_validate_request_payload_rejects_large_snapshot(tmp_path: Path):
    settings = _settings(tmp_path, max_request_snapshot_bytes=8)

    with pytest.raises(ValidationError, match="content_snapshot_too_large"):
        validate_request_payload({"file_path": "inbox/test.md", "content_snapshot": "too large"}, settings)


def test_validate_attachment_metadata_rejects_unsafe_or_large_attachment(tmp_path: Path):
    settings = _settings(tmp_path, max_attachment_bytes=4)

    assert validate_attachment_metadata("safe.txt", "text/plain", b"1234", settings) == ("safe.txt", "text/plain")
    with pytest.raises(HTTPException) as too_large:
        validate_attachment_metadata("safe.txt", "text/plain", b"12345", settings)
    assert too_large.value.status_code == 413

    with pytest.raises(HTTPException) as bad_name:
        validate_attachment_metadata("../secret.txt", "text/plain", b"1", settings)
    assert bad_name.value.detail == "invalid_attachment_file_name"


def _settings(
    tmp_path: Path,
    *,
    api_token: str | None = None,
    plugin_token: str | None = None,
    admin_token: str | None = None,
    max_request_snapshot_bytes: int = 262_144,
    max_attachment_bytes: int = 10 * 1024 * 1024,
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
        max_request_snapshot_bytes=max_request_snapshot_bytes,
        max_attachment_bytes=max_attachment_bytes,
    )
