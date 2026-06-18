from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import llm_wiki.cli as cli
import pytest
from llm_wiki.cli import build_parser


def test_worker_parser_accepts_openai_api_runner():
    args = build_parser().parse_args(["worker", "--runner", "openai-api"])

    assert args.runner == "openai-api"


def test_worker_status_includes_db_note_auto_export_and_notifications(monkeypatch, capsys, tmp_path):
    settings = SimpleNamespace(
        worker_max_attempts=3,
        worker_retry_backoff_seconds=300,
        worker_heartbeat_interval=15,
        worker_runner="codex-cli",
        db_note_run_root=tmp_path / "db-note-runs",
        vault_path=tmp_path / "mirror",
        worker_db_note_auto_export_enabled=True,
        mirror_git_push_enabled=False,
        openai_api_runner_enabled=False,
        openai_api_model="gpt-5.5",
        openai_api_timeout_seconds=1800,
        openai_api_max_output_tokens=8192,
        openai_api_reasoning_effort="low",
        time_suggestion_auto_register_enabled=True,
        notification_dispatch_enabled=True,
        pwa_vapid_public_key="public-key",
        pwa_vapid_private_key="private-key",
        telegram_bot_token=None,
        telegram_chat_id=None,
        telegram_polling_enabled=True,
        telegram_polling_timeout_seconds=5,
        telegram_polling_interval_seconds=2,
        telegram_polling_limit=20,
        telegram_polling_offset_path=tmp_path / "telegram-offset.json",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "count_requests_by_status", lambda loaded_settings: {})
    monkeypatch.setattr(cli, "list_worker_state", lambda loaded_settings: [])

    args = build_parser().parse_args(["worker-status"])
    args.func(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["worker_db_note_auto_export_enabled"] is True
    assert payload["db_note_run_root"] == str(tmp_path / "db-note-runs")
    assert payload["mirror_path"] == str(tmp_path / "mirror")
    assert payload["mirror_git_push_enabled"] is False
    assert payload["time_suggestion_auto_register_enabled"] is True
    assert payload["notification_dispatch_enabled"] is True
    assert payload["pwa_push_configured"] is True
    assert payload["telegram_configured"] is False
    assert payload["telegram_polling_enabled"] is True
    assert payload["telegram_polling_offset_path"] == str(tmp_path / "telegram-offset.json")


def test_telegram_poll_parser_and_once_command(monkeypatch, capsys, tmp_path):
    captured = {}
    settings = SimpleNamespace(telegram_polling_offset_path=tmp_path / "telegram-offset.json")
    settings.telegram_polling_offset_path.write_text('{"offset": 40}', encoding="utf-8")

    def fake_poll(settings, *, offset, timeout_seconds, limit, offset_callback):
        captured.update({"settings": settings, "offset": offset, "timeout_seconds": timeout_seconds, "limit": limit})
        offset_callback(42)
        return {"status": "ok", "fetched": 0, "handled": 0}

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "poll_telegram_updates", fake_poll)
    args = build_parser().parse_args(["telegram-poll", "--once", "--timeout", "0", "--limit", "3"])

    args.func(args)

    assert captured == {"settings": settings, "offset": 40, "timeout_seconds": 0, "limit": 3}
    assert json.loads(settings.telegram_polling_offset_path.read_text(encoding="utf-8"))["offset"] == 42
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_telegram_poll_loop_command_passes_runtime_options(monkeypatch):
    captured = {}

    def fake_loop(settings, *, interval, timeout_seconds, limit):
        captured.update(
            {
                "settings": settings,
                "interval": interval,
                "timeout_seconds": timeout_seconds,
                "limit": limit,
            }
        )

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "run_telegram_polling_loop", fake_loop)
    args = build_parser().parse_args(["telegram-poll", "--interval", "4", "--timeout", "7", "--limit", "1"])

    args.func(args)

    assert captured == {"settings": "settings", "interval": 4, "timeout_seconds": 7, "limit": 1}


def test_chat_cleanup_parser_and_command(monkeypatch, capsys):
    captured = {}

    def fake_purge(*, older_than_days, limit, dry_run, settings):
        captured.update(
            {
                "older_than_days": older_than_days,
                "limit": limit,
                "dry_run": dry_run,
                "settings": settings,
            }
        )
        return {"purged_sessions": 0, "matched_sessions": 2}

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "purge_deleted_chat_sessions", fake_purge)
    args = build_parser().parse_args(
        [
            "chat-cleanup",
            "--deleted-retention-days",
            "14",
            "--limit",
            "25",
            "--dry-run",
        ]
    )

    args.func(args)

    assert captured == {
        "older_than_days": 14,
        "limit": 25,
        "dry_run": True,
        "settings": "settings",
    }
    assert json.loads(capsys.readouterr().out)["matched_sessions"] == 2


def test_data_lifecycle_report_parser_and_command(monkeypatch, capsys):
    captured = {}

    def fake_report(settings, *, deleted_chat_retention_days, stale_draft_days):
        captured.update(
            {
                "settings": settings,
                "deleted_chat_retention_days": deleted_chat_retention_days,
                "stale_draft_days": stale_draft_days,
            }
        )
        return {"notes": {"total": 1}, "recommended_actions": []}

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "build_data_lifecycle_report", fake_report)
    args = build_parser().parse_args(
        [
            "data-lifecycle-report",
            "--deleted-chat-retention-days",
            "14",
            "--stale-draft-days",
            "5",
        ]
    )

    args.func(args)

    assert captured == {
        "settings": "settings",
        "deleted_chat_retention_days": 14,
        "stale_draft_days": 5,
    }
    assert json.loads(capsys.readouterr().out)["notes"]["total"] == 1


def test_demo_seed_parser_and_command(monkeypatch, capsys):
    captured = {}

    def fake_create_demo_seed(settings, *, anchor_date, with_notifications):
        captured.update(
            {
                "settings": settings,
                "anchor_date": anchor_date,
                "with_notifications": with_notifications,
            }
        )
        return {"seed": "public-demo", "anchor_date": anchor_date.isoformat()}

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "create_demo_seed", fake_create_demo_seed)
    args = build_parser().parse_args(
        [
            "demo-seed",
            "--anchor-date",
            "2026-07-01",
            "--with-notifications",
        ]
    )

    args.func(args)

    assert captured["settings"] == "settings"
    assert captured["anchor_date"].isoformat() == "2026-07-01"
    assert captured["with_notifications"] is True
    assert json.loads(capsys.readouterr().out)["seed"] == "public-demo"


def test_request_list_parser_accepts_dashboard_filter_shape():
    args = build_parser().parse_args(
        [
            "request-list",
            "--status",
            "failed",
            "--source",
            "plugin-quick-capture",
            "--query",
            "inbox/mobile",
            "--limit",
            "30",
        ]
    )

    assert args.status == "failed"
    assert args.source == "plugin-quick-capture"
    assert args.query == "inbox/mobile"
    assert args.limit == 30


def test_request_sources_parser():
    args = build_parser().parse_args(["request-sources"])

    assert args.func


def test_request_review_set_parser_and_command(monkeypatch, capsys):
    captured = {}

    def fake_set_request_review(request_id, *, outcome, note, reviewed_by, settings):
        captured.update(
            {
                "request_id": request_id,
                "outcome": outcome,
                "note": note,
                "reviewed_by": reviewed_by,
                "settings": settings,
            }
        )
        return {"request_id": request_id, "outcome": outcome, "note": note, "reviewed_by": reviewed_by}

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "set_request_review", fake_set_request_review)
    args = build_parser().parse_args(
        [
            "request-review-set",
            "req_test_review",
            "--outcome",
            "manual_rewrite",
            "--note",
            "too noisy",
            "--reviewed-by",
            "pmk",
        ]
    )

    args.func(args)

    assert captured == {
        "request_id": "req_test_review",
        "outcome": "manual_rewrite",
        "note": "too noisy",
        "reviewed_by": "pmk",
        "settings": "settings",
    }
    assert json.loads(capsys.readouterr().out)["outcome"] == "manual_rewrite"


def test_request_review_list_parser_and_command(monkeypatch, capsys):
    captured = {}

    def fake_list_request_reviews(*, outcome, needs_review, poor, limit, settings):
        captured.update(
            {
                "outcome": outcome,
                "needs_review": needs_review,
                "poor": poor,
                "limit": limit,
                "settings": settings,
            }
        )
        return [{"id": "req_test_review", "review_outcome": "unsafe"}]

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "list_request_reviews", fake_list_request_reviews)
    args = build_parser().parse_args(["request-review-list", "--poor", "--limit", "5"])

    args.func(args)

    assert captured == {
        "outcome": None,
        "needs_review": False,
        "poor": True,
        "limit": 5,
        "settings": "settings",
    }
    assert json.loads(capsys.readouterr().out)[0]["review_outcome"] == "unsafe"


def test_note_create_parser_and_command(monkeypatch, capsys, tmp_path):
    captured = {}
    body_file = tmp_path / "note.md"
    body_file.write_text("note body", encoding="utf-8")

    def fake_create_note(payload, settings):
        captured.update({"payload": payload, "settings": settings})
        return {"id": "note_test_cli", "title": payload["title"], "version": 1}

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "create_note", fake_create_note)
    args = build_parser().parse_args(
        [
            "note-create",
            "--title",
            "CLI Note",
            "--kind",
            "inbox",
            "--status",
            "draft",
            "--body-file",
            str(body_file),
            "--metadata-json",
            '{"source":"pytest"}',
            "--change-source",
            "test",
            "--created-by",
            "pytest",
        ]
    )

    args.func(args)

    assert captured["settings"] == "settings"
    assert captured["payload"]["title"] == "CLI Note"
    assert captured["payload"]["body_markdown"] == "note body"
    assert captured["payload"]["metadata"] == {"source": "pytest"}
    assert captured["payload"]["change_source"] == "test"
    assert json.loads(capsys.readouterr().out)["id"] == "note_test_cli"


def test_note_update_parser_and_command(monkeypatch, capsys):
    captured = {}

    def fake_update_note(note_id, **kwargs):
        captured.update({"note_id": note_id, **kwargs})
        return {"id": note_id, "version": 3, "body_markdown": kwargs["body_markdown"]}

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "update_note", fake_update_note)
    args = build_parser().parse_args(
        [
            "note-update",
            "note_test_cli",
            "--expected-version",
            "2",
            "--body",
            "updated",
            "--metadata-json",
            '{"state":"done"}',
            "--change-source",
            "test",
        ]
    )

    args.func(args)

    assert captured["note_id"] == "note_test_cli"
    assert captured["expected_version"] == 2
    assert captured["body_markdown"] == "updated"
    assert captured["metadata"] == {"state": "done"}
    assert captured["settings"] == "settings"
    assert json.loads(capsys.readouterr().out)["version"] == 3


def test_note_list_and_revisions_parsers(monkeypatch, capsys):
    captured = {}

    def fake_list_notes(*, kind, status, query, include_deleted, limit, settings):
        captured["list"] = {
            "kind": kind,
            "status": status,
            "query": query,
            "include_deleted": include_deleted,
            "limit": limit,
            "settings": settings,
        }
        return [{"id": "note_test_cli"}]

    def fake_list_note_revisions(note_id, *, limit, settings):
        captured["revisions"] = {"note_id": note_id, "limit": limit, "settings": settings}
        return [{"note_id": note_id, "version": 1}]

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "list_notes", fake_list_notes)
    monkeypatch.setattr(cli, "list_note_revisions", fake_list_note_revisions)

    list_args = build_parser().parse_args(
        ["note-list", "--kind", "inbox", "--status", "active", "--query", "hello", "--limit", "10"]
    )
    list_args.func(list_args)

    assert captured["list"] == {
        "kind": "inbox",
        "status": "active",
        "query": "hello",
        "include_deleted": False,
        "limit": 10,
        "settings": "settings",
    }
    assert json.loads(capsys.readouterr().out)[0]["id"] == "note_test_cli"

    revision_args = build_parser().parse_args(["note-revisions", "note_test_cli", "--limit", "5"])
    revision_args.func(revision_args)

    assert captured["revisions"] == {"note_id": "note_test_cli", "limit": 5, "settings": "settings"}
    assert json.loads(capsys.readouterr().out)[0]["version"] == 1


def test_source_readable_backfill_parser_and_command(monkeypatch, capsys):
    captured = {}

    def fake_queue_source_readable_reanalysis(settings, *, limit, dry_run, created_by):
        captured.update(
            {
                "settings": settings,
                "limit": limit,
                "dry_run": dry_run,
                "created_by": created_by,
            }
        )
        return {"matched": 2, "queued": 2}

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "queue_source_readable_reanalysis", fake_queue_source_readable_reanalysis)
    args = build_parser().parse_args(
        [
            "source-readable-backfill",
            "--limit",
            "25",
            "--dry-run",
            "--created-by",
            "pytest",
        ]
    )

    args.func(args)

    assert captured == {"settings": "settings", "limit": 25, "dry_run": True, "created_by": "pytest"}
    assert json.loads(capsys.readouterr().out)["matched"] == 2


def test_promoted_targets_refresh_parser_and_command(monkeypatch, capsys):
    captured = {}

    def fake_refresh_promoted_target_source_sections(settings):
        captured["settings"] = settings
        return {"count": 1, "refreshed": ["note_topic"]}

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "refresh_promoted_target_source_sections", fake_refresh_promoted_target_source_sections)
    args = build_parser().parse_args(["promoted-targets-refresh"])

    args.func(args)

    assert captured == {"settings": "settings"}
    assert json.loads(capsys.readouterr().out)["refreshed"] == ["note_topic"]


def test_notes_export_parser_and_command(monkeypatch, capsys):
    captured = {}

    def fake_export_notes_to_markdown(settings, *, scope, note_id, dry_run, sync, push, reconcile):
        captured.update(
            {
                "settings": settings,
                "scope": scope,
                "note_id": note_id,
                "dry_run": dry_run,
                "sync": sync,
                "push": push,
                "reconcile": reconcile,
            }
        )
        return {"status": "dry_run", "exported_count": 1}

    class FakeSettings:
        mirror_git_push_enabled = True

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "export_notes_to_markdown", fake_export_notes_to_markdown)
    args = build_parser().parse_args(["notes-export", "--note-id", "note_test_cli", "--dry-run", "--no-sync", "--no-push"])

    args.func(args)

    assert captured == {
        "settings": "settings",
        "scope": "note-id",
        "note_id": "note_test_cli",
        "dry_run": True,
        "sync": False,
        "push": False,
        "reconcile": False,
    }
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"

    captured.clear()
    monkeypatch.setattr(cli, "load_settings", lambda: FakeSettings())
    args = build_parser().parse_args(["notes-export", "--scope", "full", "--dry-run", "--reconcile", "--local-only"])

    args.func(args)

    assert captured["scope"] == "full"
    assert captured["sync"] is False
    assert captured["push"] is False
    assert captured["reconcile"] is True


def test_notes_import_parser_and_command(monkeypatch, capsys):
    captured = {}

    def fake_import_vault_notes(from_vault, *, mode, settings):
        captured.update({"from_vault": str(from_vault), "mode": mode, "settings": settings})
        return {"mode": mode, "importable_count": 1}

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "import_vault_notes", fake_import_vault_notes)
    args = build_parser().parse_args(["notes-import", "--from-vault", "/vault", "--mode", "dry-run"])

    args.func(args)

    assert Path(captured["from_vault"]).as_posix() == "/vault"
    assert captured["mode"] == "dry-run"
    assert captured["settings"] == "settings"
    assert json.loads(capsys.readouterr().out)["importable_count"] == 1


def test_ops_health_parser_and_command(monkeypatch, capsys):
    captured = {}

    def fake_build_health_summary(settings, **kwargs):
        captured.update({"settings": settings, **kwargs})
        return {"status": "OK", "checks": []}

    monkeypatch.setattr(cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(cli, "build_health_summary", fake_build_health_summary)
    args = build_parser().parse_args(
        [
            "ops-health",
            "--api-url",
            "http://api:8080/health",
            "--backup-dir",
            "/backups",
            "--codex-login-log",
            "/backups/codex-login-status.log",
            "--exit-status",
        ]
    )

    with pytest.raises(SystemExit) as exc:
        args.func(args)

    assert exc.value.code == 0
    assert captured["settings"] == "settings"
    assert isinstance(captured["backup_dir"], Path)
    assert captured["backup_dir"].name == "backups"
    assert captured["api_url"] == "http://api:8080/health"
    assert json.loads(capsys.readouterr().out)["status"] == "OK"


def test_backup_defaults_to_db_and_object_artifacts_without_repo_bundle(monkeypatch, capsys, tmp_path):
    calls = []
    settings = SimpleNamespace(database_url="postgresql://source:secret@app-db/llm_wiki", vault_path=tmp_path / "mirror")

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "create_repo_mirror_backup", lambda *args, **kwargs: calls.append("repo") or tmp_path / "repo.bundle")
    monkeypatch.setattr(
        cli,
        "create_postgres_dump",
        lambda target, loaded_settings: calls.append(("postgres", target, loaded_settings)) or tmp_path / "dump.sql",
    )
    monkeypatch.setattr(
        cli,
        "create_object_manifest",
        lambda target, loaded_settings, *, verify, source: calls.append(("manifest", verify, source))
        or tmp_path
        / "objects.json",
    )
    monkeypatch.setattr(
        cli,
        "create_object_archive",
        lambda target, loaded_settings, *, source: calls.append(("archive", source)) or tmp_path / "objects.tar.gz",
    )
    monkeypatch.setattr(
        cli,
        "restore_smoke_postgres_dump",
        lambda dump, url, *, source_database_url: calls.append(("restore-db", dump, url, source_database_url))
        or {"ok": True},
    )
    monkeypatch.setattr(
        cli,
        "restore_smoke_markdown_export",
        lambda target, *, database_url, settings: calls.append(("restore-mirror", target, database_url)) or {"ok": True},
    )
    monkeypatch.setattr(
        cli,
        "restore_smoke_object_archive",
        lambda archive, target: calls.append(("restore-objects", archive, target)) or {"ok": True},
    )

    args = build_parser().parse_args(
        [
            "backup",
            "--target",
            str(tmp_path / "backups"),
            "--postgres",
            "--object-manifest",
            "--verify-objects",
            "--object-data",
            "--restore-smoke",
            "--db-restore-url",
            "postgresql://restore:secret@restore-db/restore",
            "--mirror-restore-target",
            str(tmp_path / "restore-mirror"),
            "--object-restore-target",
            str(tmp_path / "restore-objects"),
        ]
    )

    args.func(args)

    payload = json.loads(capsys.readouterr().out)
    assert "repo_bundle" not in payload
    assert "repo" not in calls
    assert ("manifest", True, "db") in calls
    assert ("archive", "db") in calls
    assert payload["restore_smoke"]["postgres"]["ok"] is True
    assert payload["restore_smoke"]["markdown_export"]["ok"] is True
    assert payload["restore_smoke"]["object_archive"]["ok"] is True


def test_restore_smoke_parser_supports_db_and_object_without_repo_bundle(monkeypatch, capsys, tmp_path):
    settings = SimpleNamespace(database_url="postgresql://source:secret@app-db/llm_wiki")
    captured = []

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "restore_smoke_postgres_dump",
        lambda dump, url, *, source_database_url: captured.append(("db", dump, url, source_database_url))
        or {"ok": True},
    )
    monkeypatch.setattr(
        cli,
        "restore_smoke_object_archive",
        lambda archive, target: captured.append(("object", archive, target)) or {"ok": True},
    )

    args = build_parser().parse_args(
        [
            "restore-smoke",
            "--postgres-dump",
            str(tmp_path / "dump.sql"),
            "--db-restore-url",
            "postgresql://restore:secret@restore-db/restore",
            "--object-archive",
            str(tmp_path / "objects.tar.gz"),
            "--object-restore-target",
            str(tmp_path / "restore-objects"),
        ]
    )

    args.func(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["postgres"]["ok"] is True
    assert payload["object_archive"]["ok"] is True
    assert captured[0][0] == "db"
    assert captured[1][0] == "object"


def test_backup_restore_smoke_failure_exits_before_retention(monkeypatch, capsys, tmp_path):
    calls = []
    settings = SimpleNamespace(database_url="postgresql://source:secret@app-db/llm_wiki", vault_path=tmp_path / "mirror")

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "create_postgres_dump", lambda target, loaded_settings: tmp_path / "dump.sql")
    monkeypatch.setattr(
        cli,
        "restore_smoke_postgres_dump",
        lambda dump, url, *, source_database_url: {"ok": False, "reason": "restore failed"},
    )
    monkeypatch.setattr(
        cli,
        "cleanup_old_backups",
        lambda target, *, older_than_days: calls.append("retention") or [],
    )

    args = build_parser().parse_args(
        [
            "backup",
            "--target",
            str(tmp_path / "backups"),
            "--postgres",
            "--restore-smoke",
            "--db-restore-url",
            "postgresql://restore:secret@restore-db/restore",
            "--retention-days",
            "30",
        ]
    )

    with pytest.raises(SystemExit) as exc:
        args.func(args)

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert payload["restore_smoke"]["postgres"]["ok"] is False
    assert calls == []
