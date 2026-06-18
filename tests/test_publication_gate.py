from pathlib import Path
import subprocess

from scripts.publication_gate import gate_succeeded, run_gate


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_publication_gate_fails_on_secret_like_tracked_content(tmp_path: Path):
    note = tmp_path / "README.md"
    note.write_text("key: " + "sk-proj-" + ("A" * 40), encoding="utf-8")

    results = run_gate(
        tmp_path,
        allow_dirty=True,
        skip_compile=True,
        skip_pytest=True,
        secret_tools="skip",
        command_runner=lambda command, root: _completed(),
        tracked_file_provider=lambda root: [note],
    )

    assert not gate_succeeded(results)
    scan = next(result for result in results if result.name == "publication-scan")
    assert scan.status == "failed"
    assert "openai-api-key" in scan.output


def test_publication_gate_requires_clean_working_tree_by_default(tmp_path: Path):
    results = run_gate(
        tmp_path,
        skip_compile=True,
        skip_pytest=True,
        secret_tools="skip",
        command_runner=lambda command, root: _completed(" M README.md") if command[:2] == ["git", "status"] else _completed(),
        tracked_file_provider=lambda root: [],
    )

    status = next(result for result in results if result.name == "git-status")
    assert status.status == "failed"
    assert "working tree has changes" in status.detail


def test_publication_gate_can_allow_dirty_working_tree(tmp_path: Path):
    results = run_gate(
        tmp_path,
        allow_dirty=True,
        skip_compile=True,
        skip_pytest=True,
        secret_tools="skip",
        command_runner=lambda command, root: _completed(" M README.md") if command[:2] == ["git", "status"] else _completed(),
        tracked_file_provider=lambda root: [],
    )

    status = next(result for result in results if result.name == "git-status")
    assert status.status == "skipped"
    assert gate_succeeded(results)


def test_publication_gate_can_require_external_secret_tools(tmp_path: Path):
    results = run_gate(
        tmp_path,
        allow_dirty=True,
        skip_compile=True,
        skip_pytest=True,
        secret_tools="require",
        command_runner=lambda command, root: _completed(),
        tracked_file_provider=lambda root: [],
        which=lambda name: None,
    )

    assert not gate_succeeded(results)
    missing = {result.name: result.status for result in results if result.name in {"gitleaks", "trufflehog"}}
    assert missing == {"gitleaks": "failed", "trufflehog": "failed"}
