from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


BLOCKED_PATH_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p8",
    "*.p12",
    "*.dump",
    "*.bak",
    "*.backup",
    "*.sqlite",
    "*.sqlite3",
    "agent_private.md",
    ".codex-remote-attachments/*",
)

ALLOWED_PATH_PATTERNS = (
    ".env.example",
    "*.env.example",
)

CONTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("openai-api-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("telegram-bot-token", re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private-windows-home", re.compile(r"\b[A-Z]:\\Users\\(?!YOUR_USER\b)(?!example\b)[A-Za-z0-9._-]+", re.IGNORECASE)),
    (
        "private-linux-home",
        re.compile(r"(?<![A-Za-z0-9_/-])/home/(?!(?:YOUR_USER|example)(?:[/\s`'\")]|$))[A-Za-z0-9._-]+"),
    ),
    (
        "private-network-ip",
        re.compile(
            r"(?<![\d.])(?:10\.(?:\d{1,3}\.){2}\d{1,3}|"
            r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
            r"192\.168\.\d{1,3}\.\d{1,3})(?![\d.])"
        ),
    ),
)


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    line: int
    snippet: str


def tracked_files(root: Path) -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    return [root / item.decode("utf-8") for item in output.split(b"\0") if item]


def scan_paths(paths: Iterable[Path], *, root: Path | None = None, extra_terms: Iterable[str] = ()) -> list[Finding]:
    base = (root or Path.cwd()).resolve()
    findings: list[Finding] = []
    terms = [term.strip() for term in extra_terms if term and term.strip()]
    for path in paths:
        resolved = path.resolve()
        display = _display_path(resolved, base)
        findings.extend(_scan_path_name(display))
        if not resolved.is_file() or _looks_binary(resolved):
            continue
        text = resolved.read_text(encoding="utf-8", errors="replace")
        findings.extend(_scan_text(display, text, terms))
    return findings


def extra_terms_from_env() -> list[str]:
    raw = os.environ.get("LLM_WIKI_PUBLIC_SCAN_TERMS", "")
    return [item.strip() for item in re.split(r"[\n,]", raw) if item.strip()]


def _scan_path_name(path: str) -> list[Finding]:
    normalized = path.replace("\\", "/")
    if any(fnmatch.fnmatch(normalized, pattern) for pattern in ALLOWED_PATH_PATTERNS):
        return []
    findings = []
    for pattern in BLOCKED_PATH_PATTERNS:
        if fnmatch.fnmatch(normalized, pattern):
            findings.append(Finding(path=path, rule="blocked-path", line=0, snippet=pattern))
    return findings


def _scan_text(path: str, text: str, extra_terms: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in CONTENT_RULES:
            if pattern.search(line):
                findings.append(Finding(path=path, rule=name, line=line_number, snippet=_snippet(line)))
        for term in extra_terms:
            if term in line:
                findings.append(Finding(path=path, rule="custom-term", line=line_number, snippet=_snippet(line)))
    return findings


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _looks_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return True
    return b"\0" in chunk


def _snippet(line: str) -> str:
    compact = re.sub(r"\s+", " ", line).strip()
    return compact[:160]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan tracked files before publishing a public llm-wiki snapshot.")
    parser.add_argument("--root", default=".", help="Repository root. Defaults to the current directory.")
    parser.add_argument("--term", action="append", default=[], help="Additional exact string to reject.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    terms = [*extra_terms_from_env(), *args.term]
    findings = scan_paths(tracked_files(root), root=root, extra_terms=terms)
    if not findings:
        print("publication scan passed")
        return 0
    for finding in findings:
        location = f"{finding.path}:{finding.line}" if finding.line else finding.path
        print(f"{location}: {finding.rule}: {finding.snippet}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
