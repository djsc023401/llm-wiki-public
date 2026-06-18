from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import tarfile
import time
from types import SimpleNamespace

from llm_wiki.backup import (
    cleanup_old_backups,
    create_object_archive,
    create_object_manifest,
    create_postgres_dump,
    create_repo_mirror_backup,
    restore_smoke_object_archive,
    restore_smoke_bundle,
    restore_smoke_postgres_dump,
)
from llm_wiki.config import Settings
from llm_wiki.git_tools import run_git


SimpleCompletedProcess = SimpleNamespace


def test_restore_smoke_bundle_verifies_head_and_required_paths(tmp_path: Path):
    vault = _git_vault(tmp_path)
    settings = _settings(tmp_path, vault)
    head = run_git(["rev-parse", "HEAD"], cwd=vault).stdout.strip()
    bundle = create_repo_mirror_backup(tmp_path / "backups", settings)

    result = restore_smoke_bundle(
        bundle,
        tmp_path / "restore-smoke",
        expected_head=head,
        required_paths=["docs/vault-structure.md", "docs/markdown-rules.md"],
    )

    assert result["ok"]
    assert result["head"] == head
    assert result["missing_paths"] == []
    assert Path(result["restore_path"], "docs", "vault-structure.md").exists()


def test_object_manifest_collects_s3_refs_without_verification(tmp_path: Path):
    vault = tmp_path / "vault"
    note = vault / "wiki" / "sources" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "\n".join(
            [
                "---",
                "object_refs:",
                "  - s3://llm-wiki/assets/a.txt",
                "---",
                "",
                "Embedded s3://llm-wiki/raw/source.md reference.",
            ]
        ),
        encoding="utf-8",
    )

    manifest = create_object_manifest(tmp_path / "backups", _settings(tmp_path, vault), verify=False, source="markdown")
    data = json.loads(manifest.read_text(encoding="utf-8"))

    if os.name != "nt":
        assert manifest.stat().st_mode & 0o777 == 0o600
    assert data["object_count"] == 2
    assert {item["key"] for item in data["objects"]} == {"assets/a.txt", "raw/source.md"}


def test_object_manifest_ignores_example_placeholders_and_backtick_boundaries(tmp_path: Path):
    vault = tmp_path / "vault"
    real_note = vault / "wiki" / "sources" / "note.md"
    example = vault / "docs" / "examples" / "source-example.md"
    real_note.parent.mkdir(parents=True)
    example.parent.mkdir(parents=True)
    real_note.write_text("Object ref: `s3://llm-wiki/assets/a.txt`\n", encoding="utf-8")
    example.write_text("Placeholder: s3://llm-wiki/raw/examples/source.txt\n", encoding="utf-8")

    manifest = create_object_manifest(tmp_path / "backups", _settings(tmp_path, vault), verify=False, source="markdown")
    data = json.loads(manifest.read_text(encoding="utf-8"))

    assert data["object_count"] == 1
    assert data["objects"][0]["key"] == "assets/a.txt"


def test_object_manifest_can_verify_s3_refs(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    note = vault / "wiki" / "sources" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("s3://llm-wiki/assets/a.txt\n", encoding="utf-8")

    def fake_head_object(key: str, settings=None):
        assert key == "assets/a.txt"
        return {"size_bytes": 12, "content_type": "text/plain", "sha256": "abc123"}

    monkeypatch.setattr("llm_wiki.storage.head_object", fake_head_object)

    manifest = create_object_manifest(tmp_path / "backups", _settings(tmp_path, vault), verify=True, source="markdown")
    data = json.loads(manifest.read_text(encoding="utf-8"))

    assert data["verified"] is True
    assert data["objects"] == [
        {
            "bucket": "llm-wiki",
            "key": "assets/a.txt",
            "uri": "s3://llm-wiki/assets/a.txt",
            "sources": [{"kind": "markdown"}],
            "verified": True,
            "size_bytes": 12,
            "content_type": "text/plain",
            "sha256": "abc123",
        }
    ]


def test_object_archive_downloads_referenced_s3_objects(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    note = vault / "wiki" / "sources" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("s3://llm-wiki/assets/a.txt\n", encoding="utf-8")

    def fake_get_object_bytes(key: str, settings=None):
        assert key == "assets/a.txt"
        return b"hello object", {"content_type": "text/plain", "sha256": "source-sha", "etag": "etag"}

    monkeypatch.setattr("llm_wiki.storage.get_object_bytes", fake_get_object_bytes)

    archive = create_object_archive(tmp_path / "backups", _settings(tmp_path, vault), source="markdown")

    if os.name != "nt":
        assert archive.stat().st_mode & 0o777 == 0o600
    with tarfile.open(archive, "r:gz") as handle:
        names = handle.getnames()
        assert "manifest.json" in names
        object_names = [name for name in names if name.startswith("objects/")]
        assert len(object_names) == 1
        assert handle.extractfile(object_names[0]).read() == b"hello object"
        manifest = json.loads(handle.extractfile("manifest.json").read().decode("utf-8"))

    assert manifest["object_count"] == 1
    assert manifest["objects"][0]["key"] == "assets/a.txt"
    assert manifest["objects"][0]["sha256"] != manifest["objects"][0]["source_sha256"]
    assert manifest["objects"][0]["source_sha256"] == "source-sha"


def test_postgres_dump_omits_owner_and_acl_for_restore_portability(tmp_path: Path, monkeypatch):
    settings = replace(_settings(tmp_path, tmp_path / "vault"), database_url="postgresql://dump:secret@db/dump")
    calls = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, "env": kwargs.get("env")})
        kwargs["stdout"].write("-- portable dump\n")
        return SimpleCompletedProcess(stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    dump = create_postgres_dump(tmp_path / "backups", settings)

    assert dump.read_text(encoding="utf-8") == "-- portable dump\n"
    assert calls[0]["command"] == ["pg_dump", "--no-owner", "--no-privileges", "postgresql://dump@db/dump"]
    assert calls[0]["env"]["PGPASSWORD"] == "secret"


def test_object_manifest_defaults_to_db_asset_metadata(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path, tmp_path / "vault")

    monkeypatch.setattr(
        "llm_wiki.backup._collect_db_object_refs",
        lambda loaded_settings: [
            {
                "key": "assets/db-file.txt",
                "sources": [
                    {
                        "kind": "note_asset",
                        "id": "asset_test",
                        "owner_id": "note_test",
                        "file_name": "db-file.txt",
                    }
                ],
            }
        ],
    )

    manifest = create_object_manifest(tmp_path / "backups", settings, verify=False)
    data = json.loads(manifest.read_text(encoding="utf-8"))

    assert data["source"] == "db"
    assert data["object_count"] == 1
    assert data["objects"][0]["key"] == "assets/db-file.txt"
    assert data["objects"][0]["sources"][0]["owner_id"] == "note_test"


def test_object_archive_restore_smoke_verifies_manifest_and_bytes(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path, tmp_path / "vault")

    monkeypatch.setattr(
        "llm_wiki.backup._collect_db_object_refs",
        lambda loaded_settings: [{"key": "assets/from-db.bin", "sources": [{"kind": "note_asset"}]}],
    )
    monkeypatch.setattr(
        "llm_wiki.storage.get_object_bytes",
        lambda key, settings=None: (b"object data", {"content_type": "application/octet-stream", "sha256": "source"}),
    )

    archive = create_object_archive(tmp_path / "backups", settings)
    result = restore_smoke_object_archive(archive, tmp_path / "restore-objects")

    assert result["ok"] is True
    assert result["object_count"] == 1
    assert result["verified_count"] == 1
    assert Path(result["restore_path"], "objects").exists()


def test_restore_smoke_postgres_dump_imports_into_separate_database(tmp_path: Path, monkeypatch):
    dump = tmp_path / "dump.sql"
    dump.write_text("-- dump\n", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, "env": kwargs.get("env")})
        stdout = "5\n" if "-At" in command else "restored"
        return SimpleCompletedProcess(stdout=stdout, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = restore_smoke_postgres_dump(
        dump,
        "postgresql://restore:secret@db/restore",
        source_database_url="postgresql://source:secret@db/source",
    )

    assert result["ok"] is True
    assert result["database_url"] == "postgresql://restore:***@db/restore"
    assert result["table_count"] == 5
    assert calls[0]["command"][:2] == ["psql", "postgresql://restore@db/restore"]
    assert calls[1]["command"][:3] == ["psql", "postgresql://restore@db/restore", "-At"]
    assert calls[0]["env"]["PGPASSWORD"] == "secret"
    assert calls[1]["env"]["PGPASSWORD"] == "secret"


def test_cleanup_old_backups_removes_only_known_old_backup_files(tmp_path: Path):
    target = tmp_path / "backups"
    target.mkdir()
    old_bundle = target / "llm-wiki-old.bundle"
    old_dump = target / "llm-wiki-app-db-old.sql"
    old_manifest = target / "llm-wiki-objects-old.json"
    old_object_archive = target / "llm-wiki-objects-old.tar.gz"
    old_backup_run = target / "llm-wiki-backup-run-old.json"
    keep = target / "notes.txt"
    for path in [old_bundle, old_dump, old_manifest, old_object_archive, old_backup_run, keep]:
        path.write_text("x", encoding="utf-8")
        old = time.time() - (3 * 86400)
        os.utime(path, (old, old))

    removed = cleanup_old_backups(target, older_than_days=1)

    assert {Path(row["path"]).name for row in removed} == {
        old_bundle.name,
        old_dump.name,
        old_manifest.name,
        old_object_archive.name,
        old_backup_run.name,
    }
    assert keep.exists()


def _git_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "docs").mkdir()
    (vault / "docs" / "vault-structure.md").write_text("# Vault Structure\n", encoding="utf-8")
    (vault / "docs" / "markdown-rules.md").write_text("# Markdown Rules\n", encoding="utf-8")
    run_git(["init"], cwd=vault)
    run_git(["config", "user.name", "pytest"], cwd=vault)
    run_git(["config", "user.email", "pytest@example.invalid"], cwd=vault)
    run_git(["add", "-A"], cwd=vault)
    run_git(["commit", "-m", "initial"], cwd=vault)
    return vault


def _settings(tmp_path: Path, vault: Path) -> Settings:
    return Settings(
        database_url="postgresql://unused",
        api_token=None,
        vault_path=vault,
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
