from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from llm_wiki.ai_runner import (
    CodexCliRunner,
    DryRunRunner,
    OpenAIApiRunner,
    _codex_env,
    build_codex_prompt,
    find_existing_source_note,
    get_runner,
)
from llm_wiki.vault_lint import lint_vault


def test_dry_run_updates_existing_source_note_for_same_source_ref(tmp_path: Path):
    source = tmp_path / "inbox" / "mobile" / "capture.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                "---",
                'title: "Capture Title"',
                "type: capture",
                "status: draft",
                "created: 2026-06-02",
                "updated: 2026-06-02",
                "source_refs: []",
                "---",
                "",
                "# Capture Title",
                "",
                "Important detail.",
            ]
        ),
        encoding="utf-8",
    )
    existing = tmp_path / "wiki" / "sources" / "existing-note.md"
    existing.parent.mkdir(parents=True)
    existing.write_text(
        "\n".join(
            [
                "---",
                'title: "Existing Note"',
                "type: source",
                "status: draft",
                "created: 2026-06-02",
                "updated: 2026-06-02",
                "source_refs:",
                "  - inbox/mobile/capture.md",
                "---",
                "",
                "# Existing Note",
                "",
                "Original human-authored content.",
            ]
        ),
        encoding="utf-8",
    )

    result = DryRunRunner().run(_request("inbox/mobile/capture.md"), tmp_path)

    updated = existing.read_text(encoding="utf-8")
    assert result.summary == "Updated existing wiki/sources/existing-note.md"
    assert result.changed_paths == ["wiki/sources/existing-note.md"]
    assert "Original human-authored content." in updated
    assert "## 처리 업데이트" in updated
    assert not (tmp_path / "wiki" / "sources" / "capture-title.md").exists()


def test_codex_prompt_points_to_existing_source_note(tmp_path: Path):
    source = tmp_path / "inbox" / "manual" / "capture.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Capture\n", encoding="utf-8")
    existing = tmp_path / "wiki" / "sources" / "capture-source.md"
    existing.parent.mkdir(parents=True)
    existing.write_text(
        "\n".join(
            [
                "---",
                'title: "Capture Source"',
                "type: source",
                "status: draft",
                "created: 2026-06-02",
                "updated: 2026-06-02",
                "source_refs:",
                "  - inbox/manual/capture.md",
                "---",
                "",
                "# Capture Source",
            ]
        ),
        encoding="utf-8",
    )

    prompt, source_context = build_codex_prompt(_request("inbox/manual/capture.md"), tmp_path)

    assert find_existing_source_note(tmp_path, "inbox/manual/capture.md") == "wiki/sources/capture-source.md"
    assert source_context.existing_path == "wiki/sources/capture-source.md"
    assert "Existing source note path: `wiki/sources/capture-source.md`" in prompt
    assert "do not create a duplicate source note" in prompt
    assert "Write the generated source note in Korean" in prompt
    assert "Start the generated source note with a concise Korean H1 heading" in prompt
    assert "Use Korean stable sections in this order: `읽기용 정리`, `요약`, `추출된 사실`, `소스 메타데이터`, and `관련`." in prompt
    assert "rewrite the source as a short natural Korean note for a human reader" in prompt
    assert "add `읽기용 정리` if it is missing" in prompt
    assert "Write candidate names, evidence, and review notes in Korean." in prompt
    assert "Treat `Personalization context` and any `## 개인화 참고` block as non-evidence configuration" in prompt
    assert "never cite them as source facts, extracted facts, evidence cells, or time candidate evidence" in prompt
    assert "Write the generated source note in English" not in prompt
    assert "### 주제 제안" in prompt
    assert "### 대상 제안" in prompt
    assert "### 태그 제안" in prompt
    assert "### 분류 변경 제안" in prompt
    assert "### 일정 제안" in prompt
    assert "Suggested topic paths must be proposed as text like `wiki/topics/<slug>.md`; do not create those files." in prompt
    assert "Suggested entity paths must be proposed as text like `wiki/entities/<slug>.md`; do not create those files." in prompt
    assert "Tag candidates are lightweight labels for filtering and context" in prompt
    assert "Do not directly rewrite approved links as final truth" in prompt
    assert "`동작` must be one of `추가`, `제거`, or `교체`" in prompt
    assert "future commitments, deadlines, reservations, follow-up checks, or actionable tasks" in prompt
    assert "Markdown table columns: `후보`, `의도`, `유형`, `시작`, `종료`, `마감`, `알림`, `시간대`, `근거`, `검토 메모`" in prompt
    assert "`의도` must be one of `기록 전용`, `일정`, `할 일`, `마감`, `후속 확인`, or `알림`." in prompt
    assert "Classify every time candidate by `의도`" in prompt
    assert "suggest `후속 확인` only when the source evidence says a later check/review/action is needed" in prompt
    assert "do not invent generic follow-up dates" in prompt
    assert "use `기록 전용` for facts that only record a past or completed state" in prompt
    assert "Completion records such as reservation, purchase, payment, application, submission, visit, checkup, or delivery completion are `기록 전용`" in prompt
    assert "Do not put a completion timestamp into `시작`, `마감`, or `알림` for an actionable row" in prompt
    assert "`예약 완료`, `구매 완료`, `결제 완료`, or `검진 완료` alone are `기록 전용`" in prompt
    assert "`진료일`, `방문 예정일`, `여행 출발일`, or `숙소 체크인` are `일정`" in prompt
    assert "If the source says no reminder, no schedule, no follow-up, or no actionable item is needed" in prompt
    assert "Use ISO datetime strings with timezone offsets" in prompt
    assert "prefer concise Korean slugs in new suggested paths" in prompt
    assert "사용자 제공 메타데이터" in prompt
    assert "manual topics and manual tags as explicit user intent" in prompt
    assert "Do not create or edit `wiki/topics/` or `wiki/entities/` pages" in prompt


def test_codex_prompt_includes_personalization_context_without_secret_metadata(tmp_path: Path):
    source = tmp_path / "inbox" / "web" / "personalized.md"
    source.parent.mkdir(parents=True)
    source.write_text("오늘 치약을 구매 완료했다.\n", encoding="utf-8")
    request = _request("inbox/web/personalized.md")
    request["created_at"] = datetime(2026, 6, 5, 1, 0, tzinfo=timezone.utc)
    request["personalization_context"] = {
        "workflow_mode": "personal",
        "timezone": "UTC",
        "default_schedule_days": 45,
        "daily_digest_time": "07:30",
        "default_reminder_minutes": 30,
        "default_notification_channels": ["telegram"],
        "personal_terms": ["예약 완료", "구매 완료"],
        "classification_seeds": ["개인 일정", "생활용품"],
        "record_only_terms": ["예약 완료"],
        "follow_up_terms": ["확인 필요"],
        "frequent_people": ["A"],
        "frequent_places": ["강릉"],
        "active_projects": ["llm-wiki"],
        "life_categories": ["건강", "여행"],
        "metadata": {"api_key": "sk-test-secret", "admin_token": "admin-secret"},
    }

    prompt, _source_context = build_codex_prompt(request, tmp_path)

    assert "Personalization context:" in prompt
    assert "- Workflow mode: `personal` (Personal operating workspace)" in prompt
    assert "- Default timezone: `UTC`" in prompt
    assert "- Reference date (UTC): `2026-06-05`" in prompt
    assert "- Default schedule horizon: `45 days`" in prompt
    assert "- Daily digest time: `07:30`" in prompt
    assert "- Default reminder lead time: `30 minutes`" in prompt
    assert "- Preferred notification channels: `telegram`" in prompt
    assert "- Personal terms: `예약 완료`, `구매 완료`" in prompt
    assert "- Classification seeds: `개인 일정`, `생활용품`" in prompt
    assert "- Record-only terms: `예약 완료`" in prompt
    assert "- Follow-up terms: `확인 필요`" in prompt
    assert "- Frequent people: `A`" in prompt
    assert "- Frequent places: `강릉`" in prompt
    assert "- Active projects: `llm-wiki`" in prompt
    assert "- Life categories: `건강`, `여행`" in prompt
    assert "source evidence" in prompt
    assert "Never infer ownership, possession, investment holdings, relationships, visits, appointments, or completed actions" in prompt
    assert "record-only terms as phrases" in prompt
    assert "follow-up terms as phrases" in prompt
    assert "must not create time candidates by themselves" in prompt
    assert "personal operating flow" in prompt
    assert "do not force unrelated tags, topics, or entities" in prompt
    assert "keep the suggestion reviewable and cite the matching source evidence" in prompt
    assert "never create schedules, reminders, tasks, topics, or entities without source evidence" in prompt
    assert "sk-test-secret" not in prompt
    assert "admin-secret" not in prompt


def test_codex_prompt_preserves_manual_classification_guidance(tmp_path: Path):
    source = tmp_path / "inbox" / "web" / "classified.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                'title: "제목 없는 웹 메모"',
                "",
                "스타벅스에 3만원을 충전했다.",
                "",
                "## User Provided Metadata",
                "",
                "- Manual topics: 개인 지출; 선불 충전",
                "- Manual tags: 소비; 카페",
            ]
        ),
        encoding="utf-8",
    )

    prompt, _source_context = build_codex_prompt(_request("inbox/web/classified.md"), tmp_path)

    assert "manual topics and manual tags as explicit user intent" in prompt
    assert "Preserve manual tags in the generated source note" in prompt
    assert "Include each manual topic in `관련 > 주제 제안`" in prompt
    assert "infer reviewable topic, entity, and tag suggestions" in prompt


def test_codex_prompt_temporally_grounds_relative_dates(tmp_path: Path):
    source = tmp_path / "inbox" / "web" / "today-note.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                'title: "제목 없는 노트"',
                "",
                "오늘 스타벅스에 3만원을 충전했다.",
            ]
        ),
        encoding="utf-8",
    )
    request = _request("inbox/web/today-note.md")
    request["created_at"] = datetime(2026, 6, 5, 4, 30, tzinfo=timezone.utc)

    prompt, _source_context = build_codex_prompt(request, tmp_path)

    assert "Temporal context:" in prompt
    assert "Reference date (Asia/Seoul): `2026-06-05`" in prompt
    assert "상대 날짜 표현" in prompt or "relative date expressions" in prompt
    assert "`오늘`, `어제`, `내일`" in prompt
    assert "include the resolved absolute date" in prompt
    assert "Preserve the original relative wording only inside direct quotations or evidence cells" in prompt


def test_codex_prompt_handles_chained_relative_dates(tmp_path: Path):
    source = tmp_path / "inbox" / "web" / "stock-pattern.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                'title: "A 종목 관찰"',
                "",
                "A 종목은 어제 주가가 30% 하락하였고, 다음날 20% 상승함.",
                "급락 후 급등 패턴으로 보임.",
            ]
        ),
        encoding="utf-8",
    )
    request = _request("inbox/web/stock-pattern.md")
    request["source_revision_created_at"] = datetime(2026, 6, 4, 15, 0, tzinfo=timezone.utc)

    prompt, _source_context = build_codex_prompt(request, tmp_path)

    assert "chained relative expressions" in prompt
    assert "`어제 ... 다음날 ...`" in prompt
    assert "`다음날`, `익일`, `그 다음날`" in prompt
    assert "`하루 뒤`, `하루 전`, `그날`" in prompt
    assert "nearest prior explicit or already-resolved event date" in prompt
    assert "include both the original expression and the resolved absolute date" in prompt
    assert "`어제 30% 하락했고, 다음날 20% 상승`" in prompt
    assert "`2026-06-04 30% 하락`" in prompt
    assert "`2026-06-05 20% 상승`" in prompt
    assert "local anchor is unclear" in prompt


def test_codex_prompt_uses_source_revision_date_before_request_date(tmp_path: Path):
    source = tmp_path / "inbox" / "web" / "today-note.md"
    source.parent.mkdir(parents=True)
    source.write_text("오늘 운동을 완료했다.\n", encoding="utf-8")
    request = _request("inbox/web/today-note.md")
    request["created_at"] = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    request["source_revision_created_at"] = datetime(2026, 6, 4, 16, 30, tzinfo=timezone.utc)

    prompt, _source_context = build_codex_prompt(request, tmp_path)

    assert "Reference date (Asia/Seoul): `2026-06-05`" in prompt
    assert "Reference date (Asia/Seoul): `2026-06-01`" not in prompt


@pytest.mark.parametrize("generic_title", ["제목 없는 노트", "제목 없는 웹 메모"])
def test_codex_prompt_infers_title_when_web_note_title_is_generic_korean(tmp_path: Path, generic_title: str):
    source = tmp_path / "inbox" / "web" / "untitled-web-note.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                f'title: "{generic_title}"',
                "",
                "QQQI의 연 배당률은 약 14%다.",
            ]
        ),
        encoding="utf-8",
    )

    prompt, source_context = build_codex_prompt(_request("inbox/web/untitled-web-note.md"), tmp_path)

    assert source_context.title == "QQQI의 연 배당률은 약 14%다."
    assert generic_title not in source_context.candidate_path
    assert "infer a concise Korean source-note title from the body" in prompt
    assert "Do not reuse placeholder titles" in prompt


def test_codex_env_excludes_service_secrets(monkeypatch):
    monkeypatch.setenv("CODEX_HOME", "/data/codex")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("APP_PLUGIN_TOKEN", "plugin-secret")
    monkeypatch.setenv("APP_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("CUSTOM_SERVICE_TOKEN", "service-secret")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "s3-secret")

    env = _codex_env()

    assert env["CODEX_HOME"] == "/data/codex"
    assert env["PATH"] == "/usr/bin"
    assert "APP_DATABASE_URL" not in env
    assert "APP_PLUGIN_TOKEN" not in env
    assert "APP_ADMIN_TOKEN" not in env
    assert "CUSTOM_SERVICE_TOKEN" not in env
    assert "S3_SECRET_ACCESS_KEY" not in env


def test_codex_cli_runner_writes_private_run_context_and_uses_allowlisted_env(tmp_path: Path, monkeypatch):
    source = tmp_path / "inbox" / "manual" / "capture.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Capture\n\nImportant detail.\n", encoding="utf-8")
    run_root = tmp_path / "runs"
    monkeypatch.setenv("CODEX_RUN_ROOT", str(run_root))
    monkeypatch.setenv("CODEX_CLI_EXEC_ARGS", "--dangerously-bypass-approvals-and-sandbox --model gpt-test")
    monkeypatch.setenv("CODEX_HOME", "/data/codex")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://secret")
    calls = []

    class Completed:
        returncode = 0
        stdout = "codex ok"
        stderr = ""

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr("llm_wiki.ai_runner.subprocess.run", fake_run)

    result = CodexCliRunner(command=["codex"]).run(_request("inbox/manual/capture.md"), tmp_path)

    assert result.summary == "Codex CLI completed"
    assert result.changed_paths == []
    assert len(calls) == 1
    args, kwargs = calls[0]
    command = args[0]
    assert command[:4] == ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--model"]
    assert command[4] == "gpt-test"
    assert "Target source note path: `wiki/sources/capture.md`" in command[-1]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["stdin"] is not None
    assert kwargs["timeout"] == 1800
    assert kwargs["env"]["CODEX_HOME"] == "/data/codex"
    assert "APP_DATABASE_URL" not in kwargs["env"]

    run_dir = run_root / "req_test"
    assert (run_dir / "prompt.md").read_text(encoding="utf-8") == command[-1]
    context = (run_dir / "context.json").read_text(encoding="utf-8")
    assert '"request_id": "req_test"' in context
    assert '"target_path": "wiki/sources/capture.md"' in context
    assert (run_dir / "stdout.txt").read_text(encoding="utf-8") == "codex ok"
    assert (run_dir / "stderr.txt").read_text(encoding="utf-8") == ""


def test_openai_api_runner_is_selectable_but_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OPENAI_API_RUNNER_ENABLED", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY_FILE", raising=False)
    monkeypatch.delenv("OPENAI_API_MODEL", raising=False)

    runner = get_runner("openai-api")

    assert isinstance(runner, OpenAIApiRunner)
    with pytest.raises(RuntimeError, match="openai-api runner is disabled"):
        runner.preflight(Path("."))


def test_openai_api_runner_applies_json_file_plan_and_writes_redacted_metadata(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_RUNNER_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_API_TIMEOUT_SECONDS", "123")
    monkeypatch.setenv("OPENAI_API_MAX_OUTPUT_TOKENS", "456")
    monkeypatch.setenv("OPENAI_API_REASONING_EFFORT", "medium")
    source = tmp_path / "inbox" / "manual" / "capture.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                "---",
                'title: "API 캡처"',
                "type: capture",
                "status: draft",
                "created: 2026-06-03",
                "updated: 2026-06-03",
                "source_refs: []",
                "---",
                "",
                "# API 캡처",
                "",
                "Sensitive source detail.",
            ]
        ),
        encoding="utf-8",
    )
    created_content = "\n".join(
        [
            "---",
            'title: "API 캡처"',
            "type: source",
            "status: draft",
            "created: 2026-06-03",
            "updated: 2026-06-03",
            "source_refs:",
            "  - inbox/manual/capture.md",
            "---",
            "",
            "# API 캡처",
            "",
            "## 요약",
            "",
            "API가 생성한 요약입니다.",
        ]
    )
    fake_client = FakeOpenAIClient(
        FakeOpenAIResponse(
            output_text=_json(
                {
                    "summary": "API 소스 노트를 생성했습니다.",
                    "files": [
                        {
                            "path": "wiki/sources/api-캡처.md",
                            "content": created_content,
                        }
                    ],
                }
            )
        )
    )

    runner = OpenAIApiRunner(client_factory=_fake_client_factory(fake_client), run_root=tmp_path / "runs")

    runner.preflight(tmp_path)
    request = _request("inbox/manual/capture.md")
    request["personalization_context"] = {
        "timezone": "Asia/Seoul",
        "default_schedule_days": 45,
        "daily_digest_time": "07:30",
        "default_reminder_minutes": 30,
        "default_notification_channels": ["telegram"],
        "personal_terms": ["예약 완료"],
        "classification_seeds": ["개인 일정"],
        "record_only_terms": ["예약 완료"],
        "follow_up_terms": ["확인 필요"],
        "metadata": {"admin_token": "admin-secret", "telegram_token": "telegram-secret"},
    }

    result = runner.run(request, tmp_path)

    assert result.summary == "API 소스 노트를 생성했습니다."
    assert result.changed_paths == ["wiki/sources/api-캡처.md"]
    assert (tmp_path / "wiki" / "sources" / "api-캡처.md").read_text(encoding="utf-8") == created_content
    assert fake_client.factory_kwargs == {"api_key": "test-key", "timeout_seconds": 123}
    call = fake_client.responses.calls[0]
    assert call["model"] == "gpt-test"
    assert call["reasoning"] == {"effort": "medium"}
    assert call["max_output_tokens"] == 456
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["strict"] is True
    assert call["text"]["format"]["schema"]["properties"]["files"]["maxItems"] == 1
    file_schema = call["text"]["format"]["schema"]["properties"]["files"]["items"]["properties"]
    assert file_schema["path"]["enum"] == ["wiki/sources/api-캡처.md"]
    assert call["metadata"] == {"llm_wiki_request_id": "req_test", "llm_wiki_runner": "openai-api"}
    api_input = call["input"][0]["content"]
    assert "Sensitive source detail." in api_input
    assert "Write the generated source note in Korean" in api_input
    assert "예약 완료" in api_input
    assert "30 minutes" in api_input
    assert "개인 일정" in api_input
    assert "확인 필요" in api_input
    assert "preserve human-authored sections" in api_input
    assert "Treat `Personalization context` and any `## 개인화 참고` block as non-evidence configuration" in api_input
    assert "Never infer ownership, possession, investment holdings, relationships, visits, appointments, or completed actions" in api_input
    assert "Use default reminder lead time and preferred channels only after the source supports a real actionable time candidate" in api_input
    assert "never create schedules, reminders, tasks, topics, or entities without source evidence" in api_input

    run_dir = tmp_path / "runs" / "req_test"
    context = (run_dir / "context.json").read_text(encoding="utf-8")
    metadata = (run_dir / "response_metadata.json").read_text(encoding="utf-8")
    applied = (run_dir / "applied_files.json").read_text(encoding="utf-8")
    prompt_file = (run_dir / "prompt.md").read_text(encoding="utf-8")
    assert "Sensitive source detail." not in context
    assert "test-key" not in prompt_file + api_input + context + metadata + applied
    assert "admin-secret" not in prompt_file + api_input + context + metadata + applied
    assert "telegram-secret" not in prompt_file + api_input + context + metadata + applied
    assert '"output_count": 0' in metadata
    assert '"path": "wiki/sources/api-캡처.md"' in applied


def test_openai_api_runner_rejects_disallowed_file_plan(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_RUNNER_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_MODEL", "gpt-test")
    source = tmp_path / "inbox" / "manual" / "capture.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Capture\n", encoding="utf-8")
    fake_client = FakeOpenAIClient(
        FakeOpenAIResponse(
            output_text=_json(
                {
                    "summary": "Unsafe",
                    "files": [
                        {
                            "path": "wiki/topics/api-capture.md",
                            "content": "# Unsafe",
                        }
                    ],
                }
            )
        )
    )

    runner = OpenAIApiRunner(client_factory=_fake_client_factory(fake_client), run_root=tmp_path / "runs")

    with pytest.raises(RuntimeError, match="does not match expected target"):
        runner.run(_request("inbox/manual/capture.md"), tmp_path)


def test_openai_api_runner_preserves_existing_note_when_response_does(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_RUNNER_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_MODEL", "gpt-test")
    source = tmp_path / "inbox" / "manual" / "capture.md"
    source.parent.mkdir(parents=True)
    source.write_text("# 캡처\n\n새로운 사실.\n", encoding="utf-8")
    existing = tmp_path / "wiki" / "sources" / "existing-source.md"
    existing.parent.mkdir(parents=True)
    existing.write_text(
        "\n".join(
            [
                "---",
                'title: "Existing Source"',
                "type: source",
                "status: draft",
                "created: 2026-06-03",
                "updated: 2026-06-03",
                "source_refs:",
                "  - inbox/manual/capture.md",
                "---",
                "",
                "# Existing Source",
                "",
                "SENTINEL HUMAN SECTION",
            ]
        ),
        encoding="utf-8",
    )
    updated = existing.read_text(encoding="utf-8") + "\n\n## 처리 업데이트\n\n- 새로운 사실.\n"
    fake_client = FakeOpenAIClient(
        FakeOpenAIResponse(
            output_text=_json(
                {
                    "summary": "기존 소스 노트를 업데이트했습니다.",
                    "files": [{"path": "wiki/sources/existing-source.md", "content": updated}],
                }
            )
        )
    )

    runner = OpenAIApiRunner(client_factory=_fake_client_factory(fake_client), run_root=tmp_path / "runs")
    result = runner.run(_request("inbox/manual/capture.md"), tmp_path)

    assert result.changed_paths == ["wiki/sources/existing-source.md"]
    assert "SENTINEL HUMAN SECTION" in existing.read_text(encoding="utf-8")
    assert "Existing target source note content:" in fake_client.responses.calls[0]["input"][0]["content"]


def test_openai_api_runner_reports_incomplete_response(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_RUNNER_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_MODEL", "gpt-test")
    source = tmp_path / "inbox" / "manual" / "capture.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Capture\n", encoding="utf-8")
    fake_client = FakeOpenAIClient(
        FakeOpenAIResponse(
            status="incomplete",
            incomplete_details=SimpleObject(reason="max_output_tokens"),
            output_text="",
        )
    )

    runner = OpenAIApiRunner(client_factory=_fake_client_factory(fake_client), run_root=tmp_path / "runs")

    with pytest.raises(RuntimeError, match="openai-api response incomplete: max_output_tokens"):
        runner.run(_request("inbox/manual/capture.md"), tmp_path)
    assert (tmp_path / "runs" / "req_test" / "response_metadata.json").exists()


def test_dry_run_created_source_note_passes_vault_lint(tmp_path: Path):
    source = tmp_path / "inbox" / "manual" / "capture.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                "---",
                'title: "New Capture"',
                "type: capture",
                "status: draft",
                "created: 2026-06-02",
                "updated: 2026-06-02",
                "source_refs: []",
                "---",
                "",
                "# New Capture",
            ]
        ),
        encoding="utf-8",
    )

    result = DryRunRunner().run(_request("inbox/manual/capture.md"), tmp_path)
    lint = lint_vault(tmp_path)
    note = (tmp_path / "wiki" / "sources" / "new-capture.md").read_text(encoding="utf-8")

    assert result.changed_paths == ["wiki/sources/new-capture.md"]
    assert note.index("## 읽기용 정리") < note.index("## 요약") < note.index("## 추출된 사실")
    assert "사람이 다시 읽기 쉽게 정리한 것입니다" in note
    assert "## 요약" in note
    assert "## 추출된 사실" in note
    assert "## 소스 메타데이터" in note
    assert "### 주제 제안" in note
    assert "| 후보 | 제안 경로 | 근거 | 검토 메모 |" in note
    assert "### 대상 제안" in note
    assert "| 후보 | 유형 | 제안 경로 | 근거 | 검토 메모 |" in note
    assert "### 일정 제안" in note
    assert "| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |" in note
    assert lint.ok
    assert lint.errors == []


def _request(file_path: str) -> dict:
    return {
        "id": "req_test",
        "operation": "ingest",
        "file_path": file_path,
        "branch": "main",
    }


def _json(value: dict) -> str:
    import json

    return json.dumps(value)


class SimpleObject:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeOpenAIResponse(SimpleObject):
    def __init__(self, *, output_text: str, status: str = "completed", incomplete_details=None):
        super().__init__(
            id="resp_test",
            model="gpt-test",
            status=status,
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            incomplete_details=incomplete_details,
            output=[],
            output_text=output_text,
        )


class FakeResponses:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeOpenAIClient:
    def __init__(self, response):
        self.responses = FakeResponses(response)
        self.factory_kwargs = None


def _fake_client_factory(fake_client):
    def factory(**kwargs):
        fake_client.factory_kwargs = kwargs
        return fake_client

    return factory
