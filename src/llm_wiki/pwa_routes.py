from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .branding import app_icon_png, app_icon_svg, app_manifest, service_worker_js


router = APIRouter()


@router.get("/manifest.webmanifest")
def web_app_manifest() -> Response:
    return Response(app_manifest(), media_type="application/manifest+json")


@router.get("/favicon.svg")
def favicon_svg() -> Response:
    return Response(app_icon_svg(), media_type="image/svg+xml")


@router.get("/icons/app-icon-{size}.png")
def web_app_icon(size: int) -> Response:
    try:
        content = app_icon_png(size)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="icon_not_found") from exc
    return Response(
        content,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/sw.js")
def web_service_worker() -> Response:
    return Response(
        service_worker_js(),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )
