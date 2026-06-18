from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


VALID_TYPES = {"capture", "source", "topic", "entity", "note", "decision", "review", "log"}
VALID_STATUS = {"draft", "active", "stale", "archived"}
VALID_PROCESSING = {"queued", "running", "needs_sync", "succeeded", "failed", "cancelled"}
REQUIRED = {"title", "type", "status", "created", "updated", "source_refs"}


@dataclass
class LintResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _parse_frontmatter(path: Path) -> tuple[dict, list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, ["missing frontmatter"]
    data: dict[str, object] = {}
    current_list: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return data, []
        if current_list and re.match(r"\s+-\s+", line):
            data.setdefault(current_list, []).append(re.sub(r"^\s+-\s+", "", line).strip().strip('"'))
            continue
        current_list = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "[]":
            data[key] = []
        elif value == "":
            data[key] = []
            current_list = key
        else:
            data[key] = value.strip('"').strip("'")
    return data, ["unterminated frontmatter"]


def _iter_markdown(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.md")
        if ".git" not in p.parts and p.name not in {"README.md", "AGENTS.md"}
    )


def lint_vault(root: Path) -> LintResult:
    errors: list[str] = []
    warnings: list[str] = []
    for path in _iter_markdown(root):
        rel = path.relative_to(root).as_posix()
        data, parse_errors = _parse_frontmatter(path)
        for error in parse_errors:
            errors.append(f"{rel}: {error}")
        if parse_errors:
            continue
        missing = REQUIRED - set(data)
        if missing:
            errors.append(f"{rel}: missing required frontmatter: {', '.join(sorted(missing))}")
        doc_type = data.get("type")
        if doc_type and doc_type not in VALID_TYPES:
            errors.append(f"{rel}: invalid type {doc_type}")
        status = data.get("status")
        if status and status not in VALID_STATUS:
            errors.append(f"{rel}: invalid status {status}")
        processing = data.get("processing_status")
        if processing and processing not in VALID_PROCESSING:
            errors.append(f"{rel}: invalid processing_status {processing}")
        for ref in data.get("source_refs", []) or []:
            if not ref:
                continue
            target = root / str(ref)
            if not target.exists():
                errors.append(f"{rel}: missing source_ref target {ref}")
        text = path.read_text(encoding="utf-8")
        if re.search(r"\[\[[^\]]*\.md", text):
            warnings.append(f"{rel}: wiki link includes .md extension")
        if "../" in text or "..\\" in text:
            warnings.append(f"{rel}: contains parent-directory link")
    for path in root.rglob("*"):
        if path.is_file() and ".git" not in path.parts and path.stat().st_size > 1024 * 1024:
            warnings.append(f"{path.relative_to(root).as_posix()}: file larger than 1MiB")
    if (root / "sources").exists():
        errors.append("top-level sources/ should not exist; use raw/sources/ or wiki/sources/")
    return LintResult(errors=errors, warnings=warnings)
