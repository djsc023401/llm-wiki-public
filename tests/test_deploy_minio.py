from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_app_compose_defines_optional_minio_profile() -> None:
    compose = (ROOT / "deploy" / "llm-wiki-app" / "docker-compose.yml").read_text(encoding="utf-8")

    assert "  minio:" in compose
    assert "  minio-init:" in compose
    assert "profiles:\n      - minio" in compose
    assert "condition: service_completed_successfully" in compose
    assert "required: false" in compose
    assert "mc mb --ignore-existing" in compose
    assert "raw assets extracted archive" in compose


def test_app_env_example_documents_builtin_minio_and_standard_s3_names() -> None:
    env_example = (ROOT / "deploy" / "llm-wiki-app" / ".env.example").read_text(encoding="utf-8")

    assert "S3_ENDPOINT=http://minio:9000" in env_example
    assert "S3_BUCKET=llm-wiki" in env_example
    assert "S3_ACCESS_KEY_ID=llm-wiki-minio" in env_example
    assert "S3_SECRET_ACCESS_KEY=change-me-minio-secret" in env_example
    assert "MINIO_ROOT_USER=llm-wiki-minio" in env_example
    assert "MINIO_ROOT_PASSWORD=change-me-minio-secret" in env_example
    assert "APP_BIND_ADDRESS=127.0.0.1" in env_example
    assert "MINIO_BIND_ADDRESS=127.0.0.1" in env_example
    assert "MINIO_CONSOLE_BIND_ADDRESS=127.0.0.1" in env_example
    assert "예제값은 실제 실행 시 거부됩니다" in env_example


def test_app_compose_binds_published_ports_to_loopback_by_default() -> None:
    compose = (ROOT / "deploy" / "llm-wiki-app" / "docker-compose.yml").read_text(encoding="utf-8")

    assert "${APP_BIND_ADDRESS:-127.0.0.1}:${APP_PORT:-8080}:8080" in compose
    assert "${MINIO_BIND_ADDRESS:-127.0.0.1}:${MINIO_API_PORT:-9000}:9000" in compose
    assert "${MINIO_CONSOLE_BIND_ADDRESS:-127.0.0.1}:${MINIO_CONSOLE_PORT:-9001}:9001" in compose
