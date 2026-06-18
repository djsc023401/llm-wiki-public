from pathlib import Path

from scripts.publication_scan import scan_paths


def test_publication_scan_flags_secret_like_content(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("api key: " + "sk-proj-" + ("A" * 40), encoding="utf-8")

    findings = scan_paths([note], root=tmp_path)

    assert [(finding.rule, finding.line) for finding in findings] == [("openai-api-key", 1)]


def test_publication_scan_allows_env_example_placeholders(tmp_path: Path):
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY_FILE=/data/secrets/openai-api-key",
                "APP_ADMIN_TOKEN=change-me-admin-token",
                "APP_BASE_URL=https://notes.example.com",
            ]
        ),
        encoding="utf-8",
    )

    assert scan_paths([env_example], root=tmp_path) == []


def test_publication_scan_flags_blocked_paths(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ADMIN_TOKEN=local-only", encoding="utf-8")

    findings = scan_paths([env_file], root=tmp_path)

    assert [(finding.rule, finding.snippet) for finding in findings] == [("blocked-path", ".env")]


def test_publication_scan_flags_custom_terms(tmp_path: Path):
    doc = tmp_path / "README.md"
    doc.write_text("Deploy at real.example.internal", encoding="utf-8")

    findings = scan_paths([doc], root=tmp_path, extra_terms=["real.example.internal"])

    assert [(finding.rule, finding.line) for finding in findings] == [("custom-term", 1)]
