from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from llm_wiki.ai_runner import RunnerResult
from llm_wiki.notes_store import (
    add_note_link,
    create_feedback_reprocess_note,
    create_note,
    create_note_feedback,
    create_source_reanalysis_note,
    get_note,
    get_note_revision,
    list_note_feedback,
    list_note_revisions,
    list_notes,
    update_note,
)
from llm_wiki.personalization import update_personalization_settings
from llm_wiki.requests_store import content_sha256, create_request, get_request
from llm_wiki.time_store import list_time_items
from llm_wiki.worker import process_one


def test_process_one_db_note_creates_source_and_archives_inbox(db_settings):
    inbox = create_note(
        {
            "kind": "inbox",
            "status": "active",
            "title": "Worker DB Capture",
            "body_markdown": "Capture body",
            "metadata": {"channel": "pytest"},
        },
        db_settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=db_settings)
    request = create_request(
        {
            "source": "pytest-web",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )

    result = process_one(db_settings, runner_name="dry-run", worker_id="pytest-worker")

    row = get_request(request["id"], db_settings)
    archived = get_note(inbox["id"], db_settings)
    sources = list_notes(kind="source", settings=db_settings)
    assert result["status"] == "succeeded"
    assert row["status"] == "succeeded"
    assert row["target_note_id"] == result["target_note_id"]
    assert row["branch_name"] is None
    assert row["pr_url"] is None
    assert archived["kind"] == "archive"
    assert archived["status"] == "archived"
    assert sources[0]["id"] == result["target_note_id"]
    assert sources[0]["source_note_id"] == inbox["id"]
    assert "Capture body" in sources[0]["body_markdown"]
    assert sources[0]["metadata"]["processor"] == "db-note-runner:dry-run"


def test_process_one_db_note_does_not_touch_legacy_git_paths(db_settings, monkeypatch, tmp_path):
    settings = replace(
        db_settings,
        db_note_run_root=tmp_path / "db-note-runs",
    )
    inbox = create_note(
        {
            "kind": "inbox",
            "status": "active",
            "title": "DB Only Capture",
            "body_markdown": "DB-only worker smoke body.",
        },
        settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=settings)
    request = create_request(
        {
            "source": "pytest-web",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        settings,
    )
    preflight_paths: list[Path] = []

    class FakeRunner:
        def preflight(self, vault_path: Path) -> None:
            preflight_paths.append(vault_path)

        def run(self, runner_request: dict, vault_path: Path) -> RunnerResult:
            target = vault_path / "wiki" / "sources" / "db-only-capture.md"
            target.parent.mkdir(parents=True)
            target.write_text(
                "---\ntitle: DB Only Capture\n---\n\n"
                "# DB Only Capture\n\n"
                "## 요약\n\n"
                "DB-only worker smoke body.\n",
                encoding="utf-8",
            )
            return RunnerResult(summary="DB-only runner completed", changed_paths=["wiki/sources/db-only-capture.md"])

    monkeypatch.setattr("llm_wiki.worker.get_runner", lambda _name: FakeRunner())

    result = process_one(settings, runner_name="codex-cli", worker_id="pytest-worker")

    row = get_request(request["id"], settings)
    assert result["status"] == "succeeded"
    assert row["status"] == "succeeded"
    assert row["branch_name"] is None
    assert row["pr_url"] is None
    assert preflight_paths == [settings.db_note_run_root]
    assert settings.db_note_run_root.exists()


def test_process_one_prefers_db_note_over_older_legacy_request(db_settings, monkeypatch, tmp_path):
    settings = replace(
        db_settings,
        db_note_run_root=tmp_path / "db-note-runs",
    )
    legacy = create_request(
        {
            "source": "legacy-pytest",
            "operation": "ingest",
            "input_mode": "file-path",
            "file_path": "inbox/manual/legacy.md",
            "content_snapshot": "Legacy file-path request",
        },
        settings,
    )
    inbox = create_note(
        {
            "kind": "inbox",
            "status": "active",
            "title": "Preferred DB Capture",
            "body_markdown": "DB note should not wait behind legacy Git.",
        },
        settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=settings)
    db_request = create_request(
        {
            "source": "pytest-web",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        settings,
    )

    class FakeRunner:
        def preflight(self, vault_path: Path) -> None:
            assert vault_path == settings.db_note_run_root

        def run(self, runner_request: dict, vault_path: Path) -> RunnerResult:
            target = vault_path / "wiki" / "sources" / "preferred-db-capture.md"
            target.parent.mkdir(parents=True)
            target.write_text(
                "---\ntitle: Preferred DB Capture\n---\n\n"
                "# Preferred DB Capture\n\n"
                "## 요약\n\n"
                "DB note should not wait behind legacy Git.\n",
                encoding="utf-8",
            )
            return RunnerResult(summary="DB-note prioritized", changed_paths=["wiki/sources/preferred-db-capture.md"])

    monkeypatch.setattr("llm_wiki.worker.get_runner", lambda _name: FakeRunner())

    result = process_one(settings, runner_name="codex-cli", worker_id="pytest-worker")

    assert result["status"] == "succeeded"
    assert result["id"] == db_request["id"]
    assert get_request(db_request["id"], settings)["status"] == "succeeded"
    legacy_row = get_request(legacy["id"], settings)
    assert legacy_row["status"] == "queued"
    assert legacy_row["attempts"] == 0


def test_process_one_db_note_passes_personalization_context_to_runner(db_settings, monkeypatch, tmp_path):
    settings = replace(db_settings, db_note_run_root=tmp_path / "db-note-runs")
    update_personalization_settings(
        {
            "timezone": "UTC",
            "default_schedule_days": 45,
            "daily_digest_time": "07:30",
            "default_reminder_minutes": 30,
            "default_notification_channels": ["telegram"],
            "personal_terms": ["예약 완료"],
            "classification_seeds": ["개인 일정"],
            "record_only_terms": ["예약 완료"],
            "follow_up_terms": ["확인 필요"],
            "frequent_people": ["A"],
            "frequent_places": ["강릉"],
            "active_projects": ["llm-wiki"],
            "life_categories": ["건강"],
        },
        settings,
    )
    inbox = create_note(
        {
            "kind": "inbox",
            "status": "active",
            "title": "개인화 처리",
            "body_markdown": "예약 완료 기록을 정리한다.",
        },
        settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=settings)
    request = create_request(
        {
            "source": "pytest-web",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        settings,
    )

    class FakeRunner:
        def preflight(self, vault_path: Path) -> None:
            pass

        def run(self, runner_request: dict, vault_path: Path) -> RunnerResult:
            personalization = runner_request["personalization_context"]
            assert personalization["timezone"] == "UTC"
            assert personalization["default_schedule_days"] == 45
            assert personalization["default_reminder_minutes"] == 30
            assert personalization["personal_terms"] == ["예약 완료"]
            assert personalization["classification_seeds"] == ["개인 일정"]
            assert personalization["record_only_terms"] == ["예약 완료"]
            assert personalization["follow_up_terms"] == ["확인 필요"]
            assert personalization["frequent_people"] == ["A"]
            assert personalization["frequent_places"] == ["강릉"]
            assert personalization["active_projects"] == ["llm-wiki"]
            assert personalization["life_categories"] == ["건강"]
            source_text = (vault_path / runner_request["file_path"]).read_text(encoding="utf-8")
            assert "예약 완료 기록을 정리한다." in source_text
            assert "Personalization context" not in source_text
            assert "## 개인화 참고" not in source_text
            assert "강릉" not in source_text
            assert "llm-wiki" not in source_text
            assert "\nA\n" not in source_text
            target = vault_path / "wiki" / "sources" / "개인화-처리.md"
            target.parent.mkdir(parents=True)
            target.write_text(
                "---\ntitle: 개인화 처리\n---\n\n"
                "# 개인화 처리\n\n"
                "## 요약\n\n"
                "개인화 컨텍스트가 전달되었습니다.\n",
                encoding="utf-8",
            )
            return RunnerResult(summary="personalized", changed_paths=["wiki/sources/개인화-처리.md"])

    monkeypatch.setattr("llm_wiki.worker.get_runner", lambda _name: FakeRunner())

    result = process_one(settings, runner_name="codex-cli", worker_id="pytest-worker")

    row = get_request(request["id"], settings)
    assert result["status"] == "succeeded"
    assert row["status"] == "succeeded"


def test_process_one_db_note_uses_runner_generated_source_body(db_settings, monkeypatch):
    inbox = create_note(
        {
            "kind": "inbox",
            "status": "active",
            "title": "Runner DB Capture",
            "body_markdown": "Lunch rain after clear weather.",
            "metadata": {
                "channel": "pytest",
                "manual_topics": ["날씨 기록"],
                "manual_tags": ["날씨", "점심"],
            },
        },
        db_settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=db_settings)
    request = create_request(
        {
            "source": "pytest-web",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )
    calls = []

    class FakeRunner:
        def preflight(self, vault_path: Path) -> None:
            calls.append(("preflight", vault_path))

        def run(self, runner_request: dict, vault_path: Path) -> RunnerResult:
            calls.append(("run", vault_path, runner_request))
            source_file = vault_path / runner_request["file_path"]
            assert source_file.exists()
            source_text = source_file.read_text(encoding="utf-8")
            assert "Lunch rain after clear weather." in source_text
            assert "## 사용자 제공 메타데이터" in source_text
            assert "- 사용자 주제: 날씨 기록" in source_text
            assert "- 사용자 태그: 날씨; 점심" in source_text
            assert runner_request["source_note_created_at"]
            assert runner_request["source_note_updated_at"]
            assert runner_request["source_revision_created_at"]
            assert "- 소스 노트 생성일: `" in source_text
            assert "- 소스 노트 수정일: `" in source_text
            assert "- 소스 리비전 생성일: `" in source_text
            target = vault_path / "wiki" / "sources" / "runner-db-capture.md"
            target.parent.mkdir(parents=True)
            target.write_text(
                "---\ntitle: Runner DB Capture\n---\n\n"
                "# Runner DB Capture\n\n"
                "## 추출된 사실\n\n"
                "- 맑은 날씨였다가 점심 무렵 비가 왔습니다.\n",
                encoding="utf-8",
            )
            return RunnerResult(summary="가짜 러너가 소스 노트를 작성했습니다.", changed_paths=["wiki/sources/runner-db-capture.md"])

    monkeypatch.setattr("llm_wiki.worker.get_runner", lambda _name: FakeRunner())

    result = process_one(db_settings, runner_name="codex-cli", worker_id="pytest-worker")

    row = get_request(request["id"], db_settings)
    archived = get_note(inbox["id"], db_settings)
    sources = list_notes(kind="source", settings=db_settings)
    assert [call[0] for call in calls] == ["preflight", "run"]
    assert calls[0][1] == db_settings.db_note_run_root
    assert calls[1][1].parent == db_settings.db_note_run_root
    assert result["status"] == "succeeded"
    assert row["status"] == "succeeded"
    assert archived["kind"] == "archive"
    assert sources[0]["id"] == result["target_note_id"]
    assert "점심 무렵 비가 왔습니다." in sources[0]["body_markdown"]
    assert "---" not in sources[0]["body_markdown"].splitlines()[0]
    assert sources[0]["metadata"]["processor"] == "db-note-runner:codex-cli"
    assert sources[0]["metadata"]["runner_summary"] == "가짜 러너가 소스 노트를 작성했습니다."


def test_process_one_db_note_auto_registers_time_suggestions_when_enabled(db_settings, monkeypatch):
    settings = replace(db_settings, time_suggestion_auto_register_enabled=True)
    inbox = create_note(
        {
            "kind": "inbox",
            "status": "active",
            "title": "Visit Memo",
            "body_markdown": "A will visit on July 1.",
            "metadata": {"channel": "pytest"},
        },
        settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=settings)
    request = create_request(
        {
            "source": "pytest-web",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        settings,
    )

    class FakeRunner:
        def preflight(self, vault_path: Path) -> None:
            pass

        def run(self, runner_request: dict, vault_path: Path) -> RunnerResult:
            target = vault_path / "wiki" / "sources" / "visit-memo.md"
            target.parent.mkdir(parents=True)
            target.write_text(
                "---\ntitle: Visit Memo\n---\n\n"
                "# Visit Memo\n\n"
                "## 관련\n\n"
                "### 일정 제안\n\n"
                "| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| A 방문 | 일정 | event | 2026-07-01T10:00:00+09:00 |  |  | 2026-07-01T09:30:00+09:00 | Asia/Seoul | July 1 visit | |\n",
                encoding="utf-8",
            )
            return RunnerResult(summary="일정 후보 생성", changed_paths=["wiki/sources/visit-memo.md"])

    monkeypatch.setattr("llm_wiki.worker.get_runner", lambda _name: FakeRunner())

    result = process_one(settings, runner_name="codex-cli", worker_id="pytest-worker")

    row = get_request(request["id"], settings)
    items = list_time_items(note_id=result["target_note_id"], include_closed=True, settings=settings)
    assert result["status"] == "succeeded"
    assert row["status"] == "succeeded"
    assert result["time_auto_register"]["status"] == "succeeded"
    assert len(result["time_auto_register"]["created"]) == 1
    assert len(items) == 1
    assert items[0]["title"] == "A 방문"
    assert items[0]["created_by"] == "worker"


def test_process_one_db_note_skips_time_suggestion_with_personalization_evidence(db_settings, monkeypatch):
    settings = replace(db_settings, time_suggestion_auto_register_enabled=True)
    inbox = create_note(
        {
            "kind": "inbox",
            "status": "active",
            "title": "Personalized Schedule",
            "body_markdown": "짧은 메모입니다.",
            "metadata": {"channel": "pytest"},
        },
        settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=settings)
    request = create_request(
        {
            "source": "pytest-web",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        settings,
    )

    class FakeRunner:
        def preflight(self, vault_path: Path) -> None:
            pass

        def run(self, runner_request: dict, vault_path: Path) -> RunnerResult:
            target = vault_path / "wiki" / "sources" / "personalized-schedule.md"
            target.parent.mkdir(parents=True)
            target.write_text(
                "---\ntitle: Personalized Schedule\n---\n\n"
                "# Personalized Schedule\n\n"
                "## 관련\n\n"
                "### 일정 제안\n\n"
                "| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| 개인 일정 | 일정 | event | 2026-07-01T10:00:00+09:00 |  |  | 2026-07-01T09:30:00+09:00 | Asia/Seoul | 개인화 참고의 기본 일정 힌트 | Personalization context only |\n",
                encoding="utf-8",
            )
            return RunnerResult(summary="비근거 일정 후보", changed_paths=["wiki/sources/personalized-schedule.md"])

    monkeypatch.setattr("llm_wiki.worker.get_runner", lambda _name: FakeRunner())

    result = process_one(settings, runner_name="codex-cli", worker_id="pytest-worker")

    row = get_request(request["id"], settings)
    items = list_time_items(note_id=result["target_note_id"], include_closed=True, settings=settings)
    assert result["status"] == "succeeded"
    assert row["status"] == "succeeded"
    assert result["time_auto_register"]["status"] == "succeeded"
    assert result["time_auto_register"]["created"] == []
    assert result["time_auto_register"]["skipped"][0]["reason"] == "personalization_evidence"
    assert items == []


def test_process_one_feedback_reprocess_updates_target_source(db_settings, monkeypatch):
    original_inbox = create_note(
        {
            "kind": "archive",
            "status": "archived",
            "title": "A 방문 원본",
            "body_markdown": "A가 6월 6일 놀러오기로 함",
            "metadata": {"channel": "web"},
        },
        db_settings,
    )
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "A 방문 일정",
            "body_markdown": "# A 방문 일정\n\nA가 2026년 6월 6일 방문 예정입니다.",
            "metadata": {"channel": "web"},
            "source_note_id": original_inbox["id"],
        },
        db_settings,
    )
    feedback = create_note_feedback(
        source["id"],
        {
            "feedback_type": "change",
            "body_markdown": "A가 2026년 7월 1일에 놀러오기로 변경함",
        },
        db_settings,
    )
    reprocess = create_feedback_reprocess_note(source["id"], settings=db_settings)
    revision = reprocess["revision"]
    request = create_request(
        {
            "source": "pytest-feedback",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": reprocess["note"]["id"],
            "source_revision_id": revision["id"],
            "target_note_id": source["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )

    class FakeRunner:
        def preflight(self, vault_path: Path) -> None:
            pass

        def run(self, runner_request: dict, vault_path: Path) -> RunnerResult:
            assert runner_request["target_note_id"] == source["id"]
            assert "A가 2026년 7월 1일에 놀러오기로 변경함" in runner_request["content_snapshot"]
            target = vault_path / "wiki" / "sources" / "a-방문-일정.md"
            assert target.exists()
            target.write_text(
                "---\ntitle: A 방문 일정\n---\n\n"
                "# A 방문 일정\n\n"
                "## 요약\n\n"
                "A는 2026년 7월 1일 방문 예정입니다.\n",
                encoding="utf-8",
            )
            return RunnerResult(summary="피드백 반영 완료", changed_paths=["wiki/sources/a-방문-일정.md"])

    monkeypatch.setattr("llm_wiki.worker.get_runner", lambda _name: FakeRunner())

    result = process_one(db_settings, runner_name="codex-cli", worker_id="pytest-worker")

    request_row = get_request(request["id"], db_settings)
    updated_source = get_note(source["id"], db_settings)
    archived_reprocess_note = get_note(reprocess["note"]["id"], db_settings)
    feedback_rows = list_note_feedback(source["id"], include_closed=True, settings=db_settings)
    sources = list_notes(kind="source", settings=db_settings)
    assert result["status"] == "succeeded"
    assert result["target_note_id"] == source["id"]
    assert request_row["target_note_id"] == source["id"]
    assert updated_source["id"] == source["id"]
    assert updated_source["source_note_id"] == original_inbox["id"]
    assert "2026년 7월 1일" in updated_source["body_markdown"]
    assert archived_reprocess_note["kind"] == "archive"
    assert feedback_rows[0]["id"] == feedback["id"]
    assert feedback_rows[0]["status"] == "applied"
    assert len(sources) == 1


def test_process_one_source_reanalysis_updates_target_source(db_settings, monkeypatch):
    original_inbox = create_note(
        {
            "kind": "archive",
            "status": "archived",
            "title": "스타벅스 충전 원본",
            "body_markdown": "오늘 스타벅스에 3만원을 충전함",
            "metadata": {"channel": "web"},
        },
        db_settings,
    )
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "스타벅스 충전 기록",
            "body_markdown": "# 스타벅스 충전 기록\n\n오늘 스타벅스에 3만원을 충전했다고 분석함.",
            "metadata": {"channel": "web", "manual_tags": ["생활"]},
            "source_note_id": original_inbox["id"],
        },
        db_settings,
    )
    topic = create_note(
        {
            "kind": "topic",
            "status": "active",
            "title": "스타벅스 충전",
            "body_markdown": "# 스타벅스 충전\n\n기존 주제",
        },
        db_settings,
    )
    entity = create_note(
        {
            "kind": "entity",
            "status": "active",
            "title": "스타벅스",
            "body_markdown": "# 스타벅스\n\n기존 대상",
        },
        db_settings,
    )
    add_note_link(
        source["id"],
        target_text="스타벅스 충전",
        to_note_id=topic["id"],
        link_type="topic_suggestion",
        settings=db_settings,
    )
    add_note_link(
        source["id"],
        target_text="스타벅스",
        to_note_id=entity["id"],
        link_type="entity_suggestion",
        settings=db_settings,
    )
    create_note_feedback(
        source["id"],
        {
            "expected_version": source["version"],
            "feedback_type": "correction",
            "body_markdown": "원문 기준으로 충전 표현을 다시 확인",
            "created_by": "pytest",
        },
        db_settings,
    )
    reanalysis = create_source_reanalysis_note(
        source["id"],
        expected_version=source["version"],
        settings=db_settings,
    )
    revision = reanalysis["revision"]
    request = create_request(
        {
            "source": "pytest-reanalysis",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": reanalysis["note"]["id"],
            "source_revision_id": revision["id"],
            "target_note_id": source["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )

    class FakeRunner:
        def preflight(self, vault_path: Path) -> None:
            pass

        def run(self, runner_request: dict, vault_path: Path) -> RunnerResult:
            assert runner_request["target_note_id"] == source["id"]
            assert "## 재분석 지시" in runner_request["content_snapshot"]
            assert "더 나은 읽기용 정리, 요약" in runner_request["content_snapshot"]
            assert "## 원문" in runner_request["content_snapshot"]
            assert "## 현재 소스 노트" in runner_request["content_snapshot"]
            assert "## 사용자 피드백" in runner_request["content_snapshot"]
            assert "원문 기준으로 충전 표현을 다시 확인" in runner_request["content_snapshot"]
            assert "오늘 스타벅스에 3만원" in runner_request["content_snapshot"]
            target = vault_path / "wiki" / "sources" / "스타벅스-충전-기록.md"
            assert target.exists()
            target.write_text(
                "---\ntitle: 스타벅스 충전 기록\n---\n\n"
                "# 스타벅스 충전 기록\n\n"
                "## 요약\n\n"
                "스타벅스 선불 충전 기록을 최신 기준으로 재검토했습니다.\n",
                encoding="utf-8",
            )
            return RunnerResult(summary="재분석 완료", changed_paths=["wiki/sources/스타벅스-충전-기록.md"])

    monkeypatch.setattr("llm_wiki.worker.get_runner", lambda _name: FakeRunner())

    result = process_one(db_settings, runner_name="codex-cli", worker_id="pytest-worker")

    request_row = get_request(request["id"], db_settings)
    updated_source = get_note(source["id"], db_settings)
    archived_reanalysis_note = get_note(reanalysis["note"]["id"], db_settings)
    sources = list_notes(kind="source", settings=db_settings)
    assert result["status"] == "succeeded"
    assert result["target_note_id"] == source["id"]
    assert request_row["status"] == "succeeded"
    assert request_row["target_note_id"] == source["id"]
    assert updated_source["id"] == source["id"]
    assert updated_source["version"] == source["version"] + 1
    assert updated_source["source_note_id"] == original_inbox["id"]
    assert updated_source["metadata"]["manual_tags"] == ["생활"]
    assert updated_source["metadata"]["manual_topics"] == ["스타벅스 충전"]
    assert updated_source["metadata"]["manual_entities"] == ["스타벅스"]
    assert updated_source["metadata"]["approved_topics"] == [{"title": "스타벅스 충전", "note_id": topic["id"]}]
    assert updated_source["metadata"]["approved_entities"] == [{"title": "스타벅스", "note_id": entity["id"]}]
    assert "최신 기준으로 재검토" in updated_source["body_markdown"]
    assert "## 승인된 연결" in updated_source["body_markdown"]
    assert f"- 스타벅스 충전 (`{topic['id']}`)" in updated_source["body_markdown"]
    assert f"- 스타벅스 (`{entity['id']}`)" in updated_source["body_markdown"]
    assert archived_reanalysis_note["kind"] == "archive"
    assert len(sources) == 1


def test_process_one_source_reanalysis_refreshes_promoted_target_summary(db_settings, monkeypatch):
    source = create_note(
        {
            "id": "note_worker_toothpaste_source",
            "kind": "source",
            "status": "active",
            "title": "치약 구매 필요",
            "slug": "toothpaste-source",
            "body_markdown": "# 치약 구매 필요\n\n## 읽기용 정리\n\n치약이 다 떨어져 구매가 필요합니다.",
        },
        db_settings,
    )
    entity = create_note(
        {
            "id": "note_worker_toothpaste_entity",
            "kind": "entity",
            "status": "active",
            "title": "치약",
            "slug": "toothpaste",
            "body_markdown": "# 치약\n\n## 요약\n\n이전 대상 요약입니다.\n",
            "metadata": {
                "promotion_status": "approved",
                "created_kind": "entity",
                "suggested_path": "wiki/entities/toothpaste.md",
                "evidence": "치약",
                "review_note": "생활용품 재고 대상",
            },
        },
        db_settings,
    )
    add_note_link(
        source["id"],
        target_text="치약",
        to_note_id=entity["id"],
        link_type="entity_suggestion",
        settings=db_settings,
    )
    reanalysis = create_source_reanalysis_note(
        source["id"],
        expected_version=source["version"],
        settings=db_settings,
    )
    revision = reanalysis["revision"]
    request = create_request(
        {
            "source": "pytest-reanalysis",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": reanalysis["note"]["id"],
            "source_revision_id": revision["id"],
            "target_note_id": source["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )

    class FakeRunner:
        def preflight(self, vault_path: Path) -> None:
            pass

        def run(self, runner_request: dict, vault_path: Path) -> RunnerResult:
            target = vault_path / "wiki" / "sources" / "toothpaste-source.md"
            assert target.exists()
            target.write_text(
                "# 치약 구매 완료\n\n"
                "## 읽기용 정리\n\n"
                "치약 구매가 완료되어 현재 추가 구매 필요는 낮습니다.\n\n"
                "## 요약\n\n"
                "치약 구매 필요 상태가 구매 완료 상태로 정정되었습니다.\n",
                encoding="utf-8",
            )
            return RunnerResult(summary="재분석 완료", changed_paths=["wiki/sources/toothpaste-source.md"])

    monkeypatch.setattr("llm_wiki.worker.get_runner", lambda _name: FakeRunner())

    result = process_one(db_settings, runner_name="codex-cli", worker_id="pytest-worker")

    updated_entity = get_note(entity["id"], db_settings)
    entity_revisions = list_note_revisions(entity["id"], settings=db_settings)
    assert result["status"] == "succeeded"
    assert result["promoted_targets_refresh"]["refreshed"] == [entity["id"]]
    assert get_request(request["id"], db_settings)["status"] == "succeeded"
    assert "치약 구매가 완료되어 현재 추가 구매 필요는 낮습니다." in updated_entity["body_markdown"]
    assert f"치약 구매 완료 (`{source['id']}`)" in updated_entity["body_markdown"]
    assert entity_revisions[0]["created_by"] == "source-refresh"


def test_process_one_source_reanalysis_fails_when_promoted_target_refresh_fails(db_settings, monkeypatch):
    source = create_note(
        {
            "id": "note_worker_refresh_failure_source",
            "kind": "source",
            "status": "active",
            "title": "대상 갱신 실패 소스",
            "slug": "refresh-failure-source",
            "body_markdown": "# 대상 갱신 실패 소스\n\n기존 분석",
        },
        db_settings,
    )
    reanalysis = create_source_reanalysis_note(
        source["id"],
        expected_version=source["version"],
        settings=db_settings,
    )
    revision = reanalysis["revision"]
    request = create_request(
        {
            "source": "pytest-reanalysis",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": reanalysis["note"]["id"],
            "source_revision_id": revision["id"],
            "target_note_id": source["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )

    class FakeRunner:
        def preflight(self, vault_path: Path) -> None:
            pass

        def run(self, runner_request: dict, vault_path: Path) -> RunnerResult:
            target = vault_path / "wiki" / "sources" / "refresh-failure-source.md"
            target.write_text("# 대상 갱신 실패 소스\n\n## 요약\n\n갱신된 분석입니다.\n", encoding="utf-8")
            return RunnerResult(summary="재분석 완료", changed_paths=["wiki/sources/refresh-failure-source.md"])

    def fail_refresh(*args, **kwargs):
        raise RuntimeError("target refresh failed")

    monkeypatch.setattr("llm_wiki.worker.get_runner", lambda _name: FakeRunner())
    monkeypatch.setattr("llm_wiki.worker.refresh_promoted_targets_for_source", fail_refresh)

    result = process_one(db_settings, runner_name="codex-cli", worker_id="pytest-worker")

    request_row = get_request(request["id"], db_settings)
    assert result["status"] == "failed"
    assert "target refresh failed" in result["error"]
    assert request_row["status"] == "failed"
    assert "target refresh failed" in request_row["error_message"]


def test_process_one_source_reanalysis_marks_stale_target_needs_sync(db_settings):
    source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "재분석 충돌",
            "body_markdown": "# 재분석 충돌\n\n기존 분석",
        },
        db_settings,
    )
    reanalysis = create_source_reanalysis_note(
        source["id"],
        expected_version=source["version"],
        settings=db_settings,
    )
    revision = reanalysis["revision"]
    request = create_request(
        {
            "source": "pytest-reanalysis",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": reanalysis["note"]["id"],
            "source_revision_id": revision["id"],
            "target_note_id": source["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )
    update_note(
        source["id"],
        expected_version=source["version"],
        body_markdown="# 재분석 충돌\n\n사용자가 먼저 고친 분석",
        change_source="test",
        settings=db_settings,
    )

    result = process_one(db_settings, runner_name="dry-run", worker_id="pytest-worker")

    row = get_request(request["id"], db_settings)
    current = get_note(source["id"], db_settings)
    assert result["status"] == "needs_sync"
    assert row["status"] == "needs_sync"
    assert "target source note changed" in row["error_message"]
    assert current["version"] == source["version"] + 1
    assert "사용자가 먼저 고친 분석" in current["body_markdown"]


def test_process_one_db_note_auto_exports_target_when_enabled(db_settings, monkeypatch):
    settings = replace(db_settings, worker_db_note_auto_export_enabled=True)
    inbox = create_note(
        {
            "kind": "inbox",
            "status": "active",
            "title": "Auto Export Capture",
            "body_markdown": "Capture body",
            "metadata": {"channel": "pytest"},
        },
        settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=settings)
    request = create_request(
        {
            "source": "pytest-web",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        settings,
    )
    calls = []

    def fake_export(export_settings, *, scope, note_id, dry_run, sync, push):
        calls.append(
            {
                "settings": export_settings,
                "scope": scope,
                "note_id": note_id,
                "dry_run": dry_run,
                "sync": sync,
                "push": push,
            }
        )
        return {
            "job_id": "export_pytest",
            "status": "succeeded",
            "scope": scope,
            "note_id": note_id,
            "exported_count": 1,
            "changed_paths": ["wiki/sources/auto-export-capture.md"],
            "content_commit_sha": "abc123",
            "pushed": True,
        }

    monkeypatch.setattr("llm_wiki.worker.export_notes_to_markdown", fake_export)

    result = process_one(settings, runner_name="dry-run", worker_id="pytest-worker")

    row = get_request(request["id"], settings)
    assert result["status"] == "succeeded"
    assert row["status"] == "succeeded"
    assert calls == [
        {
            "settings": settings,
            "scope": "note-id",
            "note_id": result["target_note_id"],
            "dry_run": False,
            "sync": False,
            "push": False,
        }
    ]
    assert result["export"]["status"] == "succeeded"
    assert result["export"]["note_id"] == result["target_note_id"]


def test_process_one_db_note_auto_export_failure_keeps_request_succeeded(db_settings, monkeypatch):
    settings = replace(db_settings, worker_db_note_auto_export_enabled=True)
    inbox = create_note(
        {
            "kind": "inbox",
            "status": "active",
            "title": "Auto Export Failure",
            "body_markdown": "Capture body",
        },
        settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=settings)
    request = create_request(
        {
            "source": "pytest-web",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        settings,
    )

    def failing_export(*args, **kwargs):
        raise RuntimeError("git mirror unavailable")

    monkeypatch.setattr("llm_wiki.worker.export_notes_to_markdown", failing_export)

    result = process_one(settings, runner_name="dry-run", worker_id="pytest-worker")

    row = get_request(request["id"], settings)
    assert result["status"] == "succeeded"
    assert row["status"] == "succeeded"
    assert row["target_note_id"] == result["target_note_id"]
    assert result["export"]["status"] == "failed"
    assert result["export"]["note_id"] == result["target_note_id"]
    assert "git mirror unavailable" in result["export"]["error"]


def test_process_one_db_note_marks_stale_source_needs_sync(db_settings):
    inbox = create_note(
        {
            "kind": "inbox",
            "status": "active",
            "title": "Worker Stale Capture",
            "body_markdown": "Original body",
        },
        db_settings,
    )
    revision = get_note_revision(inbox["id"], version=1, settings=db_settings)
    request = create_request(
        {
            "source": "pytest-web",
            "operation": "ingest",
            "input_mode": "db-note",
            "note_id": inbox["id"],
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
        },
        db_settings,
    )
    update_note(
        inbox["id"],
        expected_version=1,
        body_markdown="Changed body",
        status="active",
        change_source="test",
        settings=db_settings,
    )

    result = process_one(db_settings, runner_name="dry-run", worker_id="pytest-worker")

    row = get_request(request["id"], db_settings)
    current = get_note(inbox["id"], db_settings)
    assert result["status"] == "needs_sync"
    assert row["status"] == "needs_sync"
    assert "source note changed" in row["error_message"]
    assert current["kind"] == "inbox"
    assert current["status"] == "active"
    assert list_notes(kind="source", settings=db_settings) == []
