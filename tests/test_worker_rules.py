from __future__ import annotations

from llm_wiki.worker import _classified_error, _finish_legacy_file_request_unsupported


def test_legacy_file_request_is_rejected_without_git(monkeypatch, db_settings):
    finished = []

    def fake_finish_owned_request(request_id, status, worker_id, *, error_message=None, settings=None, **_kwargs):
        finished.append(
            {
                "request_id": request_id,
                "status": status,
                "worker_id": worker_id,
                "error_message": error_message,
                "settings": settings,
            }
        )
        return {"id": request_id, "status": status}

    monkeypatch.setattr("llm_wiki.worker.finish_owned_request", fake_finish_owned_request)

    result = _finish_legacy_file_request_unsupported(
        {"id": "req_legacy", "input_mode": "file-path"},
        "worker-1",
        db_settings,
    )

    assert result["status"] == "failed"
    assert "legacy file-path requests are no longer processed" in result["error"]
    assert finished == [
        {
            "request_id": "req_legacy",
            "status": "failed",
            "worker_id": "worker-1",
            "error_message": result["error"],
            "settings": db_settings,
        }
    ]


def test_classified_error_adds_operational_prefixes():
    assert _classified_error(RuntimeError("codex cli is not authenticated")).startswith("auth:")
    assert _classified_error(RuntimeError("content hash mismatch")).startswith("sync:")
    assert _classified_error(RuntimeError("legacy file-path requests are no longer processed")).startswith("legacy:")
    assert _classified_error(RuntimeError("unexpected")).startswith("runner:")
