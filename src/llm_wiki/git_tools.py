from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess

from .config import Settings, load_settings


def run_git(args: list[str], *, cwd: Path, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged_env,
    )


@contextmanager
def git_auth_env(_settings: Settings):
    yield {"GIT_TERMINAL_PROMPT": "0"}


@contextmanager
def git_operation_lock(settings: Settings):
    lock_root = settings.vault_path.parent
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / ".llm-wiki-git-ops.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        if os.name == "posix":
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "posix":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def ensure_clean(repo_path: Path) -> None:
    result = run_git(["status", "--short"], cwd=repo_path)
    if result.stdout.strip():
        raise RuntimeError(f"mirror working tree is not clean:\n{result.stdout}")


def sync_main(settings: Settings | None = None) -> str:
    resolved = settings or load_settings()
    ensure_clean(resolved.vault_path)
    with git_auth_env(resolved) as env:
        run_git(["fetch", "origin", "main"], cwd=resolved.vault_path, env=env)
        run_git(["checkout", "main"], cwd=resolved.vault_path, env=env)
        run_git(["pull", "--ff-only", "origin", "main"], cwd=resolved.vault_path, env=env)
    return run_git(["rev-parse", "HEAD"], cwd=resolved.vault_path).stdout.strip()


def commit_all(message: str, settings: Settings | None = None, *, repo_path: Path | None = None) -> str | None:
    resolved = settings or load_settings()
    path = repo_path or resolved.vault_path
    run_git(["add", "-A"], cwd=path)
    diff = run_git(["diff", "--cached", "--quiet"], cwd=path, check=False)
    if diff.returncode == 0:
        return None
    ensure_commit_identity(path)
    run_git(["commit", "-m", message], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path).stdout.strip()


def push_branch(branch: str, settings: Settings | None = None, *, repo_path: Path | None = None) -> None:
    resolved = settings or load_settings()
    path = repo_path or resolved.vault_path
    with git_auth_env(resolved) as env:
        run_git(["push", "-u", "origin", branch], cwd=path, env=env)


def restore_main(settings: Settings | None = None) -> None:
    resolved = settings or load_settings()
    run_git(["reset", "--hard"], cwd=resolved.vault_path, check=False)
    run_git(["clean", "-fd"], cwd=resolved.vault_path, check=False)
    run_git(["checkout", "main"], cwd=resolved.vault_path, check=False)


def ensure_commit_identity(repo_path: Path) -> None:
    name = run_git(["config", "user.name"], cwd=repo_path, check=False)
    if not name.stdout.strip():
        run_git(["config", "user.name", "llm-wiki worker"], cwd=repo_path)
    email = run_git(["config", "user.email"], cwd=repo_path, check=False)
    if not email.stdout.strip():
        run_git(["config", "user.email", "llm-wiki-worker@localhost"], cwd=repo_path)
