from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re

from .config import Settings, load_settings
from .git_tools import commit_all, git_operation_lock, push_branch, run_git, sync_main


EXPORT_SCOPES = {"changed-notes", "full", "note-id"}
MANAGED_EXPORT_DIRS = ("archive/inbox", "inbox", "wiki", "logs", "templates")


@dataclass(frozen=True)
class ExportItem:
    note_id: str
    path: str
    content: str


KIND_EXPORT_DIRS = {
    "source": "wiki/sources",
    "topic": "wiki/topics",
    "entity": "wiki/entities",
    "log": "logs",
    "template": "templates",
}


def export_notes_to_markdown(
    settings: Settings | None = None,
    *,
    scope: str = "changed-notes",
    note_id: str | None = None,
    dry_run: bool = False,
    sync: bool = True,
    push: bool = True,
    reconcile: bool = False,
) -> dict:
    resolved = settings or load_settings()
    if scope not in EXPORT_SCOPES:
        expected = ", ".join(sorted(EXPORT_SCOPES))
        raise ValueError(f"invalid export scope: {scope}; expected one of {expected}")
    if scope == "note-id" and not note_id:
        raise ValueError("note_id is required when scope is note-id")
    if reconcile and scope != "full":
        raise ValueError("reconcile is only supported for full export")

    notes = _select_notes(scope=scope, note_id=note_id, settings=resolved)
    items = build_export_items(notes)
    if dry_run:
        changed_paths = paths_that_would_change(items, resolved.vault_path)
        stale_paths = find_stale_export_paths(items, resolved.vault_path) if scope == "full" else []
        return {
            "job_id": None,
            "status": "dry_run",
            "scope": scope,
            "note_id": note_id,
            "exported_count": len(items),
            "changed_paths": changed_paths,
            "stale_paths": stale_paths,
            "deleted_paths": stale_paths if reconcile else [],
            "reconcile": reconcile,
            "content_commit_sha": None,
            "pushed": False,
        }

    from .notes_store import create_export_job, update_export_job

    job = create_export_job(scope=scope, note_id=note_id, settings=resolved)
    try:
        update_export_job(job["id"], status="running", settings=resolved)
        use_git = sync or push
        pushed = False
        content_commit_sha = None
        if use_git:
            with git_operation_lock(resolved):
                if sync:
                    sync_main(resolved)
                stale_paths = find_stale_export_paths(items, resolved.vault_path) if scope == "full" else []
                changed_paths = write_export_items(items, resolved.vault_path)
                deleted_paths = delete_stale_export_paths(stale_paths, resolved.vault_path) if reconcile else []
                commit_sha = commit_all(
                    export_commit_message(str(job["id"]), items, changed_paths, deleted_paths=deleted_paths),
                    resolved,
                    repo_path=resolved.vault_path,
                )
                if commit_sha and push:
                    push_branch("main", resolved, repo_path=resolved.vault_path)
                    pushed = True
                content_commit_sha = commit_sha or run_git(
                    ["rev-parse", "HEAD"],
                    cwd=resolved.vault_path,
                ).stdout.strip()
        else:
            stale_paths = find_stale_export_paths(items, resolved.vault_path) if scope == "full" else []
            changed_paths = write_export_items(items, resolved.vault_path)
            deleted_paths = delete_stale_export_paths(stale_paths, resolved.vault_path) if reconcile else []
        updated_job = update_export_job(
            job["id"],
            status="succeeded",
            content_commit_sha=content_commit_sha,
            settings=resolved,
        )
        return {
            "job_id": job["id"],
            "status": updated_job["status"] if updated_job else "succeeded",
            "scope": scope,
            "note_id": note_id,
            "exported_count": len(items),
            "changed_paths": changed_paths,
            "stale_paths": stale_paths,
            "deleted_paths": deleted_paths,
            "reconcile": reconcile,
            "content_commit_sha": content_commit_sha,
            "pushed": pushed,
        }
    except Exception as exc:
        try:
            update_export_job(job["id"], status="failed", error_message=str(exc)[:2000], settings=resolved)
        except Exception:
            pass
        raise


def build_export_items(notes: Iterable[Mapping[str, object]]) -> list[ExportItem]:
    items = [ExportItem(str(note["id"]), export_path_for_note(note), render_note_markdown(note)) for note in notes]
    seen: dict[str, str] = {}
    for item in items:
        previous_note_id = seen.get(item.path)
        if previous_note_id and previous_note_id != item.note_id:
            raise RuntimeError(f"export path collision: {item.path}")
        seen[item.path] = item.note_id
    return items


def export_commit_message(
    job_id: str,
    items: Iterable[ExportItem],
    changed_paths: Iterable[str],
    *,
    deleted_paths: Iterable[str] = (),
) -> str:
    title = f"export: DB notes {job_id}"
    changed_path_set = set(changed_paths)
    deleted_path_list = list(deleted_paths)
    changed_items = [item for item in items if item.path in changed_path_set]
    if not changed_items and not deleted_path_list:
        return title
    lines = [title, "", f"Export job: {job_id}", "", "Changed notes:"]
    for item in changed_items[:25]:
        lines.append(f"- {item.note_id}: {item.path}")
    remaining = len(changed_items) - 25
    if remaining > 0:
        lines.append(f"- ... {remaining} more")
    if deleted_path_list:
        lines.extend(["", "Deleted stale export files:"])
        for path in deleted_path_list[:25]:
            lines.append(f"- {path}")
        remaining_deleted = len(deleted_path_list) - 25
        if remaining_deleted > 0:
            lines.append(f"- ... {remaining_deleted} more")
    return "\n".join(lines)


def export_path_for_note(note: Mapping[str, object]) -> str:
    kind = str(note.get("kind") or "inbox")
    slug = _safe_file_stem(str(note.get("slug") or note.get("id") or "note"))
    if kind == "archive":
        metadata = _metadata(note)
        channel = _safe_segment(
            str(metadata.get("channel") or metadata.get("source_channel") or "web"),
            fallback="web",
        )
        year, month = _year_month(note.get("archived_at") or note.get("updated_at") or note.get("created_at"))
        return f"archive/inbox/{channel}/{year}/{month}/{slug}.md"
    if kind == "inbox":
        channel = _safe_segment(str(_metadata(note).get("channel") or "web"), fallback="web")
        return f"inbox/{channel}/{slug}.md"
    directory = KIND_EXPORT_DIRS.get(kind, f"wiki/{_safe_segment(kind, fallback='notes')}")
    return f"{directory}/{slug}.md"


def render_note_markdown(note: Mapping[str, object]) -> str:
    metadata_json = json.dumps(_metadata(note), ensure_ascii=False, sort_keys=True, default=str)
    frontmatter = {
        "llm_wiki_note_id": note.get("id"),
        "kind": note.get("kind"),
        "status": note.get("status"),
        "title": note.get("title"),
        "slug": note.get("slug"),
        "version": note.get("version"),
        "parent_id": note.get("parent_id"),
        "source_note_id": note.get("source_note_id"),
        "created_at": _timestamp(note.get("created_at")),
        "updated_at": _timestamp(note.get("updated_at")),
        "archived_at": _timestamp(note.get("archived_at")),
        "metadata_json": metadata_json,
    }
    lines = ["---"]
    lines.extend(f"{key}: {_yaml_scalar(value)}" for key, value in frontmatter.items())
    lines.append("---")

    title = str(note.get("title") or "Untitled").strip() or "Untitled"
    body = str(note.get("body_markdown") or "").strip()
    if not body:
        rendered_body = f"# {title}"
    elif _starts_with_heading(body):
        rendered_body = body
    else:
        rendered_body = f"# {title}\n\n{body}"
    return "\n".join(lines) + "\n\n" + rendered_body.rstrip() + "\n"


def write_export_items(items: Iterable[ExportItem], root: Path) -> list[str]:
    changed_paths = []
    for item in items:
        target = _resolve_export_path(root, item.path)
        old_content = target.read_text(encoding="utf-8") if target.exists() else None
        if old_content == item.content:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.content, encoding="utf-8", newline="\n")
        changed_paths.append(item.path)
    return changed_paths


def paths_that_would_change(items: Iterable[ExportItem], root: Path) -> list[str]:
    changed_paths = []
    for item in items:
        target = _resolve_export_path(root, item.path)
        old_content = target.read_text(encoding="utf-8") if target.exists() else None
        if old_content != item.content:
            changed_paths.append(item.path)
    return changed_paths


def find_stale_export_paths(items: Iterable[ExportItem], root: Path) -> list[str]:
    expected_paths = {item.path for item in items}
    stale_paths = []
    for path in _iter_managed_markdown_paths(root):
        relative_path = path.relative_to(root).as_posix()
        if relative_path in expected_paths:
            continue
        if _is_generated_export_file(path):
            stale_paths.append(relative_path)
    return sorted(stale_paths)


def delete_stale_export_paths(stale_paths: Iterable[str], root: Path) -> list[str]:
    deleted_paths = []
    for stale_path in sorted(set(stale_paths)):
        target = _resolve_export_path(root, stale_path)
        if not target.exists() or not target.is_file():
            continue
        if not _is_generated_export_file(target):
            continue
        target.unlink()
        deleted_paths.append(stale_path)
        _remove_empty_export_dirs(target.parent, root)
    return deleted_paths


def _select_notes(*, scope: str, note_id: str | None, settings: Settings) -> list[dict]:
    from .notes_store import get_note, list_exportable_notes

    if scope == "note-id":
        row = get_note(str(note_id), settings)
        if not row or row.get("deleted_at") is not None:
            raise ValueError(f"exportable note not found: {note_id}")
        return [row]
    return list_exportable_notes(settings=settings)


def _resolve_export_path(root: Path, relative_path: str) -> Path:
    parts = [part for part in relative_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise RuntimeError(f"unsafe export path: {relative_path}")
    resolved_root = root.resolve()
    target = (resolved_root / Path(*parts)).resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise RuntimeError(f"export path escapes vault root: {relative_path}")
    return target


def _iter_managed_markdown_paths(root: Path):
    if not root.exists() or not root.is_dir():
        return
    for directory in MANAGED_EXPORT_DIRS:
        base = _resolve_export_path(root, directory)
        if not base.exists() or not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.is_file():
                yield path


def _is_generated_export_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return False
    return bool(re.search(r"(?m)^llm_wiki_note_id:\s*", text))


def _remove_empty_export_dirs(start: Path, root: Path) -> None:
    resolved_root = root.resolve()
    current = start.resolve()
    while current != resolved_root and resolved_root in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _metadata(note: Mapping[str, object]) -> dict:
    value = note.get("metadata")
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_file_stem(value: str) -> str:
    cleaned = re.sub(r"[\s_]+", "-", value.strip())
    cleaned = re.sub(r"[\\/<>:\"|?*\x00-\x1f]+", "-", cleaned)
    cleaned = cleaned.strip(".- ")
    return cleaned or "note"


def _safe_segment(value: str, *, fallback: str) -> str:
    cleaned = _safe_file_stem(value).lower()
    cleaned = re.sub(r"[^0-9a-zA-Z가-힣._-]+", "-", cleaned)
    cleaned = cleaned.strip(".- ")
    return cleaned or fallback


def _year_month(value: object) -> tuple[str, str]:
    if isinstance(value, datetime):
        return f"{value.year:04d}", f"{value.month:02d}"
    text = str(value or "")
    match = re.match(r"(\d{4})-(\d{2})", text)
    if match:
        return match.group(1), match.group(2)
    return "unknown", "unknown"


def _timestamp(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _starts_with_heading(body: str) -> bool:
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.startswith("#")
    return False
