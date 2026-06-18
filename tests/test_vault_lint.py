from __future__ import annotations

from pathlib import Path

from llm_wiki.vault_lint import lint_vault


def test_vault_lint_accepts_minimal_valid_note(tmp_path: Path):
    note = tmp_path / "inbox" / "test.md"
    note.parent.mkdir()
    note.write_text(
        "\n".join(
            [
                "---",
                'title: "Test"',
                "type: capture",
                "status: draft",
                "created: 2026-06-02",
                "updated: 2026-06-02",
                "source_refs: []",
                "---",
                "",
                "# Test",
            ]
        ),
        encoding="utf-8",
    )

    result = lint_vault(tmp_path)

    assert result.ok
    assert result.errors == []


def test_vault_lint_rejects_missing_frontmatter():
    result = lint_vault(Path("tests/fixtures/bad-vault"))

    assert not result.ok
    assert "bad-note.md: missing frontmatter" in result.errors


def test_vault_lint_accepts_reviewable_topic_entity_suggestions(tmp_path: Path):
    source = tmp_path / "inbox" / "manual" / "capture.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                "---",
                'title: "Capture"',
                "type: capture",
                "status: draft",
                "created: 2026-06-03",
                "updated: 2026-06-03",
                "source_refs: []",
                "---",
                "",
                "# Capture",
            ]
        ),
        encoding="utf-8",
    )
    note = tmp_path / "wiki" / "sources" / "capture.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "\n".join(
            [
                "---",
                'title: "Capture Source"',
                "type: source",
                "status: draft",
                "created: 2026-06-03",
                "updated: 2026-06-03",
                "source_refs:",
                "  - inbox/manual/capture.md",
                "---",
                "",
                "# Capture Source",
                "",
                "## Related",
                "",
                "### Topic Suggestions",
                "",
                "| Candidate | Suggested path | Evidence | Review note |",
                "| --- | --- | --- | --- |",
                "| Knowledge Ops | `wiki/topics/knowledge-ops.md` | Capture mentions review cadence. | Review before creating topic page. |",
                "",
                "### Entity Suggestions",
                "",
                "| Candidate | Type | Suggested path | Evidence | Review note |",
                "| --- | --- | --- | --- | --- |",
                "| llm-wiki | project | `wiki/entities/llm-wiki.md` | Capture mentions the project. | Review before creating entity page. |",
            ]
        ),
        encoding="utf-8",
    )

    result = lint_vault(tmp_path)

    assert result.ok
    assert result.errors == []
