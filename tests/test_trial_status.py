from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from llm_wiki.api import app, settings_dep
from llm_wiki.notes_store import create_export_job, create_note, get_note_revision, update_export_job
from llm_wiki.requests_store import create_request, update_status
from llm_wiki.trial_status import create_web_trial_feedback, get_web_trial_status


def test_web_trial_status_counts_real_web_workflow_and_feedback(db_settings):
    real_notes = [
        create_note(
            {
                "kind": "inbox",
                "status": "active",
                "title": f"Real Trial Note {index}",
                "body_markdown": "Real web note",
                "metadata": {"channel": "web"},
                "change_source": "web",
                "created_by": "web-ui",
            },
            db_settings,
        )
        for index in range(5)
    ]
    direct_notes = [
        create_note(
            {
                "kind": kind,
                "status": "active",
                "title": f"Direct Web {kind}",
                "body_markdown": f"Direct {kind} body",
                "metadata": {"channel": "web", "created_kind": kind},
                "change_source": "web",
                "created_by": "web-ui",
            },
            db_settings,
        )
        for kind in ["source", "topic", "entity", "log"]
    ]
    smoke = create_note(
        {
            "kind": "inbox",
            "status": "active",
            "title": "Synthetic Trial Note",
            "body_markdown": "2026-06-04-w7-trial",
            "metadata": {"channel": "web", "trial_marker": "2026-06-04-w7-trial"},
            "change_source": "web",
            "created_by": "web-ui",
        },
        db_settings,
    )

    for index, note in enumerate([*real_notes[:3], smoke]):
        revision = get_note_revision(note["id"], version=1, settings=db_settings)
        target = create_note(
            {
                "kind": "source",
                "status": "active",
                "title": f"Processed Source {index}",
                "body_markdown": "Processed body",
                "metadata": {"channel": "web"},
                "source_note_id": note["id"],
                "change_source": "worker",
                "created_by": "worker",
            },
            db_settings,
        )
        request = create_request(
            {
                "source": "web-note",
                "operation": "ingest",
                "input_mode": "db-note",
                "note_id": note["id"],
                "source_revision_id": revision["id"],
                "target_note_id": target["id"],
            },
            db_settings,
        )
        update_status(request["id"], "succeeded", target_note_id=target["id"], settings=db_settings)
        job = create_export_job(scope="note-id", note_id=target["id"], settings=db_settings)
        update_export_job(job["id"], status="succeeded", content_commit_sha=f"commit-{index}", settings=db_settings)

    status = get_web_trial_status(db_settings)

    assert len(direct_notes) == 4
    assert status["criteria"]["web_notes"] == {"count": 9, "required": 5, "met": True}
    assert status["criteria"]["processed_notes"] == {"count": 3, "required": 3, "met": True}
    assert status["criteria"]["exported_source_notes"] == {"count": 3, "required": 3, "met": True}
    assert status["criteria"]["feedback"] == {"count": 0, "required": 1, "met": False}
    assert status["ready_for_recommendation"] is False

    create_web_trial_feedback({"outcome": "simpler", "note": "Web workflow is simpler."}, db_settings)
    final_status = get_web_trial_status(db_settings)

    assert final_status["criteria"]["web_notes"] == {"count": 9, "required": 5, "met": True}
    assert final_status["criteria"]["feedback"] == {"count": 1, "required": 1, "met": True}
    assert final_status["ready_for_recommendation"] is True
    assert final_status["latest_feedback"]["outcome"] == "simpler"


def test_web_trial_status_api_requires_admin_scope(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        assert client.get("/api/trial/web-service/status").status_code == 401
        assert client.get(
            "/api/trial/web-service/status",
            headers={"Authorization": "Bearer plugin-token"},
        ).status_code == 401

        status = client.get(
            "/api/trial/web-service/status",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert status.status_code == 200
        assert status.json()["trial"] == "w7-web-service"

        feedback = client.post(
            "/api/trial/web-service/feedback",
            headers={"Authorization": "Bearer admin-token"},
            json={"outcome": "unclear", "note": "Needs more use."},
        )
        assert feedback.status_code == 200
        assert feedback.json()["kind"] == "log"
        assert feedback.json()["metadata"]["feedback_type"] == "w7-web-trial"

        invalid = client.post(
            "/api/trial/web-service/feedback",
            headers={"Authorization": "Bearer admin-token"},
            json={"outcome": "bad"},
        )
        assert invalid.status_code == 422
    finally:
        app.dependency_overrides.clear()
