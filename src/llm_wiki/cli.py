from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

from .api import ValidationError, run as run_api, validate_request_payload
from .backup import (
    cleanup_old_backups,
    create_object_archive,
    create_object_manifest,
    create_postgres_dump,
    create_repo_mirror_backup,
    restore_smoke_markdown_export,
    restore_smoke_bundle,
    restore_smoke_object_archive,
    restore_smoke_postgres_dump,
)
from .chat_store import purge_deleted_chat_sessions
from .config import load_settings
from .data_lifecycle import build_data_lifecycle_report
from .demo_seed import create_demo_seed
from .diff_detector import changed_files
from .export_mirror import export_notes_to_markdown
from .git_tools import run_git
from .migrations import migrate
from .notes_store import (
    EXPORT_SCOPES,
    NOTE_KINDS,
    NOTE_STATUSES,
    REVISION_SOURCES,
    create_note,
    get_note,
    list_note_revisions,
    list_notes,
    queue_source_readable_reanalysis,
    refresh_promoted_target_source_sections,
    update_note,
)
from .ops_health import build_health_summary, health_exit_code
from .requests_store import (
    REVIEW_OUTCOMES,
    cancel_request,
    count_requests_by_status,
    create_request,
    get_request,
    list_request_reviews,
    list_request_sources,
    list_requests,
    list_worker_state,
    retry_request,
    requeue_stale_running,
    set_request_review,
)
from .storage import head_object, upload_bytes
from .telegram_bot import _load_polling_offset, _save_polling_offset, poll_telegram_updates, run_telegram_polling_loop
from .vault_lint import lint_vault
from .vault_import import IMPORT_MODES, import_vault_notes
from .worker import loop as worker_loop, process_one


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _cmd_api(args) -> None:
    run_api(args.host, args.port)


def _cmd_migrate(_args) -> None:
    _print_json({"applied": migrate(load_settings())})


def _cmd_request(args) -> None:
    settings = load_settings()
    snapshot = None
    if args.content_snapshot_file:
        snapshot_path = Path(args.content_snapshot_file)
        if snapshot_path.stat().st_size > settings.max_request_snapshot_bytes:
            raise SystemExit(
                f"content snapshot exceeds APP_MAX_REQUEST_SNAPSHOT_BYTES ({settings.max_request_snapshot_bytes})"
            )
        snapshot = snapshot_path.read_text(encoding="utf-8")
    payload = {
        "source": args.source,
        "operation": args.operation,
        "file_path": args.file_path,
        "commit_sha": args.commit_sha,
        "content_hash": args.content_hash,
        "content_snapshot": snapshot,
        "sensitivity": args.sensitivity,
    }
    try:
        validated = validate_request_payload(payload, settings)
    except ValidationError as exc:
        raise SystemExit(f"invalid request: {exc.detail}") from exc
    _print_json(create_request(validated, settings))


def _cmd_request_get(args) -> None:
    row = get_request(args.request_id, load_settings())
    if not row:
        raise SystemExit(f"request not found: {args.request_id}")
    _print_json(row)


def _cmd_request_list(args) -> None:
    _print_json(
        list_requests(
            status=args.status,
            source=_clean_filter(args.source),
            query=_clean_filter(args.query),
            limit=args.limit,
            settings=load_settings(),
        )
    )


def _cmd_request_retry(args) -> None:
    settings = load_settings()
    row = retry_request(
        args.request_id,
        settings,
        max_attempts=settings.worker_max_attempts,
        reset_attempts=args.reset_attempts,
    )
    if not row:
        raise SystemExit(
            f"request is not retryable, exceeded max attempts ({settings.worker_max_attempts}), or was not found: {args.request_id}"
        )
    _print_json(row)


def _cmd_request_cancel(args) -> None:
    row = cancel_request(args.request_id, reason=args.reason, settings=load_settings())
    if not row:
        raise SystemExit(f"request is not cancellable or was not found: {args.request_id}")
    _print_json(row)


def _cmd_request_requeue_stale(args) -> None:
    settings = load_settings()
    _print_json(
        requeue_stale_running(
            older_than_minutes=args.older_than_minutes,
            limit=args.limit,
            max_attempts=settings.worker_max_attempts,
            settings=settings,
        )
    )


def _cmd_worker_status(_args) -> None:
    settings = load_settings()
    _print_json(
        {
            "request_counts": count_requests_by_status(settings),
            "workers": list_worker_state(settings),
            "worker_max_attempts": settings.worker_max_attempts,
            "worker_retry_backoff_seconds": settings.worker_retry_backoff_seconds,
            "worker_heartbeat_interval": settings.worker_heartbeat_interval,
            "worker_runner": settings.worker_runner,
            "db_note_run_root": str(settings.db_note_run_root),
            "mirror_path": str(settings.vault_path),
            "worker_db_note_auto_export_enabled": settings.worker_db_note_auto_export_enabled,
            "mirror_git_push_enabled": settings.mirror_git_push_enabled,
            "openai_api_runner_enabled": settings.openai_api_runner_enabled,
            "openai_api_model": settings.openai_api_model,
            "openai_api_timeout_seconds": settings.openai_api_timeout_seconds,
            "openai_api_max_output_tokens": settings.openai_api_max_output_tokens,
            "openai_api_reasoning_effort": settings.openai_api_reasoning_effort,
            "time_suggestion_auto_register_enabled": settings.time_suggestion_auto_register_enabled,
            "notification_dispatch_enabled": settings.notification_dispatch_enabled,
            "pwa_push_configured": bool(settings.pwa_vapid_public_key and settings.pwa_vapid_private_key),
            "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
            "telegram_polling_enabled": settings.telegram_polling_enabled,
            "telegram_polling_timeout_seconds": settings.telegram_polling_timeout_seconds,
            "telegram_polling_interval_seconds": settings.telegram_polling_interval_seconds,
            "telegram_polling_limit": settings.telegram_polling_limit,
            "telegram_polling_offset_path": str(settings.telegram_polling_offset_path),
        }
    )


def _cmd_ops_health(args) -> None:
    result = build_health_summary(
        load_settings(),
        api_url=args.api_url,
        backup_dir=Path(args.backup_dir),
        codex_login_log=Path(args.codex_login_log),
        queued_warn=args.queued_warn,
        failed_warn=args.failed_warn,
        backup_warn_hours=args.backup_warn_hours,
        backup_critical_hours=args.backup_critical_hours,
        codex_login_warn_minutes=args.codex_login_warn_minutes,
        codex_login_critical_minutes=args.codex_login_critical_minutes,
    )
    _print_json(result)
    if args.exit_status:
        raise SystemExit(health_exit_code(result["status"]))


def _cmd_request_sources(_args) -> None:
    _print_json(list_request_sources(load_settings()))


def _cmd_request_review_set(args) -> None:
    try:
        row = set_request_review(
            args.request_id,
            outcome=args.outcome,
            note=args.note,
            reviewed_by=args.reviewed_by,
            settings=load_settings(),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not row:
        raise SystemExit(f"request not found: {args.request_id}")
    _print_json(row)


def _cmd_request_review_list(args) -> None:
    try:
        rows = list_request_reviews(
            outcome=args.outcome,
            needs_review=args.needs_review,
            poor=args.poor,
            limit=args.limit,
            settings=load_settings(),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _print_json(rows)


def _cmd_note_create(args) -> None:
    try:
        row = create_note(
            {
                "kind": args.kind,
                "status": args.status,
                "title": args.title,
                "slug": args.slug,
                "body_markdown": _read_body_arg(args),
                "metadata": _metadata_arg(args.metadata_json),
                "parent_id": args.parent_id,
                "source_note_id": args.source_note_id,
                "change_source": args.change_source,
                "created_by": args.created_by,
                "request_id": args.request_id,
            },
            load_settings(),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _print_json(row)


def _cmd_note_get(args) -> None:
    row = get_note(args.note_id, load_settings())
    if not row:
        raise SystemExit(f"note not found: {args.note_id}")
    _print_json(row)


def _cmd_note_list(args) -> None:
    try:
        rows = list_notes(
            kind=args.kind,
            status=args.status,
            query=_clean_filter(args.query),
            include_deleted=args.include_deleted,
            limit=args.limit,
            settings=load_settings(),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _print_json(rows)


def _cmd_note_update(args) -> None:
    try:
        row = update_note(
            args.note_id,
            expected_version=args.expected_version,
            title=args.title,
            body_markdown=_read_body_arg(args, default=None),
            metadata=_metadata_arg(args.metadata_json) if args.metadata_json is not None else None,
            kind=args.kind,
            status=args.status,
            slug=args.slug,
            parent_id=args.parent_id,
            source_note_id=args.source_note_id,
            change_source=args.change_source,
            request_id=args.request_id,
            created_by=args.created_by,
            settings=load_settings(),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not row:
        raise SystemExit(f"note not found or stale version: {args.note_id}")
    _print_json(row)


def _cmd_note_revisions(args) -> None:
    _print_json(list_note_revisions(args.note_id, limit=args.limit, settings=load_settings()))


def _cmd_source_readable_backfill(args) -> None:
    _print_json(
        queue_source_readable_reanalysis(
            load_settings(),
            limit=args.limit,
            dry_run=args.dry_run,
            created_by=args.created_by,
        )
    )


def _cmd_promoted_targets_refresh(_args) -> None:
    _print_json(refresh_promoted_target_source_sections(load_settings()))


def _cmd_notes_export(args) -> None:
    settings = load_settings()
    scope = args.scope
    if args.note_id and scope == "changed-notes":
        scope = "note-id"
    if scope == "note-id" and not args.note_id:
        raise SystemExit("--note-id is required when --scope note-id is used")
    if args.note_id and scope != "note-id":
        raise SystemExit("--note-id can only be used with --scope note-id")
    mirror_git_push_enabled = bool(getattr(settings, "mirror_git_push_enabled", False))
    sync = mirror_git_push_enabled if args.sync is None else args.sync
    push = mirror_git_push_enabled if args.push is None else args.push
    if args.local_only:
        sync = False
        push = False
    try:
        result = export_notes_to_markdown(
            settings,
            scope=scope,
            note_id=args.note_id,
            dry_run=args.dry_run,
            sync=sync,
            push=push,
            reconcile=args.reconcile,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _print_json(result)


def _cmd_notes_import(args) -> None:
    try:
        result = import_vault_notes(Path(args.from_vault), mode=args.mode, settings=load_settings())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _print_json(result)


def _cmd_chat_cleanup(args) -> None:
    try:
        result = purge_deleted_chat_sessions(
            older_than_days=args.deleted_retention_days,
            limit=args.limit,
            dry_run=args.dry_run,
            settings=load_settings(),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _print_json(result)


def _cmd_data_lifecycle_report(args) -> None:
    try:
        result = build_data_lifecycle_report(
            load_settings(),
            deleted_chat_retention_days=args.deleted_chat_retention_days,
            stale_draft_days=args.stale_draft_days,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _print_json(result)


def _cmd_demo_seed(args) -> None:
    try:
        anchor_date = date.fromisoformat(args.anchor_date) if args.anchor_date else None
    except ValueError as exc:
        raise SystemExit("--anchor-date must be YYYY-MM-DD") from exc
    try:
        result = create_demo_seed(
            load_settings(),
            anchor_date=anchor_date,
            with_notifications=args.with_notifications,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _print_json(result)


def _cmd_vault_lint(args) -> None:
    result = lint_vault(Path(args.path))
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    if not result.ok:
        raise SystemExit(1)
    print("vault_lint=ok")


def _cmd_diff(args) -> None:
    _print_json(changed_files(args.base, args.head, vault_path=Path(args.path)))


def _cmd_worker(args) -> None:
    settings = load_settings()
    if args.loop:
        worker_loop(settings, interval=args.interval, runner_name=args.runner)
    else:
        _print_json(process_one(settings, runner_name=args.runner) or {"status": "idle"})


def _cmd_telegram_poll(args) -> None:
    settings = load_settings()
    if args.once:
        current_offset = _load_polling_offset(settings.telegram_polling_offset_path)

        def store_offset(next_offset: int) -> None:
            _save_polling_offset(settings.telegram_polling_offset_path, next_offset)

        _print_json(
            poll_telegram_updates(
                settings,
                offset=current_offset,
                timeout_seconds=args.timeout,
                limit=args.limit,
                offset_callback=store_offset,
            )
        )
    else:
        run_telegram_polling_loop(
            settings,
            interval=args.interval,
            timeout_seconds=args.timeout,
            limit=args.limit,
        )


def _cmd_upload(args) -> None:
    data = Path(args.file).read_bytes()
    _print_json(
        upload_bytes(
            data,
            file_name=Path(args.file).name,
            content_type=args.content_type,
            prefix=args.prefix,
            settings=load_settings(),
        )
    )


def _cmd_head(args) -> None:
    _print_json(head_object(args.key, load_settings()))


def _cmd_backup(args) -> None:
    target = Path(args.target)
    settings = load_settings()
    output = {}
    bundle = create_repo_mirror_backup(target, settings) if args.repo_bundle else None
    if bundle:
        output["repo_bundle"] = str(bundle)
    postgres_dump = None
    if args.postgres:
        postgres_dump = create_postgres_dump(target, settings)
        output["postgres_dump"] = str(postgres_dump)
    object_archive = None
    if args.object_manifest:
        output["object_manifest"] = str(
            create_object_manifest(target, settings, verify=args.verify_objects, source=args.object_source)
        )
    if args.object_data:
        object_archive = create_object_archive(target, settings, source=args.object_source)
        output["object_archive"] = str(object_archive)
    if args.restore_smoke:
        output["restore_smoke"] = _backup_restore_smoke(args, settings, bundle, postgres_dump, object_archive)
        if _has_failed_restore_smoke(output["restore_smoke"]):
            _print_json(output)
            raise SystemExit(1)
    if args.retention_days:
        output["retention_removed"] = cleanup_old_backups(target, older_than_days=args.retention_days)
    _print_json(output)


def _cmd_restore_smoke(args) -> None:
    output = {}
    if args.bundle:
        output["repo_bundle"] = restore_smoke_bundle(
            Path(args.bundle),
            Path(args.target),
            expected_head=args.expected_head,
            required_paths=args.required_path,
        )
    if args.postgres_dump:
        if not args.db_restore_url:
            raise SystemExit("--db-restore-url is required with --postgres-dump")
        settings = load_settings()
        output["postgres"] = restore_smoke_postgres_dump(
            Path(args.postgres_dump),
            args.db_restore_url,
            source_database_url=settings.database_url,
        )
        if args.mirror_restore_target:
            output["markdown_export"] = restore_smoke_markdown_export(
                Path(args.mirror_restore_target),
                database_url=args.db_restore_url,
                settings=settings,
            )
    if args.object_archive:
        output["object_archive"] = restore_smoke_object_archive(
            Path(args.object_archive),
            Path(args.object_restore_target) if args.object_restore_target else None,
        )
    if not output:
        raise SystemExit("at least one restore smoke target is required")
    if _has_failed_restore_smoke(output):
        _print_json(output)
        raise SystemExit(1)
    _print_json(output)


def _backup_restore_smoke(args, settings, bundle, postgres_dump, object_archive) -> dict:
    output = {}
    if postgres_dump:
        if args.db_restore_url:
            output["postgres"] = restore_smoke_postgres_dump(
                postgres_dump,
                args.db_restore_url,
                source_database_url=settings.database_url,
            )
            if args.mirror_restore_target:
                output["markdown_export"] = restore_smoke_markdown_export(
                    Path(args.mirror_restore_target),
                    database_url=args.db_restore_url,
                    settings=settings,
                )
        else:
            output["postgres"] = {"ok": None, "skipped": "db_restore_url_not_set"}
    if object_archive:
        output["object_archive"] = restore_smoke_object_archive(
            object_archive,
            Path(args.object_restore_target) if args.object_restore_target else None,
        )
    if bundle and args.repo_restore_smoke:
        head = run_git(["rev-parse", "HEAD"], cwd=settings.vault_path).stdout.strip()
        output["repo_bundle"] = restore_smoke_bundle(
            bundle,
            Path(args.restore_target),
            expected_head=head,
            required_paths=args.required_path,
        )
    if not output:
        output["skipped"] = "no_restore_smoke_artifacts"
    return output


def _has_failed_restore_smoke(value) -> bool:
    if isinstance(value, dict):
        if value.get("ok") is False:
            return True
        return any(_has_failed_restore_smoke(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_failed_restore_smoke(item) for item in value)
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-wiki")
    sub = parser.add_subparsers(required=True)

    api = sub.add_parser("api")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8080)
    api.set_defaults(func=_cmd_api)

    migrate_parser = sub.add_parser("migrate")
    migrate_parser.set_defaults(func=_cmd_migrate)

    request = sub.add_parser("request-create")
    request.add_argument("file_path")
    request.add_argument("--source", default="cli")
    request.add_argument("--operation", default="ingest", choices=["ingest"])
    request.add_argument("--commit-sha")
    request.add_argument("--content-hash")
    request.add_argument("--content-snapshot-file")
    request.add_argument("--sensitivity", default="private", choices=["private", "internal", "public"])
    request.set_defaults(func=_cmd_request)

    request_get = sub.add_parser("request-get")
    request_get.add_argument("request_id")
    request_get.set_defaults(func=_cmd_request_get)

    request_list = sub.add_parser("request-list")
    request_list.add_argument("--status", choices=["queued", "running", "needs_sync", "succeeded", "failed", "cancelled"])
    request_list.add_argument("--source")
    request_list.add_argument("--query")
    request_list.add_argument("--limit", type=int, default=20)
    request_list.set_defaults(func=_cmd_request_list)

    request_sources = sub.add_parser("request-sources")
    request_sources.set_defaults(func=_cmd_request_sources)

    request_review_set = sub.add_parser("request-review-set")
    request_review_set.add_argument("request_id")
    request_review_set.add_argument("--outcome", required=True, choices=sorted(REVIEW_OUTCOMES))
    request_review_set.add_argument("--note")
    request_review_set.add_argument("--reviewed-by")
    request_review_set.set_defaults(func=_cmd_request_review_set)

    request_review_list = sub.add_parser("request-review-list")
    review_filters = request_review_list.add_mutually_exclusive_group()
    review_filters.add_argument("--outcome", choices=sorted(REVIEW_OUTCOMES))
    review_filters.add_argument("--needs-review", action="store_true")
    review_filters.add_argument("--poor", action="store_true")
    request_review_list.add_argument("--limit", type=int, default=20)
    request_review_list.set_defaults(func=_cmd_request_review_list)

    note_create = sub.add_parser("note-create")
    note_create.add_argument("--title", required=True)
    note_create.add_argument("--kind", default="inbox", choices=sorted(NOTE_KINDS))
    note_create.add_argument("--status", default="draft", choices=sorted(NOTE_STATUSES))
    note_create.add_argument("--slug")
    note_create_body = note_create.add_mutually_exclusive_group()
    note_create_body.add_argument("--body", default="")
    note_create_body.add_argument("--body-file")
    note_create.add_argument("--metadata-json")
    note_create.add_argument("--parent-id")
    note_create.add_argument("--source-note-id")
    note_create.add_argument("--change-source", default="web", choices=sorted(REVISION_SOURCES))
    note_create.add_argument("--created-by")
    note_create.add_argument("--request-id")
    note_create.set_defaults(func=_cmd_note_create)

    note_get = sub.add_parser("note-get")
    note_get.add_argument("note_id")
    note_get.set_defaults(func=_cmd_note_get)

    note_list = sub.add_parser("note-list")
    note_list.add_argument("--kind", choices=sorted(NOTE_KINDS))
    note_list.add_argument("--status", choices=sorted(NOTE_STATUSES))
    note_list.add_argument("--query")
    note_list.add_argument("--include-deleted", action="store_true")
    note_list.add_argument("--limit", type=int, default=20)
    note_list.set_defaults(func=_cmd_note_list)

    note_update = sub.add_parser("note-update")
    note_update.add_argument("note_id")
    note_update.add_argument("--expected-version", type=int, required=True)
    note_update.add_argument("--title")
    note_update.add_argument("--kind", choices=sorted(NOTE_KINDS))
    note_update.add_argument("--status", choices=sorted(NOTE_STATUSES))
    note_update.add_argument("--slug")
    note_update_body = note_update.add_mutually_exclusive_group()
    note_update_body.add_argument("--body")
    note_update_body.add_argument("--body-file")
    note_update.add_argument("--metadata-json")
    note_update.add_argument("--parent-id")
    note_update.add_argument("--source-note-id")
    note_update.add_argument("--change-source", default="web", choices=sorted(REVISION_SOURCES))
    note_update.add_argument("--created-by")
    note_update.add_argument("--request-id")
    note_update.set_defaults(func=_cmd_note_update)

    note_revisions = sub.add_parser("note-revisions")
    note_revisions.add_argument("note_id")
    note_revisions.add_argument("--limit", type=int, default=20)
    note_revisions.set_defaults(func=_cmd_note_revisions)

    source_readable_backfill = sub.add_parser("source-readable-backfill")
    source_readable_backfill.add_argument("--limit", type=int, default=100)
    source_readable_backfill.add_argument("--dry-run", action="store_true")
    source_readable_backfill.add_argument("--created-by", default="operator-readable-backfill")
    source_readable_backfill.set_defaults(func=_cmd_source_readable_backfill)

    promoted_targets_refresh = sub.add_parser("promoted-targets-refresh")
    promoted_targets_refresh.set_defaults(func=_cmd_promoted_targets_refresh)

    notes_export = sub.add_parser("notes-export")
    notes_export.add_argument("--scope", default="changed-notes", choices=sorted(EXPORT_SCOPES))
    notes_export.add_argument("--note-id")
    notes_export.add_argument("--dry-run", action="store_true")
    notes_export.add_argument("--reconcile", action="store_true")
    notes_export.add_argument("--local-only", action="store_true")
    notes_export.add_argument("--sync", dest="sync", action="store_true", default=None)
    notes_export.add_argument("--no-sync", dest="sync", action="store_false")
    notes_export.add_argument("--push", dest="push", action="store_true", default=None)
    notes_export.add_argument("--no-push", dest="push", action="store_false")
    notes_export.set_defaults(func=_cmd_notes_export)

    notes_import = sub.add_parser("notes-import")
    notes_import.add_argument("--from-vault", default="/vault")
    notes_import.add_argument("--mode", default="dry-run", choices=sorted(IMPORT_MODES))
    notes_import.set_defaults(func=_cmd_notes_import)

    chat_cleanup = sub.add_parser("chat-cleanup")
    chat_cleanup.add_argument("--deleted-retention-days", type=int, default=30)
    chat_cleanup.add_argument("--limit", type=int, default=500)
    chat_cleanup.add_argument("--dry-run", action="store_true")
    chat_cleanup.set_defaults(func=_cmd_chat_cleanup)

    data_lifecycle = sub.add_parser("data-lifecycle-report")
    data_lifecycle.add_argument("--deleted-chat-retention-days", type=int, default=30)
    data_lifecycle.add_argument("--stale-draft-days", type=int, default=3)
    data_lifecycle.set_defaults(func=_cmd_data_lifecycle_report)

    demo_seed = sub.add_parser("demo-seed")
    demo_seed.add_argument("--anchor-date", help="합성 일정 기준일(YYYY-MM-DD). 생략하면 기존 seed 기준일 또는 오늘을 사용합니다.")
    demo_seed.add_argument(
        "--with-notifications",
        action="store_true",
        help="브라우저 알림 발송 대기열까지 생성합니다. 기본값은 일정만 만들고 알림 채널은 비워 둡니다.",
    )
    demo_seed.set_defaults(func=_cmd_demo_seed)

    request_retry = sub.add_parser("request-retry")
    request_retry.add_argument("request_id")
    request_retry.add_argument("--reset-attempts", action="store_true")
    request_retry.set_defaults(func=_cmd_request_retry)

    request_cancel = sub.add_parser("request-cancel")
    request_cancel.add_argument("request_id")
    request_cancel.add_argument("--reason", default="cancelled by operator")
    request_cancel.set_defaults(func=_cmd_request_cancel)

    request_requeue_stale = sub.add_parser("request-requeue-stale")
    request_requeue_stale.add_argument("--older-than-minutes", type=int, default=60)
    request_requeue_stale.add_argument("--limit", type=int, default=20)
    request_requeue_stale.set_defaults(func=_cmd_request_requeue_stale)

    lint = sub.add_parser("vault-lint")
    lint.add_argument("--path", default="/vault")
    lint.set_defaults(func=_cmd_vault_lint)

    diff = sub.add_parser("git-diff")
    diff.add_argument("base")
    diff.add_argument("--head", default="HEAD")
    diff.add_argument("--path", default="/vault")
    diff.set_defaults(func=_cmd_diff)

    worker = sub.add_parser("worker")
    worker.add_argument("--loop", action="store_true")
    worker.add_argument("--interval", type=int, default=15)
    worker.add_argument("--runner", choices=["dry-run", "codex-cli", "openai-api"], default="dry-run")
    worker.set_defaults(func=_cmd_worker)

    worker_status = sub.add_parser("worker-status")
    worker_status.set_defaults(func=_cmd_worker_status)

    telegram_poll = sub.add_parser("telegram-poll")
    telegram_poll.add_argument("--once", action="store_true")
    telegram_poll.add_argument("--interval", type=int)
    telegram_poll.add_argument("--timeout", type=int)
    telegram_poll.add_argument("--limit", type=int)
    telegram_poll.set_defaults(func=_cmd_telegram_poll)

    ops_health = sub.add_parser("ops-health")
    ops_health.add_argument("--api-url")
    ops_health.add_argument("--backup-dir", default="/backups")
    ops_health.add_argument("--codex-login-log", default="/backups/codex-login-status.log")
    ops_health.add_argument("--queued-warn", type=int, default=10)
    ops_health.add_argument("--failed-warn", type=int, default=1)
    ops_health.add_argument("--backup-warn-hours", type=int, default=30)
    ops_health.add_argument("--backup-critical-hours", type=int, default=48)
    ops_health.add_argument("--codex-login-warn-minutes", type=int, default=90)
    ops_health.add_argument("--codex-login-critical-minutes", type=int, default=180)
    ops_health.add_argument("--exit-status", action="store_true")
    ops_health.set_defaults(func=_cmd_ops_health)

    upload = sub.add_parser("storage-upload")
    upload.add_argument("file")
    upload.add_argument("--prefix", default="raw")
    upload.add_argument("--content-type")
    upload.set_defaults(func=_cmd_upload)

    head = sub.add_parser("storage-head")
    head.add_argument("key")
    head.set_defaults(func=_cmd_head)

    backup = sub.add_parser("backup")
    backup.add_argument("--target", default="/backups")
    backup.add_argument("--repo-bundle", action="store_true")
    backup.add_argument("--postgres", action="store_true")
    backup.add_argument("--object-manifest", action="store_true")
    backup.add_argument("--verify-objects", action="store_true")
    backup.add_argument("--object-data", action="store_true")
    backup.add_argument("--object-source", default="db", choices=["db", "markdown"])
    backup.add_argument("--retention-days", type=int)
    backup.add_argument("--restore-smoke", action="store_true")
    backup.add_argument("--restore-target", default="/backups/restore-smoke")
    backup.add_argument("--db-restore-url")
    backup.add_argument("--mirror-restore-target")
    backup.add_argument("--object-restore-target")
    backup.add_argument("--repo-restore-smoke", action="store_true")
    backup.add_argument(
        "--required-path",
        action="append",
        default=["docs/vault-structure.md", "docs/markdown-rules.md"],
    )
    backup.set_defaults(func=_cmd_backup)

    restore_smoke = sub.add_parser("restore-smoke")
    restore_smoke.add_argument("bundle", nargs="?")
    restore_smoke.add_argument("--target", default="/backups/restore-smoke")
    restore_smoke.add_argument("--expected-head")
    restore_smoke.add_argument("--postgres-dump")
    restore_smoke.add_argument("--db-restore-url")
    restore_smoke.add_argument("--mirror-restore-target")
    restore_smoke.add_argument("--object-archive")
    restore_smoke.add_argument("--object-restore-target")
    restore_smoke.add_argument(
        "--required-path",
        action="append",
        default=["docs/vault-structure.md", "docs/markdown-rules.md"],
    )
    restore_smoke.set_defaults(func=_cmd_restore_smoke)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


def _clean_filter(value: str | None, *, max_length: int = 120) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def _read_body_arg(args, *, default: str | None = "") -> str | None:
    body_file = getattr(args, "body_file", None)
    if body_file:
        return Path(body_file).read_text(encoding="utf-8")
    body = getattr(args, "body", None)
    if body is None:
        return default
    return body


def _metadata_arg(value: str | None) -> dict:
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid metadata json: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("metadata json must be an object")
    return parsed


if __name__ == "__main__":
    main()
