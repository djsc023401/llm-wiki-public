from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import os
from pathlib import Path, PurePosixPath
import socket
import tempfile
import threading
import time

from .ai_runner import get_runner
from .config import Settings, load_settings
from .daily_digest import dispatch_daily_digest
from .export_mirror import export_notes_to_markdown, export_path_for_note
from .notes_store import (
    NoteProcessingError,
    get_note,
    get_note_revision,
    get_source_note_for_source,
    process_note_revision_to_source,
    refresh_promoted_targets_for_source,
    reopen_feedback_for_reprocess_request,
)
from .notifications import dispatch_due_notifications
from .personalization import ai_personalization_context
from .prompts import source_note_context
from .requests_store import (
    claim_next,
    finish_owned_request,
    has_claimable_request,
    peek_claimable_request,
    record_worker_heartbeat,
    request_is_owned,
    touch_owned_request,
)
from .time_store import auto_register_time_suggestions_for_source


def process_one(settings: Settings | None = None, *, runner_name: str = "dry-run", worker_id: str | None = None) -> dict | None:
    resolved = settings or load_settings()
    worker_id = worker_id or _worker_id()
    record_worker_heartbeat(worker_id, "checking", settings=resolved)
    if not has_claimable_request(
        max_attempts=resolved.worker_max_attempts,
        retry_backoff_seconds=resolved.worker_retry_backoff_seconds,
        settings=resolved,
    ):
        record_worker_heartbeat(worker_id, "idle", settings=resolved)
        return None
    preferred_input_modes = ("db-note",)
    candidate = peek_claimable_request(
        max_attempts=resolved.worker_max_attempts,
        retry_backoff_seconds=resolved.worker_retry_backoff_seconds,
        settings=resolved,
        input_modes=preferred_input_modes,
    )
    claim_input_modes = preferred_input_modes if candidate else None
    if not candidate:
        candidate = peek_claimable_request(
            max_attempts=resolved.worker_max_attempts,
            retry_backoff_seconds=resolved.worker_retry_backoff_seconds,
            settings=resolved,
        )
    try:
        runner = get_runner(runner_name)
        preflight_path = _runner_preflight_path_for_mode(
            candidate.get("input_mode") if candidate else None,
            resolved,
        )
        _preflight_runner(runner, preflight_path)
    except Exception as exc:
        record_worker_heartbeat(worker_id, "blocked", settings=resolved)
        return {"status": "blocked", "error": str(exc)}
    request = claim_next(
        worker_id,
        resolved,
        max_attempts=resolved.worker_max_attempts,
        retry_backoff_seconds=resolved.worker_retry_backoff_seconds,
        input_modes=claim_input_modes,
        runner_name=runner_name,
    )
    if not request:
        record_worker_heartbeat(worker_id, "idle", settings=resolved)
        return None
    record_worker_heartbeat(worker_id, "running", request_id=request["id"], settings=resolved)
    stop_heartbeat = _start_running_heartbeat(request["id"], worker_id, resolved)
    try:
        if candidate and request.get("input_mode") != candidate.get("input_mode"):
            _preflight_runner(runner, _runner_preflight_path_for_mode(request.get("input_mode"), resolved))
        if request.get("input_mode") == "db-note":
            return _process_db_note_request(request, worker_id, resolved, runner=runner, runner_name=runner_name)
        return _finish_legacy_file_request_unsupported(request, worker_id, resolved)
    except Exception as exc:
        if request.get("input_mode") == "db-note":
            reopen_feedback_for_reprocess_request(request["id"], settings=resolved)
        updated = finish_owned_request(
            request["id"],
            "failed",
            worker_id,
            error_message=_classified_error(exc),
            settings=resolved,
        )
        if not updated:
            return {"id": request["id"], "status": "released", "error": str(exc)}
        return {"id": request["id"], "status": "failed", "error": str(exc)}
    finally:
        stop_heartbeat()
        record_worker_heartbeat(worker_id, "idle", settings=resolved)


def loop(settings: Settings | None = None, *, interval: int = 15, runner_name: str = "dry-run") -> None:
    resolved = settings or load_settings()
    worker_id = _worker_id()
    while True:
        try:
            dispatch_daily_digest(resolved)
        except Exception as exc:
            print(f"daily_digest error={str(exc)!r}", flush=True)
        try:
            dispatch_due_notifications(resolved)
        except Exception as exc:
            print(f"notification_dispatch error={str(exc)!r}", flush=True)
        result = process_one(resolved, runner_name=runner_name, worker_id=worker_id)
        if not result or result.get("status") == "blocked":
            record_worker_heartbeat(worker_id, result.get("status", "idle") if result else "idle", settings=resolved)
            time.sleep(interval)


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _preflight_runner(runner, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    runner.preflight(path)


def _runner_preflight_path_for_mode(input_mode: str | None, settings: Settings) -> Path:
    return _db_note_runner_root(settings)


def _db_note_runner_root(settings: Settings) -> Path:
    return settings.db_note_run_root


def _finish_legacy_file_request_unsupported(request: dict, worker_id: str, settings: Settings) -> dict:
    message = (
        "legacy file-path requests are no longer processed. "
        "Create or import a DB note and run AI processing from the note instead."
    )
    updated = finish_owned_request(
        request["id"],
        "failed",
        worker_id,
        error_message=message,
        settings=settings,
    )
    if not updated:
        return {"id": request["id"], "status": "released"}
    return {"id": request["id"], "status": "failed", "error": message}


def _process_db_note_request(request: dict, worker_id: str, settings: Settings, *, runner, runner_name: str) -> dict:
    request_id = request["id"]
    note_id = request.get("note_id")
    source_revision_id = request.get("source_revision_id")
    if not note_id or not source_revision_id:
        updated = finish_owned_request(
            request_id,
            "failed",
            worker_id,
            error_message="db-note: note_id and source_revision_id are required",
            settings=settings,
        )
        if not updated:
            return {"id": request_id, "status": "released"}
        return {"id": request_id, "status": "failed"}
    touch_owned_request(request_id, worker_id, settings)
    if not request_is_owned(request_id, worker_id, settings):
        return {"id": request_id, "status": "released"}
    try:
        runner_output = _run_db_note_runner(request, runner, runner_name, settings)
        result = process_note_revision_to_source(
            request_id=request_id,
            note_id=note_id,
            source_revision_id=source_revision_id,
            target_note_id=request.get("target_note_id"),
            generated_body_markdown=runner_output["body_markdown"],
            processor=f"db-note-runner:{runner_name}",
            runner_summary=runner_output.get("summary"),
            settings=settings,
        )
    except NoteProcessingError as exc:
        reopen_feedback_for_reprocess_request(request_id, settings=settings)
        updated = finish_owned_request(
            request_id,
            exc.request_status,
            worker_id,
            error_message=exc.detail,
            settings=settings,
        )
        if not updated:
            return {"id": request_id, "status": "released"}
        return {"id": request_id, "status": exc.request_status, "error": exc.detail}
    touch_owned_request(request_id, worker_id, settings)
    if not request_is_owned(request_id, worker_id, settings):
        return {"id": request_id, "status": "released"}
    target_note_id = result["target_note"]["id"]
    promoted_targets_refresh = refresh_promoted_targets_for_source(target_note_id, settings=settings)
    updated = finish_owned_request(
        request_id,
        "succeeded",
        worker_id,
        target_note_id=target_note_id,
        settings=settings,
    )
    if not updated:
        return {"id": request_id, "status": "released", "target_note_id": target_note_id}
    export_result = (
        _auto_export_db_note_target(target_note_id, settings)
        if settings.worker_db_note_auto_export_enabled
        else None
    )
    time_auto_register_result = (
        _auto_register_db_note_time_suggestions(target_note_id, settings)
        if settings.time_suggestion_auto_register_enabled
        else None
    )
    return {
        "id": request_id,
        "status": "succeeded",
        "target_note_id": target_note_id,
        "source_note_id": result["source_note"]["id"],
        "export": export_result,
        "time_auto_register": time_auto_register_result,
        "promoted_targets_refresh": promoted_targets_refresh,
    }


def _run_db_note_runner(request: dict, runner, runner_name: str, settings: Settings) -> dict:
    note_id = str(request.get("note_id") or "")
    source_revision_id = str(request.get("source_revision_id") or "")
    source_note = get_note(note_id, settings)
    if not source_note or source_note.get("deleted_at") is not None:
        raise NoteProcessingError("db-note: source note is missing", request_status="needs_sync")
    if source_note["kind"] != "inbox":
        raise NoteProcessingError("db-note: only inbox notes can be processed")
    if source_note["status"] in {"archived", "deleted"}:
        raise NoteProcessingError("db-note: source note is already closed", request_status="needs_sync")
    source_revision = get_note_revision(note_id, revision_id=source_revision_id, settings=settings)
    if not source_revision:
        raise NoteProcessingError("db-note: source revision is missing", request_status="needs_sync")
    if source_revision["version"] != source_note["version"]:
        raise NoteProcessingError("db-note: source note changed after processing was queued", request_status="needs_sync")

    run_root = _db_note_runner_root(settings)
    run_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{request['id']}-", dir=run_root) as temp_name:
        temp_vault = Path(temp_name)
        runner_request = _db_note_runner_request(request, source_note, source_revision, settings)
        _write_temp_vault_file(
            temp_vault,
            runner_request["file_path"],
            runner_request["content_snapshot"],
        )
        target_note_id = request.get("target_note_id")
        existing_target = get_note(str(target_note_id), settings) if target_note_id else get_source_note_for_source(note_id, settings)
        if target_note_id and (
            not existing_target
            or existing_target.get("kind") != "source"
            or existing_target.get("deleted_at") is not None
        ):
            raise NoteProcessingError("db-note: target source note is missing", request_status="needs_sync")
        if existing_target:
            _write_existing_db_source_note(temp_vault, existing_target, runner_request["file_path"])
        context = source_note_context(runner_request, temp_vault, runner_request["content_snapshot"])
        result = runner.run(runner_request, temp_vault)
        target_path = _temp_vault_path(temp_vault, context.target_path)
        if not target_path.exists():
            raise RuntimeError(f"db-note runner did not create target source note: {context.target_path}")
        _validate_db_note_runner_markdown_outputs(temp_vault, runner_request["file_path"], context.target_path)
        body = _strip_markdown_frontmatter(target_path.read_text(encoding="utf-8"))
        if not body.strip():
            raise RuntimeError("db-note runner produced empty source note")
        return {
            "body_markdown": body,
            "summary": getattr(result, "summary", None) or f"{runner_name} completed",
            "target_path": context.target_path,
        }


def _db_note_runner_request(request: dict, source_note: dict, source_revision: dict, settings: Settings) -> dict:
    file_path = f"inbox/web/{_db_note_runner_file_stem(source_note)}.md"
    source_markdown = _db_note_source_markdown(source_note, source_revision)
    return {
        **request,
        "file_path": file_path,
        "content_snapshot": source_markdown,
        "commit_sha": request.get("commit_sha"),
        "source_note_created_at": source_note.get("created_at"),
        "source_note_updated_at": source_note.get("updated_at"),
        "source_revision_created_at": source_revision.get("created_at"),
        "personalization_context": ai_personalization_context(settings),
    }


def _db_note_runner_file_stem(source_note: dict) -> str:
    raw = str(source_note.get("slug") or source_note.get("id") or "web-note").replace("\\", "/")
    stem = PurePosixPath(raw).name.strip(". ") or "web-note"
    return stem[:180]


def _db_note_source_markdown(source_note: dict, source_revision: dict) -> str:
    title = _db_note_source_title(source_note, source_revision)
    body = str(source_revision.get("body_markdown") or "").strip()
    user_metadata = _db_note_user_metadata_section(source_note)
    return "\n".join(
        [
            f'title: "{title.replace(chr(34), chr(39))}"',
            "",
            body or "_캡처된 본문이 없습니다._",
            "",
            *user_metadata,
            "## DB 노트 메타데이터",
            "",
            f"- 노트 ID: `{source_note['id']}`",
            f"- 리비전 ID: `{source_revision['id']}`",
            f"- 리비전 버전: `v{source_revision['version']}`",
            f"- 소스 노트 생성일: `{_format_runner_timestamp(source_note.get('created_at'))}`",
            f"- 소스 노트 수정일: `{_format_runner_timestamp(source_note.get('updated_at'))}`",
            f"- 소스 리비전 생성일: `{_format_runner_timestamp(source_revision.get('created_at'))}`",
            "",
        ]
    )


def _db_note_user_metadata_section(source_note: dict) -> list[str]:
    metadata = source_note.get("metadata")
    if not isinstance(metadata, Mapping):
        return []
    topics = _metadata_string_list(metadata.get("manual_topics"))
    tags = _metadata_string_list(metadata.get("manual_tags"))
    if not topics and not tags:
        return []
    lines = ["## 사용자 제공 메타데이터", ""]
    if topics:
        lines.append(f"- 사용자 주제: {'; '.join(topics)}")
    if tags:
        lines.append(f"- 사용자 태그: {'; '.join(tags)}")
    lines.append("")
    return lines


def _metadata_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(cleaned[:80])
    return items[:24]


def _format_runner_timestamp(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "unknown")


def _db_note_source_title(source_note: dict, source_revision: dict) -> str:
    title = str(source_revision.get("title") or source_note.get("title") or "").strip()
    if title and not _is_default_web_note_title(title):
        return title
    return "제목 없는 웹 메모"


def _is_default_web_note_title(title: str) -> bool:
    return title.strip().casefold() in {
        "untitled",
        "untitled note",
        "제목 없는 노트",
        "제목 없는 웹 메모",
        "제목 없는 소스",
        "제목 없는 주제",
        "제목 없는 대상",
        "제목 없는 로그",
    }


def _write_existing_db_source_note(temp_vault: Path, note: dict, source_file_path: str) -> None:
    body = str(note.get("body_markdown") or "").strip()
    content = "\n".join(
        [
            "---",
            f'title: "{str(note.get("title") or "Source").replace(chr(34), chr(39))}"',
            "type: source",
            "status: draft",
            "source_refs:",
            f"  - {source_file_path}",
            "---",
            "",
            body or f"# {note.get('title') or 'Source'}",
            "",
        ]
    )
    _write_temp_vault_file(temp_vault, export_path_for_note(note), content)


def _write_temp_vault_file(temp_vault: Path, relative_path: str, content: str) -> None:
    target = _temp_vault_path(temp_vault, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _temp_vault_path(temp_vault: Path, relative_path: str) -> Path:
    parts = [part for part in relative_path.replace("\\", "/").split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise RuntimeError(f"unsafe db-note runner path: {relative_path}")
    resolved_root = temp_vault.resolve()
    target = (resolved_root / Path(*parts)).resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise RuntimeError(f"db-note runner path escapes temp vault: {relative_path}")
    return target


def _validate_db_note_runner_markdown_outputs(temp_vault: Path, source_file_path: str, target_path: str) -> None:
    allowed = {source_file_path, target_path}
    violations = []
    for path in sorted(temp_vault.rglob("*.md")):
        rel = path.relative_to(temp_vault).as_posix()
        if rel in allowed:
            continue
        if rel.startswith(("wiki/topics/", "wiki/entities/")):
            violations.append(f"curated page edit is not allowed: {rel}")
        else:
            violations.append(f"unexpected Markdown output: {rel}")
    if violations:
        raise RuntimeError("db-note runner produced disallowed files: " + "; ".join(violations))


def _strip_markdown_frontmatter(markdown: str) -> str:
    lines = markdown.strip().splitlines()
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[index + 1 :]).strip()
    return markdown.strip()


def _auto_export_db_note_target(target_note_id: str, settings: Settings) -> dict:
    try:
        return export_notes_to_markdown(
            settings,
            scope="note-id",
            note_id=target_note_id,
            dry_run=False,
            sync=settings.mirror_git_push_enabled,
            push=settings.mirror_git_push_enabled,
        )
    except Exception as exc:
        return {
            "status": "failed",
            "note_id": target_note_id,
            "error": str(exc)[:2000] or "auto export failed",
        }


def _auto_register_db_note_time_suggestions(target_note_id: str, settings: Settings) -> dict:
    try:
        return {
            "status": "succeeded",
            "note_id": target_note_id,
            **auto_register_time_suggestions_for_source(target_note_id, settings=settings),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "note_id": target_note_id,
            "error": str(exc)[:2000] or "time suggestion auto registration failed",
        }


def _start_running_heartbeat(request_id: str, worker_id: str, settings: Settings):
    stop = threading.Event()
    interval = max(1, settings.worker_heartbeat_interval)

    def heartbeat() -> None:
        while not stop.wait(interval):
            try:
                touched = touch_owned_request(request_id, worker_id, settings)
                record_worker_heartbeat(worker_id, "running", request_id=request_id, settings=settings)
            except Exception:
                return
            if not touched:
                return

    thread = threading.Thread(target=heartbeat, name=f"llm-wiki-heartbeat-{request_id}", daemon=True)
    thread.start()

    def stop_heartbeat() -> None:
        stop.set()
        thread.join(timeout=1)

    return stop_heartbeat


def _classified_error(exc: Exception) -> str:
    message = str(exc)
    first_word = message.split(" ", 1)[0]
    if ":" in first_word:
        return message
    lowered = message.lower()
    if "codex cli is not authenticated" in lowered:
        return f"auth: {message}"
    if "vault working tree is not clean" in lowered or "content hash mismatch" in lowered:
        return f"sync: {message}"
    if "legacy file-path" in lowered:
        return f"legacy: {message}"
    return f"runner: {message}"
