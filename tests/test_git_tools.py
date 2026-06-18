from __future__ import annotations

from pathlib import Path

from llm_wiki.config import Settings
from llm_wiki.git_tools import commit_all, git_operation_lock, run_git


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://unused",
        api_token=None,
        vault_path=tmp_path / "mirror",
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


def test_commit_all_commits_pending_mirror_changes(tmp_path: Path):
    settings = _settings(tmp_path)
    repo = settings.vault_path
    repo.mkdir()
    run_git(["init", "-b", "main"], cwd=repo)
    (repo / "wiki").mkdir()
    (repo / "wiki" / "source.md").write_text("# Source\n", encoding="utf-8")

    commit_sha = commit_all("export: test", settings, repo_path=repo)

    assert commit_sha
    assert run_git(["status", "--short"], cwd=repo).stdout.strip() == ""
    assert run_git(["log", "-1", "--pretty=%s"], cwd=repo).stdout.strip() == "export: test"


def test_commit_all_returns_none_without_changes(tmp_path: Path):
    settings = _settings(tmp_path)
    repo = settings.vault_path
    repo.mkdir()
    run_git(["init", "-b", "main"], cwd=repo)
    (repo / "README.md").write_text("# Mirror\n", encoding="utf-8")
    assert commit_all("initial", settings, repo_path=repo)

    assert commit_all("no changes", settings, repo_path=repo) is None


def test_git_operation_lock_uses_mirror_parent(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.vault_path.mkdir(parents=True)

    with git_operation_lock(settings):
        assert (settings.vault_path.parent / ".llm-wiki-git-ops.lock").exists()
