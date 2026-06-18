from __future__ import annotations

import uuid

from llm_wiki.db import connect
from llm_wiki.requests_store import (
    cancel_request,
    claim_next,
    count_failed_requests_by_source,
    create_request,
    finish_owned_request,
    get_request,
    has_claimable_request,
    list_request_reviews,
    list_request_runners,
    list_request_sources,
    list_requests,
    peek_claimable_request,
    request_is_owned,
    retry_request,
    requeue_stale_running,
    set_request_review,
    update_status,
)
from llm_wiki.worker import process_one


def request_id() -> str:
    return f"req_test_{uuid.uuid4().hex}"


def test_request_lifecycle_claim_retry_cancel(db_settings):
    rid = request_id()
    created = create_request({"id": rid, "source": "pytest", "operation": "ingest", "file_path": "inbox/test.md"}, db_settings)
    assert created["status"] == "queued"
    assert has_claimable_request(max_attempts=3, retry_backoff_seconds=300, settings=db_settings)
    assert peek_claimable_request(max_attempts=3, retry_backoff_seconds=300, settings=db_settings)["input_mode"] == "file-path"

    claimed = claim_next("worker-a", db_settings, max_attempts=3, retry_backoff_seconds=300, runner_name="dry-run")
    assert claimed["id"] == rid
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1
    assert claimed["runner_name"] == "dry-run"
    assert request_is_owned(rid, "worker-a", db_settings)

    failed = finish_owned_request(rid, "failed", "worker-a", error_message="runner: pytest", settings=db_settings)
    assert failed["status"] == "failed"

    retried = retry_request(rid, db_settings, max_attempts=3)
    assert retried["status"] == "queued"
    assert retried["attempts"] == 1

    cancelled = cancel_request(rid, reason="pytest cleanup", settings=db_settings)
    assert cancelled["status"] == "cancelled"
    assert get_request(rid, db_settings)["attachments"] == []


def test_retry_attempt_limits_and_reset(db_settings):
    rid = request_id()
    create_request({"id": rid, "source": "pytest", "operation": "ingest", "file_path": "inbox/test.md"}, db_settings)
    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update processing_requests
                   set status = 'failed', attempts = 3, error_message = 'maxed'
                 where id = %s
                """,
                (rid,),
            )
        conn.commit()

    assert retry_request(rid, db_settings, max_attempts=3) is None
    reset = retry_request(rid, db_settings, max_attempts=3, reset_attempts=True)
    assert reset["status"] == "queued"
    assert reset["attempts"] == 0


def test_backoff_and_stale_max_attempt_handling(db_settings):
    rid = request_id()
    create_request({"id": rid, "source": "pytest", "operation": "ingest", "file_path": "inbox/test.md"}, db_settings)
    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update processing_requests
                   set status = 'queued', attempts = 1, updated_at = now()
                 where id = %s
                """,
                (rid,),
            )
        conn.commit()

    assert not has_claimable_request(max_attempts=3, retry_backoff_seconds=300, settings=db_settings)
    assert has_claimable_request(max_attempts=3, retry_backoff_seconds=0, settings=db_settings)

    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update processing_requests
                   set status = 'running',
                       attempts = 3,
                       locked_by = 'pytest',
                       locked_at = now() - interval '2 hours',
                       updated_at = now() - interval '2 hours'
                 where id = %s
                """,
                (rid,),
            )
        conn.commit()

    rows = requeue_stale_running(older_than_minutes=60, limit=5, max_attempts=3, settings=db_settings)
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["error_message"] == "stale running request exceeded max attempts"


def test_openai_api_runner_preflight_blocks_before_claim(db_settings):
    rid = request_id()
    create_request({"id": rid, "source": "pytest", "operation": "ingest", "file_path": "inbox/test.md"}, db_settings)

    result = process_one(db_settings, runner_name="openai-api", worker_id="pytest-worker")

    assert result is not None
    assert result["status"] == "blocked"
    assert "openai-api runner is disabled" in result["error"]
    row = get_request(rid, db_settings)
    assert row["status"] == "queued"
    assert row["attempts"] == 0


def test_list_requests_filters_by_source_query_status_and_runner(db_settings):
    first = request_id()
    second = request_id()
    create_request(
        {"id": first, "source": "plugin-quick-capture", "operation": "ingest", "file_path": "inbox/mobile/alpha.md"},
        db_settings,
    )
    create_request(
        {"id": second, "source": "manual", "operation": "ingest", "file_path": "inbox/manual/beta.md"},
        db_settings,
    )
    finish_owned_request(
        claim_next("worker-a", db_settings, max_attempts=3, retry_backoff_seconds=0, runner_name="codex-cli")["id"],
        "failed",
        "worker-a",
        error_message="runner: alpha needs review",
        settings=db_settings,
    )

    rows = list_requests(
        status="failed",
        source="plugin-quick-capture",
        runner="codex-cli",
        query="alpha",
        settings=db_settings,
    )

    assert [row["id"] for row in rows] == [first]
    assert rows[0]["runner_name"] == "codex-cli"
    assert list_requests(status="failed", runner="openai-api", query="alpha", settings=db_settings) == []
    assert list_request_sources(db_settings) == ["manual", "plugin-quick-capture"]
    assert "codex-cli" in list_request_runners(db_settings)


def test_request_review_metadata_set_and_list(db_settings):
    useful = request_id()
    poor = request_id()
    needs_review = request_id()
    create_request({"id": useful, "source": "pytest", "operation": "ingest", "file_path": "inbox/useful.md"}, db_settings)
    create_request({"id": poor, "source": "pytest", "operation": "ingest", "file_path": "inbox/noisy.md"}, db_settings)
    create_request(
        {"id": needs_review, "source": "pytest", "operation": "ingest", "file_path": "inbox/review.md"},
        db_settings,
    )
    update_status(useful, "succeeded", pr_url="https://git.example.com/example-owner/llm-wiki/pulls/1", settings=db_settings)
    update_status(poor, "failed", pr_url="https://git.example.com/example-owner/llm-wiki/pulls/2", settings=db_settings)
    update_status(needs_review, "succeeded", settings=db_settings)

    first_review = set_request_review(
        useful,
        outcome="useful",
        note="good source synthesis",
        reviewed_by="pmk",
        settings=db_settings,
    )
    assert first_review["outcome"] == "useful"
    assert get_request(useful, db_settings).get("review") is None
    assert get_request(useful, db_settings, include_review=True)["review"]["note"] == "good source synthesis"

    set_request_review(
        poor,
        outcome="manual_rewrite",
        note="required manual rewrite",
        reviewed_by="pmk",
        settings=db_settings,
    )

    assert [row["id"] for row in list_request_reviews(outcome="useful", settings=db_settings)] == [useful]
    assert [row["id"] for row in list_request_reviews(poor=True, settings=db_settings)] == [poor]
    assert [row["id"] for row in list_request_reviews(needs_review=True, settings=db_settings)] == [needs_review]
    retry_request(poor, db_settings, max_attempts=3)
    assert get_request(poor, db_settings, include_review=True)["review"]["outcome"] == "manual_rewrite"
    assert set_request_review("req_missing_review", outcome="useful", settings=db_settings) is None


def test_count_failed_requests_by_source(db_settings):
    first = request_id()
    second = request_id()
    third = request_id()
    fourth = request_id()
    create_request({"id": first, "source": "plugin", "operation": "ingest", "file_path": "inbox/first.md"}, db_settings)
    create_request({"id": second, "source": "plugin", "operation": "ingest", "file_path": "inbox/second.md"}, db_settings)
    create_request({"id": third, "source": "manual", "operation": "ingest", "file_path": "inbox/third.md"}, db_settings)
    create_request({"id": fourth, "source": "plugin", "operation": "ingest", "file_path": "inbox/fourth.md"}, db_settings)
    finish_owned_request(
        claim_next("worker-a", db_settings, max_attempts=3, retry_backoff_seconds=0, runner_name="codex-cli")["id"],
        "failed",
        "worker-a",
        error_message="runner failed\nwith detail",
        settings=db_settings,
    )
    finish_owned_request(
        claim_next("worker-b", db_settings, max_attempts=3, retry_backoff_seconds=0, runner_name="codex-cli")["id"],
        "failed",
        "worker-b",
        error_message="runner failed   with detail",
        settings=db_settings,
    )
    update_status(third, "succeeded", settings=db_settings)
    finish_owned_request(
        claim_next("worker-c", db_settings, max_attempts=3, retry_backoff_seconds=0, runner_name="openai-api")["id"],
        "failed",
        "worker-c",
        error_message="auth: missing key",
        settings=db_settings,
    )

    rows = count_failed_requests_by_source(db_settings)

    assert rows[0]["runner"] == "codex-cli"
    assert rows[0]["input_mode"] == "file-path"
    assert rows[0]["source"] == "plugin"
    assert rows[0]["error_reason"] == "runner failed with detail"
    assert rows[0]["count"] == 2
    assert rows[1]["runner"] == "openai-api"
    assert rows[1]["error_reason"] == "auth: missing key"
    assert rows[1]["count"] == 1

    runner_rows = count_failed_requests_by_source(db_settings, runner="codex-cli")
    assert len(runner_rows) == 1
    assert runner_rows[0]["runner"] == "codex-cli"
    assert runner_rows[0]["count"] == 2
