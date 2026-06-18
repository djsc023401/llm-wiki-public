from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .config import Settings, load_settings


IMPORT_MODES = {"dry-run", "apply"}


@dataclass(frozen=True)
class ImportCandidate:
    path: str
    kind: str
    status: str
    title: str
    slug: str
    body_markdown: str
    metadata: dict
    note_id: str | None = None


@dataclass(frozen=True)
class InvalidImportFile:
    path: str
    reason: str


IGNORED_NAMES = {"README.md", "AGENTS.md", "index.md"}
SUPPORTED_WIKI_KINDS = {
    "sources": "source",
    "topics": "topic",
    "entities": "entity",
    "logs": "log",
}
STATUS_MAP = {
    "draft": "draft",
    "active": "active",
    "archived": "archived",
    "deleted": "deleted",
    "needs_review": "needs_review",
    "stale": "needs_review",
}


def import_vault_notes(
    vault_path: Path,
    *,
    mode: str,
    settings: Settings | None = None,
) -> dict:
    if mode not in IMPORT_MODES:
        expected = ", ".join(sorted(IMPORT_MODES))
        raise ValueError(f"invalid import mode: {mode}; expected one of {expected}")
    resolved = settings or load_settings()
    report = _build_import_report(vault_path, settings=resolved)
    if mode == "dry-run":
        report["mode"] = mode
        return _public_report(report)

    imported = []
    errors = []
    for item in report["candidates"]:
        path = item["path"]
        if path in report["existing_paths"]:
            continue
        candidate = item["candidate"]
        try:
            row = _create_imported_note(candidate, resolved)
            imported.append({"path": path, "note_id": row["id"], "kind": row["kind"], "slug": row["slug"]})
        except Exception as exc:
            errors.append({"path": path, "reason": str(exc)})

    result = dict(report)
    result["mode"] = mode
    result["imported"] = imported
    result["imported_count"] = len(imported)
    result["apply_errors"] = errors
    result["status"] = "failed" if errors else "succeeded"
    return _public_report(result)


def build_import_report(vault_path: Path, *, settings: Settings | None = None) -> dict:
    return _public_report(_build_import_report(vault_path, settings=settings))


def _build_import_report(vault_path: Path, *, settings: Settings | None = None) -> dict:
    root = vault_path.resolve()
    candidates: list[ImportCandidate] = []
    invalid_files: list[InvalidImportFile] = []
    ignored_files: list[str] = []
    for path in _iter_markdown(root):
        rel = path.relative_to(root).as_posix()
        if _is_ignored_markdown(path, rel):
            ignored_files.append(rel)
            continue
        try:
            candidate = parse_import_candidate(root, path)
        except ValueError as exc:
            invalid_files.append(InvalidImportFile(rel, str(exc)))
            continue
        candidates.append(candidate)

    existing_paths: dict[str, str] = {}
    if settings:
        existing_paths = _find_existing_notes(candidates, settings)

    counts_by_kind = Counter(candidate.kind for candidate in candidates)
    existing_counts_by_kind = Counter(candidate.kind for candidate in candidates if candidate.path in existing_paths)
    report = {
        "vault_path": str(root),
        "total_markdown_files": len(candidates) + len(invalid_files) + len(ignored_files),
        "importable_count": len(candidates),
        "new_count": len([candidate for candidate in candidates if candidate.path not in existing_paths]),
        "existing_count": len(existing_paths),
        "ignored_count": len(ignored_files),
        "invalid_count": len(invalid_files),
        "counts_by_kind": dict(sorted(counts_by_kind.items())),
        "new_counts_by_kind": dict(
            sorted((counts_by_kind - existing_counts_by_kind).items())
        ),
        "existing_counts_by_kind": dict(sorted(existing_counts_by_kind.items())),
        "invalid_files": [invalid.__dict__ for invalid in invalid_files],
        "ignored_files": ignored_files,
        "existing_paths": existing_paths,
        "candidates": [{"path": candidate.path, "candidate": candidate} for candidate in candidates],
    }
    return report


def parse_import_candidate(root: Path, path: Path) -> ImportCandidate:
    rel = path.relative_to(root).as_posix()
    mapping = _map_path(rel)
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_markdown(text)
    title = _title(frontmatter, body, path)
    slug = _slug(frontmatter, path)
    source_refs = _list_value(frontmatter.get("source_refs"))
    metadata = {
        "original_path": rel,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "imported_from": "vault",
        "frontmatter": frontmatter,
    }
    if source_refs:
        metadata["source_refs"] = source_refs
    if mapping.get("channel"):
        metadata["channel"] = mapping["channel"]
    if mapping.get("archive_year"):
        metadata["archive_year"] = mapping["archive_year"]
        metadata["archive_month"] = mapping["archive_month"]
    llm_wiki_note_id = _clean_optional_text(frontmatter.get("llm_wiki_note_id"))
    if llm_wiki_note_id:
        metadata["llm_wiki_note_id"] = llm_wiki_note_id
    status = _status(frontmatter, mapping["default_status"])
    return ImportCandidate(
        path=rel,
        kind=mapping["kind"],
        status=status,
        title=title,
        slug=slug,
        body_markdown=body.strip(),
        metadata=metadata,
        note_id=llm_wiki_note_id,
    )


def parse_markdown(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    data: dict[str, object] = {}
    current_list: str | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body = "\n".join(lines[index + 1 :])
            if text.endswith("\n"):
                body += "\n"
            return data, body
        if current_list and re.match(r"\s+-\s+", line):
            data.setdefault(current_list, []).append(_parse_scalar(re.sub(r"^\s+-\s+", "", line).strip()))
            continue
        current_list = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value == "":
            data[key] = []
            current_list = key
        else:
            data[key] = _parse_scalar(value)
    return {}, text


def _create_imported_note(candidate: ImportCandidate, settings: Settings) -> dict:
    from .notes_store import create_note

    payload = {
        "kind": candidate.kind,
        "status": candidate.status,
        "title": candidate.title,
        "slug": candidate.slug,
        "body_markdown": candidate.body_markdown,
        "metadata": {
            **candidate.metadata,
            "imported_at": datetime.now(timezone.utc).isoformat(),
        },
        "change_source": "import",
        "created_by": "vault-import",
    }
    if candidate.note_id:
        payload["id"] = candidate.note_id
    return create_note(payload, settings)


def _find_existing_notes(candidates: list[ImportCandidate], settings: Settings) -> dict[str, str]:
    from .notes_store import get_note, get_note_by_original_path

    existing = {}
    for candidate in candidates:
        if candidate.note_id:
            row = get_note(candidate.note_id, settings)
            if row:
                existing[candidate.path] = row["id"]
                continue
        row = get_note_by_original_path(candidate.path, settings)
        if row:
            existing[candidate.path] = row["id"]
    return existing


def _iter_markdown(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if ".git" not in path.parts and ".obsidian" not in path.parts)


def _is_ignored_markdown(path: Path, rel: str) -> bool:
    if path.name in IGNORED_NAMES:
        return True
    if rel.startswith(("docs/", "scripts/", "raw/", "assets/")):
        return True
    return False


def _map_path(rel: str) -> dict[str, str]:
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "inbox":
        return {"kind": "inbox", "default_status": "draft", "channel": parts[1]}
    if len(parts) >= 6 and parts[:2] == ["archive", "inbox"]:
        return {
            "kind": "archive",
            "default_status": "archived",
            "channel": parts[2],
            "archive_year": parts[3],
            "archive_month": parts[4],
        }
    if len(parts) >= 3 and parts[0] == "wiki" and parts[1] in SUPPORTED_WIKI_KINDS:
        return {"kind": SUPPORTED_WIKI_KINDS[parts[1]], "default_status": "active"}
    if len(parts) >= 2 and parts[0] == "logs":
        return {"kind": "log", "default_status": "active"}
    if len(parts) >= 2 and parts[0] == "templates":
        return {"kind": "template", "default_status": "draft"}
    raise ValueError("unsupported import path")


def _title(frontmatter: Mapping[str, object], body: str, path: Path) -> str:
    title = _clean_optional_text(frontmatter.get("title"))
    if title:
        return title
    for line in body.splitlines():
        cleaned = line.strip()
        if cleaned.startswith("#"):
            title = cleaned.lstrip("#").strip()
            if title:
                return title[:300]
    return path.stem[:300]


def _slug(frontmatter: Mapping[str, object], path: Path) -> str:
    slug = _clean_optional_text(frontmatter.get("slug"))
    return slug or path.stem


def _status(frontmatter: Mapping[str, object], default: str) -> str:
    value = _clean_optional_text(frontmatter.get("status"))
    if not value:
        return default
    return STATUS_MAP.get(value, default)


def _list_value(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _parse_scalar(value: str) -> object:
    if value == "[]":
        return []
    if value in {"null", "~"}:
        return None
    if value in {"true", "false"}:
        return value == "true"
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value.strip('"').strip("'")


def _public_report(report: dict) -> dict:
    cleaned = dict(report)
    cleaned.pop("candidates", None)
    return cleaned
