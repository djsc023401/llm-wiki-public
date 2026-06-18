from __future__ import annotations

from collections.abc import Callable
from fastapi import APIRouter, Depends, HTTPException

from .config import Settings
from .trial_status import create_web_trial_feedback, get_web_trial_status


def create_trial_router(
    admin_dependency: Callable,
    settings_dependency: Callable[[], Settings],
    validation_detail: Callable[[ValueError], str],
) -> APIRouter:
    router = APIRouter(prefix="/api/trial", dependencies=[Depends(admin_dependency)])

    @router.get("/web-service/status")
    def api_web_trial_status(settings: Settings = Depends(settings_dependency)) -> dict:
        return get_web_trial_status(settings)

    @router.post("/web-service/feedback")
    def api_web_trial_feedback(
        payload: dict,
        settings: Settings = Depends(settings_dependency),
    ) -> dict:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="invalid_trial_feedback_payload")
        try:
            return create_web_trial_feedback(payload, settings, created_by="web-ui")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc

    return router
