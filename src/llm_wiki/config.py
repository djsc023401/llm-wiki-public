from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


DEFAULT_CHAT_ANSWER_OPENAI_MODEL = "gpt-5.4-mini"


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _optional_secret(name: str, file_name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    path = os.getenv(file_name)
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8").strip()
    return None


def _optional_app_token(name: str) -> str | None:
    value = os.getenv(name)
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if _is_placeholder_secret(cleaned):
        raise RuntimeError(f"Invalid placeholder secret for environment variable: {name}")
    return cleaned


def _is_placeholder_secret(value: str) -> bool:
    normalized = value.strip().lower().replace("_", "-")
    return (
        normalized in {"placeholder", "changeme", "change-me", "example", "example-secret", "example-token"}
        or normalized.startswith("change-me")
        or normalized.startswith("replace-me")
    )


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _env_alias(primary: str, legacy: str, default: str) -> str:
    return _first_env(primary, legacy) or default


def _int_env(name: str, default: int, *, min_value: int | None = None) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid integer environment variable: {name}={value}") from exc
    if min_value is not None and parsed < min_value:
        raise RuntimeError(f"Invalid integer environment variable: {name}={value}; expected >= {min_value}")
    return parsed


def _float_env(name: str, default: float | None = None, *, min_value: float | None = None) -> float | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid float environment variable: {name}={value}") from exc
    if min_value is not None and parsed < min_value:
        raise RuntimeError(f"Invalid float environment variable: {name}={value}; expected >= {min_value}")
    return parsed


def _choice_env(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default)
    if value not in choices:
        expected = ", ".join(sorted(choices))
        raise RuntimeError(f"Invalid environment variable: {name}={value}; expected one of {expected}")
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Invalid boolean environment variable: {name}={value}")


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_token: str | None
    vault_path: Path
    app_base_url: str
    repo_full_name: str
    s3_endpoint: str | None
    s3_bucket: str
    s3_access_key_id: str | None
    s3_secret_access_key: str | None
    s3_region: str
    worker_max_attempts: int
    worker_retry_backoff_seconds: int
    worker_heartbeat_interval: int
    db_note_run_root: Path = Path("/data/db-note-runs")
    worker_runner: str = "dry-run"
    worker_max_changed_files: int = 5
    worker_max_diff_bytes: int = 200_000
    worker_db_note_auto_export_enabled: bool = False
    mirror_git_push_enabled: bool = False
    api_plugin_token: str | None = None
    api_admin_token: str | None = None
    max_request_snapshot_bytes: int = 262_144
    max_attachment_bytes: int = 10 * 1024 * 1024
    openai_api_runner_enabled: bool = False
    openai_api_model: str | None = None
    openai_api_timeout_seconds: int = 1800
    openai_api_max_output_tokens: int = 8192
    openai_api_reasoning_effort: str = "low"
    chat_answer_provider: str = "rules"
    chat_answer_openai_model: str | None = DEFAULT_CHAT_ANSWER_OPENAI_MODEL
    chat_answer_openai_api_key: str | None = None
    chat_answer_openai_timeout_seconds: int = 60
    chat_answer_openai_max_output_tokens: int = 1200
    chat_answer_openai_reasoning_effort: str = "low"
    chat_answer_openai_max_evidence_items: int = 12
    chat_answer_openai_max_prompt_chars: int = 24_000
    chat_answer_openai_input_cost_per_1m_tokens: float | None = None
    chat_answer_openai_output_cost_per_1m_tokens: float | None = None
    personalization_default_workflow_mode: str = "generic"
    time_suggestion_auto_register_enabled: bool = False
    daily_digest_enabled: bool = False
    notification_dispatch_enabled: bool = True
    pwa_vapid_public_key: str | None = None
    pwa_vapid_private_key: str | None = None
    pwa_vapid_subject: str = "mailto:llm-wiki@example.local"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_webhook_secret: str | None = None
    telegram_polling_enabled: bool = False
    telegram_polling_timeout_seconds: int = 5
    telegram_polling_interval_seconds: int = 2
    telegram_polling_limit: int = 20
    telegram_polling_offset_path: Path = Path("/data/telegram-polling-offset.json")
    telegram_polling_delete_webhook_on_conflict: bool = True


def load_settings() -> Settings:
    return Settings(
        database_url=_env("APP_DATABASE_URL"),
        api_token=_optional_app_token("APP_API_TOKEN"),
        api_plugin_token=_optional_app_token("APP_PLUGIN_TOKEN"),
        api_admin_token=_optional_app_token("APP_ADMIN_TOKEN"),
        vault_path=Path(_env_alias("MIRROR_PATH", "VAULT_PATH", "/vault")),
        app_base_url=_env("APP_BASE_URL", "http://127.0.0.1:8080"),
        repo_full_name=_env("APP_REPO_FULL_NAME", "local/llm-wiki"),
        s3_endpoint=os.getenv("S3_ENDPOINT"),
        s3_bucket=_first_env("S3_BUCKET", "S3_BUCKET_NAME") or "llm-wiki",
        s3_access_key_id=_first_env("S3_ACCESS_KEY_ID", "S3_ACCESS_KEY"),
        s3_secret_access_key=(
            _optional_secret("S3_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY_FILE")
            or _optional_secret("S3_SECRET_KEY", "S3_SECRET_KEY_FILE")
        ),
        s3_region=_env("S3_REGION", "us-east-1"),
        worker_max_attempts=_int_env("WORKER_MAX_ATTEMPTS", 3, min_value=1),
        worker_retry_backoff_seconds=_int_env("WORKER_RETRY_BACKOFF_SECONDS", 300, min_value=0),
        worker_heartbeat_interval=_int_env("WORKER_HEARTBEAT_INTERVAL", 15, min_value=1),
        worker_runner=_choice_env("WORKER_RUNNER", "dry-run", {"dry-run", "codex-cli", "openai-api"}),
        db_note_run_root=Path(_env("DB_NOTE_RUN_ROOT", "/data/db-note-runs")),
        worker_max_changed_files=_int_env("WORKER_MAX_CHANGED_FILES", 5, min_value=1),
        worker_max_diff_bytes=_int_env("WORKER_MAX_DIFF_BYTES", 200_000, min_value=1),
        worker_db_note_auto_export_enabled=_bool_env("WORKER_DB_NOTE_AUTO_EXPORT_ENABLED", False),
        mirror_git_push_enabled=_bool_env("MIRROR_GIT_PUSH_ENABLED", False),
        max_request_snapshot_bytes=_int_env("APP_MAX_REQUEST_SNAPSHOT_BYTES", 262_144, min_value=1),
        max_attachment_bytes=_int_env("APP_MAX_ATTACHMENT_BYTES", 10 * 1024 * 1024, min_value=1),
        openai_api_runner_enabled=_bool_env("OPENAI_API_RUNNER_ENABLED", False),
        openai_api_model=os.getenv("OPENAI_API_MODEL"),
        openai_api_timeout_seconds=_int_env("OPENAI_API_TIMEOUT_SECONDS", 1800, min_value=1),
        openai_api_max_output_tokens=_int_env("OPENAI_API_MAX_OUTPUT_TOKENS", 8192, min_value=1),
        openai_api_reasoning_effort=_choice_env(
            "OPENAI_API_REASONING_EFFORT",
            "low",
            {"none", "low", "medium", "high", "xhigh"},
        ),
        chat_answer_provider=_choice_env("CHAT_ANSWER_PROVIDER", "rules", {"rules", "openai-api"}),
        chat_answer_openai_model=_first_env("CHAT_ANSWER_OPENAI_MODEL") or DEFAULT_CHAT_ANSWER_OPENAI_MODEL,
        chat_answer_openai_api_key=(
            _optional_secret("CHAT_ANSWER_OPENAI_API_KEY", "CHAT_ANSWER_OPENAI_API_KEY_FILE")
            or _optional_secret("OPENAI_API_KEY", "OPENAI_API_KEY_FILE")
        ),
        chat_answer_openai_timeout_seconds=_int_env("CHAT_ANSWER_OPENAI_TIMEOUT_SECONDS", 60, min_value=1),
        chat_answer_openai_max_output_tokens=_int_env("CHAT_ANSWER_OPENAI_MAX_OUTPUT_TOKENS", 1200, min_value=1),
        chat_answer_openai_reasoning_effort=_choice_env(
            "CHAT_ANSWER_OPENAI_REASONING_EFFORT",
            "low",
            {"none", "low", "medium", "high", "xhigh"},
        ),
        chat_answer_openai_max_evidence_items=_int_env(
            "CHAT_ANSWER_OPENAI_MAX_EVIDENCE_ITEMS",
            12,
            min_value=1,
        ),
        chat_answer_openai_max_prompt_chars=_int_env(
            "CHAT_ANSWER_OPENAI_MAX_PROMPT_CHARS",
            24_000,
            min_value=1000,
        ),
        chat_answer_openai_input_cost_per_1m_tokens=_float_env(
            "CHAT_ANSWER_OPENAI_INPUT_COST_PER_1M_TOKENS",
            None,
            min_value=0,
        ),
        chat_answer_openai_output_cost_per_1m_tokens=_float_env(
            "CHAT_ANSWER_OPENAI_OUTPUT_COST_PER_1M_TOKENS",
            None,
            min_value=0,
        ),
        personalization_default_workflow_mode=_choice_env(
            "APP_DEFAULT_WORKFLOW_MODE",
            "generic",
            {"generic", "personal"},
        ),
        time_suggestion_auto_register_enabled=_bool_env("TIME_SUGGESTION_AUTO_REGISTER_ENABLED", False),
        daily_digest_enabled=_bool_env("DAILY_DIGEST_ENABLED", False),
        notification_dispatch_enabled=_bool_env("NOTIFICATION_DISPATCH_ENABLED", True),
        pwa_vapid_public_key=os.getenv("PWA_VAPID_PUBLIC_KEY"),
        pwa_vapid_private_key=_optional_secret("PWA_VAPID_PRIVATE_KEY", "PWA_VAPID_PRIVATE_KEY_FILE"),
        pwa_vapid_subject=_env("PWA_VAPID_SUBJECT", "mailto:llm-wiki@example.local"),
        telegram_bot_token=_optional_secret("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN_FILE"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        telegram_webhook_secret=_optional_secret("TELEGRAM_WEBHOOK_SECRET", "TELEGRAM_WEBHOOK_SECRET_FILE"),
        telegram_polling_enabled=_bool_env("TELEGRAM_POLLING_ENABLED", False),
        telegram_polling_timeout_seconds=_int_env("TELEGRAM_POLLING_TIMEOUT_SECONDS", 5, min_value=0),
        telegram_polling_interval_seconds=_int_env("TELEGRAM_POLLING_INTERVAL_SECONDS", 2, min_value=0),
        telegram_polling_limit=_int_env("TELEGRAM_POLLING_LIMIT", 20, min_value=1),
        telegram_polling_offset_path=Path(_env("TELEGRAM_POLLING_OFFSET_PATH", "/data/telegram-polling-offset.json")),
        telegram_polling_delete_webhook_on_conflict=_bool_env("TELEGRAM_POLLING_DELETE_WEBHOOK_ON_CONFLICT", True),
    )
