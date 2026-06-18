from __future__ import annotations

from pathlib import Path

from llm_wiki.diff_detector import changed_files
from llm_wiki.git_tools import run_git


def test_changed_files_handles_unicode_paths(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(["init", "-b", "main"], cwd=repo)
    run_git(["config", "user.name", "pytest"], cwd=repo)
    run_git(["config", "user.email", "pytest@example.invalid"], cwd=repo)
    (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
    run_git(["add", "-A"], cwd=repo)
    run_git(["commit", "-m", "initial"], cwd=repo)
    base = run_git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()
    note = repo / "inbox" / "manual" / "오늘 날씨.md"
    note.parent.mkdir(parents=True)
    note.write_text("더운 날씨\n", encoding="utf-8")
    run_git(["add", "-A"], cwd=repo)
    run_git(["commit", "-m", "capture"], cwd=repo)

    rows = changed_files(base, "HEAD", vault_path=repo)

    assert rows == [
        {
            "status": "A",
            "path": "inbox/manual/오늘 날씨.md",
            "old_path": None,
            "class": "inbox",
        }
    ]
