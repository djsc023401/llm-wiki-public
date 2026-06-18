from __future__ import annotations

import pytest

from llm_wiki.config import DEFAULT_CHAT_ANSWER_OPENAI_MODEL, load_settings


OPTIONAL_SETTINGS_ENV = [
    "APP_DEFAULT_WORKFLOW_MODE",
    "APP_REPO_FULL_NAME",
    "APP_BASE_URL",
    "APP_API_TOKEN",
    "APP_PLUGIN_TOKEN",
    "APP_ADMIN_TOKEN",
    "VAULT_PATH",
    "MIRROR_PATH",
    "S3_BUCKET",
    "S3_BUCKET_NAME",
    "S3_ACCESS_KEY_ID",
    "S3_ACCESS_KEY",
    "S3_SECRET_ACCESS_KEY",
    "S3_SECRET_ACCESS_KEY_FILE",
    "S3_SECRET_KEY",
    "S3_SECRET_KEY_FILE",
    "S3_REGION",
    "WORKER_RUNNER",
    "DB_NOTE_RUN_ROOT",
    "WORKER_DB_NOTE_AUTO_EXPORT_ENABLED",
    "MIRROR_GIT_PUSH_ENABLED",
    "TIME_SUGGESTION_AUTO_REGISTER_ENABLED",
    "DAILY_DIGEST_ENABLED",
    "OPENAI_API_RUNNER_ENABLED",
    "OPENAI_API_MODEL",
    "OPENAI_API_TIMEOUT_SECONDS",
    "OPENAI_API_MAX_OUTPUT_TOKENS",
    "OPENAI_API_REASONING_EFFORT",
    "OPENAI_API_KEY",
    "OPENAI_API_KEY_FILE",
    "CHAT_ANSWER_PROVIDER",
    "CHAT_ANSWER_OPENAI_MODEL",
    "CHAT_ANSWER_OPENAI_API_KEY",
    "CHAT_ANSWER_OPENAI_API_KEY_FILE",
    "CHAT_ANSWER_OPENAI_TIMEOUT_SECONDS",
    "CHAT_ANSWER_OPENAI_MAX_OUTPUT_TOKENS",
    "CHAT_ANSWER_OPENAI_REASONING_EFFORT",
    "CHAT_ANSWER_OPENAI_MAX_EVIDENCE_ITEMS",
    "CHAT_ANSWER_OPENAI_MAX_PROMPT_CHARS",
    "CHAT_ANSWER_OPENAI_INPUT_COST_PER_1M_TOKENS",
    "CHAT_ANSWER_OPENAI_OUTPUT_COST_PER_1M_TOKENS",
    "NOTIFICATION_DISPATCH_ENABLED",
    "PWA_VAPID_PUBLIC_KEY",
    "PWA_VAPID_PRIVATE_KEY",
    "PWA_VAPID_PRIVATE_KEY_FILE",
    "PWA_VAPID_SUBJECT",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_BOT_TOKEN_FILE",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_WEBHOOK_SECRET",
    "TELEGRAM_WEBHOOK_SECRET_FILE",
    "TELEGRAM_POLLING_ENABLED",
    "TELEGRAM_POLLING_TIMEOUT_SECONDS",
    "TELEGRAM_POLLING_INTERVAL_SECONDS",
    "TELEGRAM_POLLING_LIMIT",
    "TELEGRAM_POLLING_OFFSET_PATH",
    "TELEGRAM_POLLING_DELETE_WEBHOOK_ON_CONFLICT",
]


@pytest.fixture(autouse=True)
def clear_optional_settings_env(monkeypatch):
    for name in OPTIONAL_SETTINGS_ENV:
        monkeypatch.delenv(name, raising=False)


def test_load_settings_uses_db_first_defaults_without_mirror_env(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://pytest")

    settings = load_settings()

    assert settings.vault_path.as_posix() == "/vault"
    assert settings.repo_full_name == "local/llm-wiki"
    assert settings.mirror_git_push_enabled is False
    assert settings.db_note_run_root.as_posix() == "/data/db-note-runs"
    assert settings.telegram_polling_enabled is False
    assert settings.telegram_polling_timeout_seconds == 5
    assert settings.telegram_polling_interval_seconds == 2
    assert settings.telegram_polling_limit == 20
    assert settings.telegram_polling_offset_path.as_posix() == "/data/telegram-polling-offset.json"
    assert settings.telegram_polling_delete_webhook_on_conflict is True
    assert settings.daily_digest_enabled is False
    assert settings.personalization_default_workflow_mode == "generic"


def test_load_settings_accepts_generic_repo_full_name(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://pytest")
    monkeypatch.setenv("APP_REPO_FULL_NAME", "example-owner/example-notes")

    settings = load_settings()

    assert settings.repo_full_name == "example-owner/example-notes"


def test_load_settings_prefers_mirror_path_over_legacy_vault_path(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://pytest")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "legacy-vault"))
    monkeypatch.setenv("MIRROR_PATH", str(tmp_path / "mirror"))

    settings = load_settings()

    assert settings.vault_path == tmp_path / "mirror"


def test_load_settings_prefers_standard_s3_names_with_legacy_aliases(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://pytest")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setenv("S3_BUCKET_NAME", "legacy-bucket")
    monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.setenv("S3_ACCESS_KEY", "legacy-access")
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setenv("S3_SECRET_KEY", "legacy-secret")

    legacy = load_settings()

    assert legacy.s3_bucket == "legacy-bucket"
    assert legacy.s3_access_key_id == "legacy-access"
    assert legacy.s3_secret_access_key == "legacy-secret"

    monkeypatch.setenv("S3_BUCKET", "standard-bucket")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "standard-access")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "standard-secret")

    standard = load_settings()

    assert standard.s3_bucket == "standard-bucket"
    assert standard.s3_access_key_id == "standard-access"
    assert standard.s3_secret_access_key == "standard-secret"


def test_load_settings_parses_openai_api_runner_controls(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://pytest")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("OPENAI_API_RUNNER_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_MODEL", "gpt-5.5")
    monkeypatch.setenv("OPENAI_API_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("OPENAI_API_MAX_OUTPUT_TOKENS", "4096")
    monkeypatch.setenv("OPENAI_API_REASONING_EFFORT", "medium")
    chat_key = tmp_path / "chat-openai-key"
    chat_key.write_text("chat-secret", encoding="utf-8")
    monkeypatch.setenv("CHAT_ANSWER_PROVIDER", "openai-api")
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_MODEL", "gpt-chat")
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_API_KEY_FILE", str(chat_key))
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_MAX_OUTPUT_TOKENS", "900")
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_REASONING_EFFORT", "high")
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_MAX_EVIDENCE_ITEMS", "7")
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_MAX_PROMPT_CHARS", "12000")
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_INPUT_COST_PER_1M_TOKENS", "0.25")
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_OUTPUT_COST_PER_1M_TOKENS", "2.0")
    monkeypatch.setenv("WORKER_RUNNER", "codex-cli")
    monkeypatch.setenv("DB_NOTE_RUN_ROOT", str(tmp_path / "db-note-runs"))
    monkeypatch.setenv("WORKER_DB_NOTE_AUTO_EXPORT_ENABLED", "true")
    monkeypatch.setenv("MIRROR_GIT_PUSH_ENABLED", "true")
    monkeypatch.setenv("TIME_SUGGESTION_AUTO_REGISTER_ENABLED", "true")
    monkeypatch.setenv("APP_DEFAULT_WORKFLOW_MODE", "personal")
    vapid_private = tmp_path / "vapid-private.pem"
    vapid_private.write_text("private-key", encoding="utf-8")
    telegram_token = tmp_path / "telegram-token"
    telegram_token.write_text("telegram-secret", encoding="utf-8")
    telegram_webhook = tmp_path / "telegram-webhook"
    telegram_webhook.write_text("webhook-secret", encoding="utf-8")
    monkeypatch.setenv("NOTIFICATION_DISPATCH_ENABLED", "true")
    monkeypatch.setenv("PWA_VAPID_PUBLIC_KEY", "public-key")
    monkeypatch.setenv("PWA_VAPID_PRIVATE_KEY_FILE", str(vapid_private))
    monkeypatch.setenv("PWA_VAPID_SUBJECT", "mailto:test@example.com")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(telegram_token))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_FILE", str(telegram_webhook))
    monkeypatch.setenv("TELEGRAM_POLLING_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_POLLING_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("TELEGRAM_POLLING_INTERVAL_SECONDS", "3")
    monkeypatch.setenv("TELEGRAM_POLLING_LIMIT", "11")
    monkeypatch.setenv("TELEGRAM_POLLING_OFFSET_PATH", str(tmp_path / "telegram-offset.json"))
    monkeypatch.setenv("TELEGRAM_POLLING_DELETE_WEBHOOK_ON_CONFLICT", "false")

    settings = load_settings()

    assert settings.worker_runner == "codex-cli"
    assert settings.db_note_run_root == tmp_path / "db-note-runs"
    assert settings.openai_api_runner_enabled is True
    assert settings.openai_api_model == "gpt-5.5"
    assert settings.openai_api_timeout_seconds == 120
    assert settings.openai_api_max_output_tokens == 4096
    assert settings.openai_api_reasoning_effort == "medium"
    assert settings.chat_answer_provider == "openai-api"
    assert settings.chat_answer_openai_model == "gpt-chat"
    assert settings.chat_answer_openai_api_key == "chat-secret"
    assert settings.chat_answer_openai_timeout_seconds == 30
    assert settings.chat_answer_openai_max_output_tokens == 900
    assert settings.chat_answer_openai_reasoning_effort == "high"
    assert settings.chat_answer_openai_max_evidence_items == 7
    assert settings.chat_answer_openai_max_prompt_chars == 12000
    assert settings.chat_answer_openai_input_cost_per_1m_tokens == 0.25
    assert settings.chat_answer_openai_output_cost_per_1m_tokens == 2.0
    assert settings.worker_db_note_auto_export_enabled is True
    assert settings.mirror_git_push_enabled is True
    assert settings.time_suggestion_auto_register_enabled is True
    assert settings.daily_digest_enabled is False
    assert settings.personalization_default_workflow_mode == "personal"
    assert settings.notification_dispatch_enabled is True
    assert settings.pwa_vapid_public_key == "public-key"
    assert settings.pwa_vapid_private_key == "private-key"
    assert settings.pwa_vapid_subject == "mailto:test@example.com"
    assert settings.telegram_bot_token == "telegram-secret"
    assert settings.telegram_chat_id == "1234"
    assert settings.telegram_webhook_secret == "webhook-secret"
    assert settings.telegram_polling_enabled is True
    assert settings.telegram_polling_timeout_seconds == 7
    assert settings.telegram_polling_interval_seconds == 3
    assert settings.telegram_polling_limit == 11
    assert settings.telegram_polling_offset_path == tmp_path / "telegram-offset.json"
    assert settings.telegram_polling_delete_webhook_on_conflict is False


def test_load_settings_parses_daily_digest_enabled(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://pytest")
    monkeypatch.setenv("DAILY_DIGEST_ENABLED", "true")

    settings = load_settings()

    assert settings.daily_digest_enabled is True


def test_load_settings_defaults_chat_answer_model_independent_from_worker_model(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://pytest")
    monkeypatch.setenv("OPENAI_API_MODEL", "gpt-5.5")
    monkeypatch.setenv("OPENAI_API_REASONING_EFFORT", "high")
    monkeypatch.delenv("CHAT_ANSWER_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CHAT_ANSWER_OPENAI_REASONING_EFFORT", raising=False)

    settings = load_settings()

    assert settings.openai_api_model == "gpt-5.5"
    assert settings.openai_api_reasoning_effort == "high"
    assert settings.chat_answer_openai_model == DEFAULT_CHAT_ANSWER_OPENAI_MODEL
    assert settings.chat_answer_openai_reasoning_effort == "low"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APP_API_TOKEN", "change-me"),
        ("APP_PLUGIN_TOKEN", "change-me-client"),
        ("APP_ADMIN_TOKEN", "change-me-admin"),
        ("APP_ADMIN_TOKEN", "placeholder"),
        ("APP_PLUGIN_TOKEN", "replace-me-client"),
    ],
)
def test_load_settings_rejects_placeholder_app_tokens(monkeypatch, name, value):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://pytest")
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=name):
        load_settings()


def test_load_settings_rejects_invalid_openai_api_runner_controls(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://pytest")
    monkeypatch.setenv("OPENAI_API_RUNNER_ENABLED", "maybe")

    with pytest.raises(RuntimeError, match="Invalid boolean environment variable"):
        load_settings()

    monkeypatch.setenv("OPENAI_API_RUNNER_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_REASONING_EFFORT", "maximum")

    with pytest.raises(RuntimeError, match="OPENAI_API_REASONING_EFFORT"):
        load_settings()

    monkeypatch.setenv("OPENAI_API_REASONING_EFFORT", "low")
    monkeypatch.setenv("CHAT_ANSWER_PROVIDER", "codex-cli")

    with pytest.raises(RuntimeError, match="CHAT_ANSWER_PROVIDER"):
        load_settings()

    monkeypatch.setenv("CHAT_ANSWER_PROVIDER", "openai-api")
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_REASONING_EFFORT", "maximum")

    with pytest.raises(RuntimeError, match="CHAT_ANSWER_OPENAI_REASONING_EFFORT"):
        load_settings()

    monkeypatch.setenv("CHAT_ANSWER_OPENAI_REASONING_EFFORT", "low")
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_MAX_PROMPT_CHARS", "999")

    with pytest.raises(RuntimeError, match="CHAT_ANSWER_OPENAI_MAX_PROMPT_CHARS"):
        load_settings()

    monkeypatch.setenv("CHAT_ANSWER_OPENAI_MAX_PROMPT_CHARS", "24000")
    monkeypatch.setenv("APP_DEFAULT_WORKFLOW_MODE", "private")

    with pytest.raises(RuntimeError, match="APP_DEFAULT_WORKFLOW_MODE"):
        load_settings()

    monkeypatch.setenv("APP_DEFAULT_WORKFLOW_MODE", "generic")
    monkeypatch.setenv("CHAT_ANSWER_OPENAI_INPUT_COST_PER_1M_TOKENS", "free")

    with pytest.raises(RuntimeError, match="CHAT_ANSWER_OPENAI_INPUT_COST_PER_1M_TOKENS"):
        load_settings()

    monkeypatch.setenv("CHAT_ANSWER_OPENAI_INPUT_COST_PER_1M_TOKENS", "-1")

    with pytest.raises(RuntimeError, match="CHAT_ANSWER_OPENAI_INPUT_COST_PER_1M_TOKENS"):
        load_settings()
