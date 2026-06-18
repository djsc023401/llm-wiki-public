from __future__ import annotations

from pathlib import Path

from .config import Settings, load_settings
from .git_tools import run_git


def classify(path: str) -> str:
    if path.startswith("inbox/"):
        return "inbox"
    if path.startswith("raw/"):
        return "raw"
    if path.startswith("wiki/"):
        return "wiki"
    if path.startswith("assets/"):
        return "assets"
    return "other"


def changed_files(base: str, head: str = "HEAD", *, vault_path: Path | None = None) -> list[dict]:
    root = vault_path or load_settings().vault_path
    result = run_git(["-c", "core.quotePath=false", "diff", "--name-status", base, head], cwd=root)
    rows: list[dict] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            old_path, new_path = parts[1], parts[2]
            rows.append({"status": status, "path": new_path, "old_path": old_path, "class": classify(new_path)})
        elif len(parts) >= 2:
            path = parts[1]
            rows.append({"status": status, "path": path, "old_path": None, "class": classify(path)})
    return rows


def detect_since_state(settings: Settings | None = None) -> list[dict]:
    resolved = settings or load_settings()
    state_file = Path("/data/last_processed_commit")
    if not state_file.exists():
        base = run_git(["rev-list", "--max-parents=0", "HEAD"], cwd=resolved.vault_path).stdout.strip()
    else:
        base = state_file.read_text(encoding="utf-8").strip()
    head = run_git(["rev-parse", "HEAD"], cwd=resolved.vault_path).stdout.strip()
    return changed_files(base, head, vault_path=resolved.vault_path)
