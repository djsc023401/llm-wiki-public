from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

try:
    from scripts.publication_scan import Finding, extra_terms_from_env, scan_paths, tracked_files
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.publication_scan import Finding, extra_terms_from_env, scan_paths, tracked_files


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str = ""
    output: str = ""


CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]
TrackedFileProvider = Callable[[Path], list[Path]]
Which = Callable[[str], str | None]


def run_gate(
    root: Path,
    *,
    terms: Iterable[str] = (),
    allow_dirty: bool = False,
    skip_compile: bool = False,
    skip_pytest: bool = False,
    secret_tools: str = "auto",
    command_runner: CommandRunner | None = None,
    tracked_file_provider: TrackedFileProvider = tracked_files,
    which: Which = shutil.which,
) -> list[CheckResult]:
    resolved_root = root.resolve()
    runner = command_runner or _run_command
    custom_terms = [*extra_terms_from_env(), *(term for term in terms if term)]

    results = [
        _check_git_status(resolved_root, allow_dirty=allow_dirty, command_runner=runner),
        _check_publication_scan(resolved_root, custom_terms, tracked_file_provider=tracked_file_provider),
    ]
    if skip_compile:
        results.append(CheckResult("compileall", "skipped", "--skip-compile"))
    else:
        results.append(_command_check("compileall", [sys.executable, "-m", "compileall", "-q", "-f", "src", "tests", "scripts"], resolved_root, runner))
    if skip_pytest:
        results.append(CheckResult("pytest", "skipped", "--skip-pytest"))
    else:
        results.append(_command_check("pytest", [sys.executable, "-m", "pytest"], resolved_root, runner))
    results.extend(_secret_tool_checks(resolved_root, secret_tools=secret_tools, command_runner=runner, which=which))
    return results


def gate_succeeded(results: Iterable[CheckResult]) -> bool:
    return all(result.status != "failed" for result in results)


def _check_git_status(root: Path, *, allow_dirty: bool, command_runner: CommandRunner) -> CheckResult:
    result = _command_check("git-status", ["git", "status", "--short"], root, command_runner)
    if result.status == "failed":
        return result
    if not result.output.strip():
        return CheckResult("git-status", "passed", "working tree clean")
    if allow_dirty:
        return CheckResult("git-status", "skipped", "dirty working tree allowed", result.output)
    return CheckResult("git-status", "failed", "working tree has changes", result.output)


def _check_publication_scan(
    root: Path,
    terms: Iterable[str],
    *,
    tracked_file_provider: TrackedFileProvider,
) -> CheckResult:
    findings = scan_paths(tracked_file_provider(root), root=root, extra_terms=terms)
    if not findings:
        return CheckResult("publication-scan", "passed", "tracked files passed")
    return CheckResult("publication-scan", "failed", f"{len(findings)} finding(s)", _format_findings(findings))


def _secret_tool_checks(
    root: Path,
    *,
    secret_tools: str,
    command_runner: CommandRunner,
    which: Which,
) -> list[CheckResult]:
    if secret_tools == "skip":
        return [
            CheckResult("gitleaks", "skipped", "--secret-tools=skip"),
            CheckResult("trufflehog", "skipped", "--secret-tools=skip"),
        ]
    checks: list[CheckResult] = []
    tools = [
        ("gitleaks", ["gitleaks", "detect", "--source", ".", "--no-git"]),
        ("trufflehog", ["trufflehog", "git", "file://.", "--only-verified"]),
    ]
    for name, command in tools:
        if which(name) is None:
            status = "failed" if secret_tools == "require" else "skipped"
            checks.append(CheckResult(name, status, f"{name} is not installed"))
            continue
        checks.append(_command_check(name, command, root, command_runner))
    return checks


def _command_check(name: str, command: Sequence[str], root: Path, command_runner: CommandRunner) -> CheckResult:
    try:
        completed = command_runner(command, root)
    except FileNotFoundError as exc:
        return CheckResult(name, "failed", str(exc))
    output = _combined_output(completed)
    if completed.returncode == 0:
        return CheckResult(name, "passed", "ok", output)
    return CheckResult(name, "failed", f"exit {completed.returncode}", output)


def _run_command(command: Sequence[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)


def _combined_output(completed: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part.strip() for part in (completed.stdout or "", completed.stderr or "") if part.strip())


def _format_findings(findings: Iterable[Finding]) -> str:
    lines = []
    for finding in findings:
        location = f"{finding.path}:{finding.line}" if finding.line else finding.path
        lines.append(f"{location}: {finding.rule}: {finding.snippet}")
    return "\n".join(lines)


def _print_results(results: Iterable[CheckResult]) -> None:
    for result in results:
        print(f"[{result.status}] {result.name}: {result.detail}")
        if result.output:
            print(result.output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the public snapshot verification gate.")
    parser.add_argument("--root", default=".", help="Repository root. Defaults to the current directory.")
    parser.add_argument("--term", action="append", default=[], help="Additional exact string to reject.")
    parser.add_argument("--allow-dirty", action="store_true", help="Do not fail when the working tree has changes.")
    parser.add_argument("--skip-compile", action="store_true", help="Skip compileall.")
    parser.add_argument("--skip-pytest", action="store_true", help="Skip pytest.")
    parser.add_argument(
        "--secret-tools",
        choices=("auto", "require", "skip"),
        default=os.environ.get("LLM_WIKI_PUBLIC_SECRET_TOOLS", "auto"),
        help="Run gitleaks/trufflehog when available, require them, or skip them.",
    )
    args = parser.parse_args(argv)

    results = run_gate(
        Path(args.root),
        terms=args.term,
        allow_dirty=args.allow_dirty,
        skip_compile=args.skip_compile,
        skip_pytest=args.skip_pytest,
        secret_tools=args.secret_tools,
    )
    _print_results(results)
    return 0 if gate_succeeded(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
