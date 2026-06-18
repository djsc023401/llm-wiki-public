from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time
from urllib.parse import unquote, urlparse, urlunparse

from .config import Settings, load_settings
from .db import connect, fetch_all
from .git_tools import run_git


OBJECT_REF_SOURCES = {"db", "markdown"}


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def _make_private_file(path: Path) -> Path:
    path.chmod(0o600)
    return path


def create_repo_mirror_backup(target_dir: Path, settings: Settings | None = None) -> Path:
    resolved = settings or load_settings()
    _ensure_private_dir(target_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mirror = target_dir / f"llm-wiki-{stamp}.bundle"
    run_git(["bundle", "create", str(mirror), "--all"], cwd=resolved.vault_path)
    return _make_private_file(mirror)


def create_postgres_dump(target_dir: Path, settings: Settings | None = None) -> Path:
    resolved = settings or load_settings()
    _ensure_private_dir(target_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_path = target_dir / f"llm-wiki-app-db-{stamp}.sql"
    database_url, env = _postgres_command_connection(resolved.database_url)
    with dump_path.open("w", encoding="utf-8") as handle:
        subprocess.run(
            ["pg_dump", "--no-owner", "--no-privileges", database_url],
            check=True,
            text=True,
            stdout=handle,
            env=env,
        )
    return _make_private_file(dump_path)


def create_object_manifest(
    target_dir: Path,
    settings: Settings | None = None,
    *,
    verify: bool = False,
    source: str = "db",
) -> Path:
    resolved = settings or load_settings()
    _ensure_private_dir(target_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = target_dir / f"llm-wiki-objects-{stamp}.json"
    refs = _collect_object_refs(resolved, source=source)
    objects = []
    for ref in refs:
        item = {
            "bucket": resolved.s3_bucket,
            "key": ref["key"],
            "uri": f"s3://{resolved.s3_bucket}/{ref['key']}",
        }
        if ref.get("sources"):
            item["sources"] = ref["sources"]
        if verify:
            try:
                from .storage import head_object

                head = head_object(ref["key"], resolved)
                item.update(
                    {
                        "verified": True,
                        "size_bytes": head.get("size_bytes"),
                        "content_type": head.get("content_type"),
                        "sha256": head.get("sha256"),
                    }
                )
            except Exception as exc:
                item.update({"verified": False, "error": str(exc)})
        objects.append(item)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bucket": resolved.s3_bucket,
        "source": source,
        "verified": verify,
        "object_count": len(objects),
        "objects": objects,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return _make_private_file(manifest_path)


def create_object_archive(target_dir: Path, settings: Settings | None = None, *, source: str = "db") -> Path:
    resolved = settings or load_settings()
    _ensure_private_dir(target_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = target_dir / f"llm-wiki-objects-{stamp}.tar.gz"
    refs = _collect_object_refs(resolved, source=source)
    objects = []
    with tarfile.open(archive_path, "w:gz") as archive:
        for ref in refs:
            from .storage import get_object_bytes

            key = ref["key"]
            data, head = get_object_bytes(key, resolved)
            data_sha256 = hashlib.sha256(data).hexdigest()
            member_path = f"objects/{hashlib.sha256(key.encode('utf-8')).hexdigest()}.bin"
            info = tarfile.TarInfo(member_path)
            info.size = len(data)
            info.mode = 0o600
            info.mtime = int(time.time())
            archive.addfile(info, io.BytesIO(data))
            objects.append(
                {
                    "bucket": resolved.s3_bucket,
                    "key": key,
                    "uri": f"s3://{resolved.s3_bucket}/{key}",
                    "archive_path": member_path,
                    "size_bytes": len(data),
                    "sha256": data_sha256,
                    "source_sha256": head.get("sha256"),
                    "content_type": head.get("content_type"),
                    "etag": head.get("etag"),
                }
            )
            if ref.get("sources"):
                objects[-1]["sources"] = ref["sources"]
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "bucket": resolved.s3_bucket,
            "source": source,
            "object_count": len(objects),
            "objects": objects,
        }
        payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        info.mode = 0o600
        info.mtime = int(time.time())
        archive.addfile(info, io.BytesIO(payload))
    return _make_private_file(archive_path)


def cleanup_old_backups(target_dir: Path, *, older_than_days: int) -> list[dict]:
    target = target_dir.resolve()
    if not target.exists():
        return []
    if older_than_days < 1:
        raise RuntimeError("older_than_days must be >= 1")
    cutoff = time.time() - (older_than_days * 86400)
    removed = []
    for pattern in (
        "llm-wiki-*.bundle",
        "llm-wiki-app-db-*.sql",
        "llm-wiki-objects-*.json",
        "llm-wiki-objects-*.tar.gz",
        "llm-wiki-backup-run-*.json",
    ):
        for path in sorted(target.glob(pattern)):
            if not path.is_file() or path.stat().st_mtime >= cutoff:
                continue
            stat = path.stat()
            path.unlink()
            removed.append(
                {
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "mtime_epoch": int(stat.st_mtime),
                }
            )
    return removed


def restore_smoke_postgres_dump(
    dump_path: Path,
    database_url: str,
    *,
    source_database_url: str | None = None,
) -> dict:
    if source_database_url and database_url == source_database_url:
        raise RuntimeError("restore smoke database URL must not match the source database URL")
    command_database_url, env = _postgres_command_connection(database_url)
    try:
        result = subprocess.run(
            ["psql", command_database_url, "-v", "ON_ERROR_STOP=1", "-f", str(dump_path)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        table_count = subprocess.run(
            [
                "psql",
                command_database_url,
                "-At",
                "-c",
                "select count(*) from information_schema.tables where table_schema = 'public'",
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        output = "\n".join(part for part in [exc.stdout, exc.stderr] if part)
        raise RuntimeError(f"restore smoke postgres failed: {output[-4000:]}") from exc
    return {
        "ok": True,
        "dump_path": str(dump_path),
        "database_url": _redact_database_url(database_url),
        "table_count": int(table_count or "0"),
        "stdout_bytes": len(result.stdout.encode("utf-8")),
        "stderr_bytes": len(result.stderr.encode("utf-8")),
    }


def restore_smoke_object_archive(archive_path: Path, target_dir: Path | None = None) -> dict:
    restore_path = None
    if target_dir is not None:
        _ensure_private_dir(target_dir)
        restore_path = target_dir / f"objects-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        restore_path.mkdir(mode=0o700)
    with tarfile.open(archive_path, "r:gz") as archive:
        names = archive.getnames()
        if "manifest.json" not in names:
            raise RuntimeError("object archive is missing manifest.json")
        manifest_member = archive.extractfile("manifest.json")
        if manifest_member is None:
            raise RuntimeError("object archive manifest is not readable")
        manifest = json.loads(manifest_member.read().decode("utf-8"))
        objects = manifest.get("objects") if isinstance(manifest, dict) else None
        if not isinstance(objects, list):
            raise RuntimeError("object archive manifest objects must be a list")
        object_names = {name for name in names if name.startswith("objects/") and not name.endswith("/")}
        verified = []
        for item in objects:
            if not isinstance(item, dict):
                raise RuntimeError("object archive manifest item must be an object")
            archive_member_path = str(item.get("archive_path") or "")
            if archive_member_path not in object_names:
                raise RuntimeError(f"object archive member missing: {archive_member_path}")
            member = archive.extractfile(archive_member_path)
            if member is None:
                raise RuntimeError(f"object archive member is not readable: {archive_member_path}")
            data = member.read()
            expected_sha = item.get("sha256")
            actual_sha = hashlib.sha256(data).hexdigest()
            if expected_sha and actual_sha != expected_sha:
                raise RuntimeError(f"object archive sha256 mismatch: {archive_member_path}")
            expected_size = item.get("size_bytes")
            if expected_size is not None and len(data) != int(expected_size):
                raise RuntimeError(f"object archive size mismatch: {archive_member_path}")
            if restore_path is not None:
                target = _safe_restore_member_path(restore_path, archive_member_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(0o600)
            verified.append(archive_member_path)
    return {
        "ok": True,
        "archive_path": str(archive_path),
        "restore_path": str(restore_path) if restore_path else None,
        "object_count": int(manifest.get("object_count", len(objects))),
        "verified_count": len(verified),
    }


def restore_smoke_markdown_export(
    target_dir: Path,
    *,
    database_url: str,
    settings: Settings | None = None,
) -> dict:
    from .export_mirror import export_notes_to_markdown

    resolved = settings or load_settings()
    _ensure_private_dir(target_dir)
    mirror_path = target_dir / f"mirror-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    mirror_path.mkdir(mode=0o700)
    smoke_settings = replace(
        resolved,
        database_url=database_url,
        vault_path=mirror_path,
        mirror_git_push_enabled=False,
    )
    result = export_notes_to_markdown(
        smoke_settings,
        scope="full",
        dry_run=False,
        sync=False,
        push=False,
        reconcile=True,
    )
    return {
        "ok": result.get("status") == "succeeded",
        "mirror_path": str(mirror_path),
        "exported_count": result.get("exported_count"),
        "changed_paths": result.get("changed_paths", []),
        "deleted_paths": result.get("deleted_paths", []),
    }


def restore_smoke_bundle(
    bundle_path: Path,
    target_dir: Path,
    *,
    expected_head: str | None = None,
    required_paths: list[str] | None = None,
) -> dict:
    required_paths = required_paths or ["docs/vault-structure.md", "docs/markdown-rules.md"]
    _ensure_private_dir(target_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    restore_path = target_dir / f"repo-{stamp}"
    if restore_path.exists():
        raise RuntimeError(f"restore target already exists: {restore_path}")
    run_git(["clone", str(bundle_path), str(restore_path)], cwd=target_dir)
    head = run_git(["rev-parse", "HEAD"], cwd=restore_path).stdout.strip()
    missing = [path for path in required_paths if not (restore_path / path).exists()]
    expected_ok = expected_head is None or head.startswith(expected_head) or expected_head.startswith(head)
    return {
        "ok": not missing and expected_ok,
        "restore_path": str(restore_path),
        "head": head,
        "expected_head": expected_head,
        "expected_head_ok": expected_ok,
        "required_paths": required_paths,
        "missing_paths": missing,
    }


def _collect_object_refs(settings: Settings, *, source: str) -> list[dict]:
    if source not in OBJECT_REF_SOURCES:
        expected = ", ".join(sorted(OBJECT_REF_SOURCES))
        raise ValueError(f"invalid object reference source: {source}; expected one of {expected}")
    if source == "db":
        return _collect_db_object_refs(settings)
    return [{"key": key, "sources": [{"kind": "markdown"}]} for key in _collect_markdown_object_keys(settings.vault_path, settings.s3_bucket)]


def _collect_db_object_refs(settings: Settings) -> list[dict]:
    with connect(settings) as conn:
        rows = fetch_all(
            conn,
            """
            select 'note_asset' as source_kind, id as source_id, note_id as owner_id,
                   object_key, file_name, content_type, size_bytes, sha256, created_at
              from note_assets
            union all
            select 'processing_attachment' as source_kind, id as source_id, request_id as owner_id,
                   object_key, file_name, content_type, size_bytes, sha256, created_at
              from processing_attachments
             order by object_key, created_at
            """,
        )
    refs: dict[str, dict] = {}
    for row in rows:
        key = str(row["object_key"])
        item = refs.setdefault(
            key,
            {
                "key": key,
                "file_name": row.get("file_name"),
                "content_type": row.get("content_type"),
                "size_bytes": row.get("size_bytes"),
                "sha256": row.get("sha256"),
                "sources": [],
            },
        )
        item["sources"].append(
            {
                "kind": row.get("source_kind"),
                "id": row.get("source_id"),
                "owner_id": row.get("owner_id"),
                "file_name": row.get("file_name"),
            }
        )
    return [refs[key] for key in sorted(refs)]


def _collect_markdown_object_keys(vault_path: Path, bucket: str) -> list[str]:
    pattern = re.compile(rf"s3://{re.escape(bucket)}/([^\s\]\)`\"']+)")
    refs: set[str] = set()
    for path in sorted(vault_path.rglob("*.md")):
        rel = path.relative_to(vault_path).as_posix()
        if ".git" in path.parts or rel.startswith("docs/examples/"):
            continue
        text = path.read_text(encoding="utf-8")
        refs.update(match.group(1).rstrip(",") for match in pattern.finditer(text))
    return sorted(refs)


def _safe_restore_member_path(root: Path, member_path: str) -> Path:
    target = (root / member_path).resolve()
    resolved_root = root.resolve()
    if target == resolved_root or resolved_root not in target.parents:
        raise RuntimeError(f"unsafe object archive member path: {member_path}")
    return target


def _redact_database_url(value: str) -> str:
    return re.sub(r":([^:@/]+)@", ":***@", value)


def _postgres_command_connection(database_url: str) -> tuple[str, dict[str, str] | None]:
    parsed = urlparse(database_url)
    if not parsed.password or "@" not in parsed.netloc:
        return database_url, None
    userinfo, hostinfo = parsed.netloc.rsplit("@", 1)
    username = userinfo.split(":", 1)[0]
    safe_url = urlunparse(parsed._replace(netloc=f"{username}@{hostinfo}"))
    env = os.environ.copy()
    env["PGPASSWORD"] = unquote(parsed.password)
    return safe_url, env
