from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from llm_wiki.config import Settings
from llm_wiki.ops_health import build_health_summary, health_exit_code


def test_build_health_summary_ok(tmp_path: Path):
    now = datetime(2026, 6, 3, 1, 0, tzinfo=timezone.utc)
    backup_dir = _write_primary_backups(tmp_path, now)
    login_log = tmp_path / "backups" / "codex-login-status.log"
    login_log.write_text("Logged in using ChatGPT\n", encoding="utf-8")
    os.utime(login_log, (now.timestamp(), now.timestamp()))

    summary = build_health_summary(
        _settings(tmp_path),
        api_url="http://api:8080/health",
        backup_dir=backup_dir,
        codex_login_log=login_log,
        now=now,
        request_counter=lambda _settings: [{"status": "queued", "count": 1}, {"status": "failed", "count": 0}],
        worker_lister=lambda _settings: [
            {"key": "worker:pytest", "value": {"worker_id": "pytest", "state": "idle"}, "updated_at": now}
        ],
        url_checker=lambda url: (url == "http://api:8080/health", "api ok"),
    )

    assert summary["status"] == "OK"
    assert health_exit_code(summary["status"]) == 0
    assert {check["name"] for check in summary["checks"]} == {
        "api_health",
        "db",
        "request_queue",
        "worker_heartbeat",
        "backup_age",
        "codex_login_check",
    }
    rendered = str(summary)
    assert "postgresql://unused" not in rendered
    assert "content_snapshot" not in rendered
    assert "secret" not in rendered.lower()


def test_build_health_summary_warns_for_failed_requests(tmp_path: Path):
    now = datetime(2026, 6, 3, 1, 0, tzinfo=timezone.utc)
    backup_dir = _write_primary_backups(tmp_path, now)
    login_log = tmp_path / "backups" / "codex-login-status.log"
    login_log.write_text("Logged in using ChatGPT\n", encoding="utf-8")
    os.utime(login_log, (now.timestamp(), now.timestamp()))

    summary = build_health_summary(
        _settings(tmp_path),
        backup_dir=backup_dir,
        codex_login_log=login_log,
        now=now,
        request_counter=lambda _settings: [{"status": "failed", "count": 1}],
        worker_lister=lambda _settings: [
            {"key": "worker:pytest", "value": {"worker_id": "pytest", "state": "idle"}, "updated_at": now}
        ],
    )

    assert summary["status"] == "WARN"
    assert health_exit_code(summary["status"]) == 1
    assert _check(summary, "request_queue")["status"] == "WARN"


def test_build_health_summary_critical_for_stale_worker_and_missing_backup(tmp_path: Path):
    now = datetime(2026, 6, 3, 1, 0, tzinfo=timezone.utc)
    login_log = tmp_path / "codex-login-status.log"
    login_log.write_text("Not logged in\n", encoding="utf-8")
    os.utime(login_log, (now.timestamp(), now.timestamp()))

    summary = build_health_summary(
        _settings(tmp_path),
        api_url="http://api:8080/health",
        backup_dir=tmp_path / "missing-backups",
        codex_login_log=login_log,
        now=now,
        request_counter=lambda _settings: [],
        worker_lister=lambda _settings: [],
        url_checker=lambda _url: (False, "api failed"),
    )

    assert summary["status"] == "CRITICAL"
    assert health_exit_code(summary["status"]) == 2
    assert _check(summary, "api_health")["status"] == "CRITICAL"
    assert _check(summary, "worker_heartbeat")["status"] == "CRITICAL"
    assert _check(summary, "backup_age")["status"] == "CRITICAL"
    assert _check(summary, "codex_login_check")["status"] == "CRITICAL"


def test_build_health_summary_critical_when_primary_backup_artifact_missing(tmp_path: Path):
    now = datetime(2026, 6, 3, 1, 0, tzinfo=timezone.utc)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "llm-wiki-app-db-20260603T010000Z.sql").write_text("dump", encoding="utf-8")
    login_log = backup_dir / "codex-login-status.log"
    login_log.write_text("Logged in using ChatGPT\n", encoding="utf-8")

    summary = build_health_summary(
        _settings(tmp_path),
        backup_dir=backup_dir,
        codex_login_log=login_log,
        now=now,
        request_counter=lambda _settings: [],
        worker_lister=lambda _settings: [
            {"key": "worker:pytest", "value": {"worker_id": "pytest", "state": "idle"}, "updated_at": now}
        ],
    )

    backup_check = _check(summary, "backup_age")
    assert backup_check["status"] == "CRITICAL"
    assert "object_manifest" in backup_check["data"]["missing"]


def test_build_health_summary_critical_when_latest_restore_smoke_failed(tmp_path: Path):
    now = datetime(2026, 6, 3, 1, 0, tzinfo=timezone.utc)
    backup_dir = _write_primary_backups(tmp_path, now, restore_ok=False)
    login_log = backup_dir / "codex-login-status.log"
    login_log.write_text("Logged in using ChatGPT\n", encoding="utf-8")

    summary = build_health_summary(
        _settings(tmp_path),
        backup_dir=backup_dir,
        codex_login_log=login_log,
        now=now,
        request_counter=lambda _settings: [],
        worker_lister=lambda _settings: [
            {"key": "worker:pytest", "value": {"worker_id": "pytest", "state": "idle"}, "updated_at": now}
        ],
    )

    backup_check = _check(summary, "backup_age")
    assert backup_check["status"] == "CRITICAL"
    assert backup_check["data"]["restore_smoke"] == "failed"


def _check(summary: dict, name: str) -> dict:
    return next(check for check in summary["checks"] if check["name"] == name)


def _write_primary_backups(tmp_path: Path, now: datetime, *, restore_ok: bool = True) -> Path:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(exist_ok=True)
    files = {
        "llm-wiki-app-db-20260603T010000Z.sql": "dump",
        "llm-wiki-objects-20260603T010000Z.json": "{}",
        "llm-wiki-objects-20260603T010000Z.tar.gz": "archive",
        "llm-wiki-backup-run-20260603T010000Z.json": json.dumps(
            {"restore_smoke": {"postgres": {"ok": restore_ok}, "object_archive": {"ok": restore_ok}}},
            ensure_ascii=False,
        ),
    }
    for name, content in files.items():
        path = backup_dir / name
        path.write_text(content, encoding="utf-8")
        os.utime(path, (now.timestamp(), now.timestamp()))
    return backup_dir


def _settings(tmp_path: Path) -> Settings:
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
