from __future__ import annotations

from pathlib import Path

from llm_wiki.notes_store import get_note_by_original_path, list_note_revisions
from llm_wiki.vault_import import build_import_report, import_vault_notes, parse_import_candidate


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_parse_import_candidate_maps_supported_paths_and_frontmatter(tmp_path):
    path = tmp_path / "archive" / "inbox" / "manual" / "2026" / "06" / "새로운 메모.md"
    write(
        path,
        """---
title: "새로운 메모"
status: archived
source_refs:
  - wiki/sources/source.md
---

Archived body
""",
    )

    candidate = parse_import_candidate(tmp_path, path)

    assert candidate.kind == "archive"
    assert candidate.status == "archived"
    assert candidate.title == "새로운 메모"
    assert candidate.slug == "새로운 메모"
    assert candidate.metadata["original_path"] == "archive/inbox/manual/2026/06/새로운 메모.md"
    assert candidate.metadata["content_sha256"]
    assert candidate.metadata["channel"] == "manual"
    assert candidate.metadata["archive_year"] == "2026"
    assert candidate.metadata["source_refs"] == ["wiki/sources/source.md"]
    assert candidate.body_markdown.strip() == "Archived body"


def test_build_import_report_counts_importable_ignored_and_invalid(tmp_path):
    write(tmp_path / "wiki" / "sources" / "source.md", "# Source\n\nBody")
    write(tmp_path / "inbox" / "manual" / "capture.md", "# Capture")
    write(tmp_path / "logs" / "daily.md", "# Daily")
    write(tmp_path / "docs" / "markdown-rules.md", "# Docs")
    write(tmp_path / "unknown" / "note.md", "# Unknown")
    write(tmp_path / "wiki" / "sources" / "index.md", "# Index")

    report = build_import_report(tmp_path)

    assert report["total_markdown_files"] == 6
    assert report["importable_count"] == 3
    assert report["ignored_count"] == 2
    assert report["invalid_count"] == 1
    assert report["counts_by_kind"] == {"inbox": 1, "log": 1, "source": 1}
    assert report["invalid_files"] == [{"path": "unknown/note.md", "reason": "unsupported import path"}]


def test_import_vault_notes_apply_creates_initial_revision_and_is_idempotent(db_settings, tmp_path):
    source_path = tmp_path / "wiki" / "sources" / "source.md"
    write(
        source_path,
        """---
title: "Imported Source"
status: active
---

# Imported Source

Body
""",
    )

    first = import_vault_notes(tmp_path, mode="apply", settings=db_settings)
    second = import_vault_notes(tmp_path, mode="apply", settings=db_settings)

    assert first["status"] == "succeeded"
    assert first["imported_count"] == 1
    assert first["new_count"] == 1
    assert second["status"] == "succeeded"
    assert second["imported_count"] == 0
    assert second["existing_count"] == 1
    note = get_note_by_original_path("wiki/sources/source.md", db_settings)
    assert note["kind"] == "source"
    assert note["metadata"]["original_path"] == "wiki/sources/source.md"
    assert note["metadata"]["content_sha256"]
    assert note["metadata"]["frontmatter"]["title"] == "Imported Source"
    revisions = list_note_revisions(note["id"], settings=db_settings)
    assert len(revisions) == 1
    assert revisions[0]["change_source"] == "import"
