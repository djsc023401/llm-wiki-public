from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from llm_wiki.config import Settings
from llm_wiki.export_mirror import (
    build_export_items,
    delete_stale_export_paths,
    export_commit_message,
    export_notes_to_markdown,
    export_path_for_note,
    find_stale_export_paths,
    render_note_markdown,
    write_export_items,
)
from llm_wiki.notes_store import create_note, get_latest_export_job_for_note


def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://unused",
        api_token=None,
        vault_path=tmp_path / "mirror",
        app_base_url="http://127.0.0.1:8080",
        repo_full_name="local/llm-wiki",
        s3_endpoint=None,
        s3_bucket="llm-wiki",
        s3_access_key_id=None,
        s3_secret_access_key=None,
        s3_region="us-east-1",
        worker_max_attempts=3,
        worker_retry_backoff_seconds=300,
        worker_heartbeat_interval=15,
    )


def note(**overrides):
    base = {
        "id": "note_test_export",
        "kind": "source",
        "status": "active",
        "title": "Export Target",
        "slug": "export-target",
        "body_markdown": "Body text",
        "metadata": {"channel": "web", "tag": "pytest"},
        "parent_id": None,
        "source_note_id": None,
        "archived_at": None,
        "created_at": datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 6, 4, 12, 5, tzinfo=timezone.utc),
        "version": 2,
        "deleted_at": None,
    }
    base.update(overrides)
    return base


def test_export_paths_follow_note_kind_and_archive_channel():
    assert export_path_for_note(note(kind="source", slug="daily-source")) == "wiki/sources/daily-source.md"
    assert export_path_for_note(note(kind="topic", slug="climate-2025")) == "wiki/topics/climate-2025.md"
    assert export_path_for_note(note(kind="entity", slug="openai")) == "wiki/entities/openai.md"
    assert export_path_for_note(note(kind="log", slug="trial-feedback")) == "logs/trial-feedback.md"
    assert export_path_for_note(note(kind="inbox", slug="new-note", metadata={"channel": "manual"})) == (
        "inbox/manual/new-note.md"
    )
    archived = note(
        kind="archive",
        status="archived",
        slug="새로운-메모-어플",
        metadata={"channel": "manual"},
        archived_at=datetime(2026, 6, 4, 13, 0, tzinfo=timezone.utc),
    )

    assert export_path_for_note(archived) == "archive/inbox/manual/2026/06/새로운-메모-어플.md"


def test_render_note_markdown_has_stable_frontmatter_and_single_heading():
    rendered = render_note_markdown(note(body_markdown="# Export Target\n\nExisting heading"))

    assert rendered.startswith("---\n")
    assert 'llm_wiki_note_id: "note_test_export"\n' in rendered
    assert 'metadata_json: "{\\"channel\\": \\"web\\", \\"tag\\": \\"pytest\\"}"\n' in rendered
    assert rendered.count("# Export Target") == 1


def test_write_export_items_is_idempotent(tmp_path):
    items = build_export_items([note(slug="first"), note(id="note_second", kind="topic", slug="second")])

    first_write = write_export_items(items, tmp_path)
    second_write = write_export_items(items, tmp_path)

    assert first_write == ["wiki/sources/first.md", "wiki/topics/second.md"]
    assert second_write == []
    assert (tmp_path / "wiki" / "sources" / "first.md").read_text(encoding="utf-8").endswith("Body text\n")


def test_export_commit_message_records_changed_note_ids():
    items = build_export_items([note(slug="first"), note(id="note_second", kind="topic", slug="second")])

    message = export_commit_message("export_test", items, ["wiki/topics/second.md"], deleted_paths=["wiki/sources/stale.md"])

    assert message.startswith("export: DB notes export_test")
    assert "Export job: export_test" in message
    assert "- note_second: wiki/topics/second.md" in message
    assert "note_test_export: wiki/sources/first.md" not in message
    assert "Deleted stale export files:" in message
    assert "- wiki/sources/stale.md" in message


def test_find_stale_export_paths_only_reports_generated_markdown(tmp_path):
    mirror = tmp_path / "mirror"
    generated = mirror / "wiki" / "sources" / "old.md"
    manual = mirror / "wiki" / "sources" / "manual.md"
    current = mirror / "wiki" / "sources" / "current.md"
    generated.parent.mkdir(parents=True)
    generated.write_text('---\nllm_wiki_note_id: "note_old"\n---\n\n# Old\n', encoding="utf-8")
    manual.write_text("# Manual note\n", encoding="utf-8")
    current.write_text('---\nllm_wiki_note_id: "note_current"\n---\n\n# Current\n', encoding="utf-8")
    items = [note(id="note_current", slug="current")]

    stale = find_stale_export_paths(build_export_items(items), mirror)

    assert stale == ["wiki/sources/old.md"]
    assert generated.exists()
    assert manual.exists()
    assert current.exists()


def test_delete_stale_export_paths_keeps_unmarked_files(tmp_path):
    mirror = tmp_path / "mirror"
    generated = mirror / "wiki" / "sources" / "old.md"
    manual = mirror / "wiki" / "sources" / "manual.md"
    generated.parent.mkdir(parents=True)
    generated.write_text('---\nllm_wiki_note_id: "note_old"\n---\n\n# Old\n', encoding="utf-8")
    manual.write_text("# Manual note\n", encoding="utf-8")

    deleted = delete_stale_export_paths(["wiki/sources/old.md", "wiki/sources/manual.md"], mirror)

    assert deleted == ["wiki/sources/old.md"]
    assert not generated.exists()
    assert manual.exists()


def test_export_notes_to_markdown_local_only_does_not_call_git(tmp_path, monkeypatch):
    export_settings = settings(tmp_path)

    def fail_git_call(*_args, **_kwargs):
        raise AssertionError("Git should not be called for local-only export")

    monkeypatch.setattr("llm_wiki.export_mirror.sync_main", fail_git_call)
    monkeypatch.setattr("llm_wiki.export_mirror.commit_all", fail_git_call)
    monkeypatch.setattr("llm_wiki.export_mirror.push_branch", fail_git_call)
    monkeypatch.setattr("llm_wiki.export_mirror.run_git", fail_git_call)
    monkeypatch.setattr("llm_wiki.export_mirror._select_notes", lambda **_kwargs: [note(slug="local-only")])
    monkeypatch.setattr("llm_wiki.notes_store.create_export_job", lambda **_kwargs: {"id": "export_local"})

    def fake_update_export_job(job_id, *, status, content_commit_sha=None, error_message=None, settings=None):
        return {
            "id": job_id,
            "status": status,
            "content_commit_sha": content_commit_sha,
            "error_message": error_message,
        }

    monkeypatch.setattr("llm_wiki.notes_store.update_export_job", fake_update_export_job)

    result = export_notes_to_markdown(
        export_settings,
        scope="note-id",
        note_id="note_test_export",
        dry_run=False,
        sync=False,
        push=False,
    )

    assert result["status"] == "succeeded"
    assert result["changed_paths"] == ["wiki/sources/local-only.md"]
    assert result["content_commit_sha"] is None
    assert result["pushed"] is False
    exported = export_settings.vault_path / "wiki" / "sources" / "local-only.md"
    assert "Body text" in exported.read_text(encoding="utf-8")


def test_export_notes_to_markdown_full_reconcile_deletes_stale_generated_files(tmp_path, monkeypatch):
    export_settings = settings(tmp_path)
    stale = export_settings.vault_path / "wiki" / "sources" / "stale.md"
    manual = export_settings.vault_path / "wiki" / "sources" / "manual.md"
    stale.parent.mkdir(parents=True)
    stale.write_text('---\nllm_wiki_note_id: "note_stale"\n---\n\n# Stale\n', encoding="utf-8")
    manual.write_text("# Manual note\n", encoding="utf-8")

    def fail_git_call(*_args, **_kwargs):
        raise AssertionError("Git should not be called for local reconciliation")

    monkeypatch.setattr("llm_wiki.export_mirror.sync_main", fail_git_call)
    monkeypatch.setattr("llm_wiki.export_mirror.commit_all", fail_git_call)
    monkeypatch.setattr("llm_wiki.export_mirror.push_branch", fail_git_call)
    monkeypatch.setattr("llm_wiki.export_mirror.run_git", fail_git_call)
    monkeypatch.setattr("llm_wiki.export_mirror._select_notes", lambda **_kwargs: [note(slug="current")])
    monkeypatch.setattr("llm_wiki.notes_store.create_export_job", lambda **_kwargs: {"id": "export_reconcile"})
    monkeypatch.setattr(
        "llm_wiki.notes_store.update_export_job",
        lambda job_id, *, status, content_commit_sha=None, error_message=None, settings=None: {
            "id": job_id,
            "status": status,
            "content_commit_sha": content_commit_sha,
            "error_message": error_message,
        },
    )

    result = export_notes_to_markdown(
        export_settings,
        scope="full",
        dry_run=False,
        sync=False,
        push=False,
        reconcile=True,
    )

    assert result["status"] == "succeeded"
    assert result["changed_paths"] == ["wiki/sources/current.md"]
    assert result["stale_paths"] == ["wiki/sources/stale.md"]
    assert result["deleted_paths"] == ["wiki/sources/stale.md"]
    assert result["reconcile"] is True
    assert not stale.exists()
    assert manual.exists()
    assert (export_settings.vault_path / "wiki" / "sources" / "current.md").exists()


def test_export_notes_to_markdown_reconcile_uses_post_sync_state(tmp_path, monkeypatch):
    export_settings = settings(tmp_path)
    stale = export_settings.vault_path / "wiki" / "sources" / "stale-after-sync.md"
    captured = {}

    def fake_sync(_settings):
        stale.parent.mkdir(parents=True)
        stale.write_text('---\nllm_wiki_note_id: "note_stale_after_sync"\n---\n\n# Stale\n', encoding="utf-8")

    def fake_commit(message, *_args, **_kwargs):
        captured["message"] = message
        return "commit_after_sync"

    monkeypatch.setattr("llm_wiki.export_mirror.sync_main", fake_sync)
    monkeypatch.setattr("llm_wiki.export_mirror.commit_all", fake_commit)
    monkeypatch.setattr("llm_wiki.export_mirror.push_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("llm_wiki.export_mirror.run_git", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("llm_wiki.export_mirror._select_notes", lambda **_kwargs: [note(slug="current")])
    monkeypatch.setattr("llm_wiki.notes_store.create_export_job", lambda **_kwargs: {"id": "export_sync_reconcile"})
    monkeypatch.setattr(
        "llm_wiki.notes_store.update_export_job",
        lambda job_id, *, status, content_commit_sha=None, error_message=None, settings=None: {
            "id": job_id,
            "status": status,
            "content_commit_sha": content_commit_sha,
            "error_message": error_message,
        },
    )

    result = export_notes_to_markdown(
        export_settings,
        scope="full",
        dry_run=False,
        sync=True,
        push=False,
        reconcile=True,
    )

    assert result["status"] == "succeeded"
    assert result["stale_paths"] == ["wiki/sources/stale-after-sync.md"]
    assert result["deleted_paths"] == ["wiki/sources/stale-after-sync.md"]
    assert not stale.exists()
    assert "wiki/sources/stale-after-sync.md" in captured["message"]


def test_export_notes_to_markdown_dry_run_reconcile_reports_without_deleting(tmp_path, monkeypatch):
    export_settings = settings(tmp_path)
    stale = export_settings.vault_path / "wiki" / "sources" / "stale.md"
    stale.parent.mkdir(parents=True)
    stale.write_text('---\nllm_wiki_note_id: "note_stale"\n---\n\n# Stale\n', encoding="utf-8")
    monkeypatch.setattr("llm_wiki.export_mirror._select_notes", lambda **_kwargs: [note(slug="current")])

    result = export_notes_to_markdown(
        export_settings,
        scope="full",
        dry_run=True,
        sync=False,
        push=False,
        reconcile=True,
    )

    assert result["status"] == "dry_run"
    assert result["stale_paths"] == ["wiki/sources/stale.md"]
    assert result["deleted_paths"] == ["wiki/sources/stale.md"]
    assert stale.exists()


def test_export_notes_to_markdown_writes_local_mirror_without_git(db_settings, monkeypatch):
    def fail_git_call(*_args, **_kwargs):
        raise AssertionError("Git should not be called for local-only export")

    monkeypatch.setattr("llm_wiki.export_mirror.sync_main", fail_git_call)
    monkeypatch.setattr("llm_wiki.export_mirror.commit_all", fail_git_call)
    monkeypatch.setattr("llm_wiki.export_mirror.push_branch", fail_git_call)
    monkeypatch.setattr("llm_wiki.export_mirror.run_git", fail_git_call)
    created = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "Local Export",
            "slug": "local-export",
            "body_markdown": "Local body",
            "change_source": "test",
        },
        db_settings,
    )

    result = export_notes_to_markdown(
        db_settings,
        scope="note-id",
        note_id=created["id"],
        dry_run=False,
        sync=False,
        push=False,
    )

    assert result["status"] == "succeeded"
    assert result["changed_paths"] == ["wiki/sources/local-export.md"]
    assert result["content_commit_sha"] is None
    assert result["pushed"] is False
    exported = db_settings.vault_path / "wiki" / "sources" / "local-export.md"
    assert "Local body" in exported.read_text(encoding="utf-8")
    latest_job = get_latest_export_job_for_note(created["id"], db_settings)
    assert latest_job["status"] == "succeeded"
    assert latest_job["content_commit_sha"] is None
