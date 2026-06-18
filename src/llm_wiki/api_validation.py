from __future__ import annotations

from pathlib import PurePosixPath
import re

from fastapi import HTTPException

from .config import Settings


VALID_OPERATIONS = {"ingest"}
VALID_SENSITIVITIES = {"private", "internal", "public"}
REQUEST_ID_RE = re.compile(r"^req_[A-Za-z0-9_.-]{8,128}$")
HEX_RE = re.compile(r"^[a-fA-F0-9]+$")


class ValidationError(ValueError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def is_valid_request_id(value: str) -> bool:
    return bool(REQUEST_ID_RE.fullmatch(value))


def validate_request_payload(payload: dict, settings: Settings) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("invalid_request_payload")
    validated = dict(payload)
    request_id = validated.get("id")
    if request_id is not None and not is_valid_request_id(str(request_id)):
        raise ValidationError("invalid_request_id")
    operation = validated.get("operation", "ingest")
    if operation not in VALID_OPERATIONS:
        raise ValidationError("invalid_operation")
    sensitivity = validated.get("sensitivity", "private")
    if sensitivity not in VALID_SENSITIVITIES:
        raise ValidationError("invalid_sensitivity")
    repo_full_name = validated.get("repo_full_name", settings.repo_full_name)
    if repo_full_name != settings.repo_full_name:
        raise ValidationError("repo_full_name_not_allowed")
    branch = validated.get("branch", "main")
    if branch != "main":
        raise ValidationError("branch_not_allowed")
    validated["operation"] = operation
    validated["sensitivity"] = sensitivity
    validated["repo_full_name"] = repo_full_name
    validated["branch"] = branch
    validated["file_path"] = validate_vault_markdown_path(validated.get("file_path"))
    _validate_optional_hex(validated.get("content_hash"), "invalid_content_hash", expected_len=64)
    _validate_optional_hex(validated.get("commit_sha"), "invalid_commit_sha", min_len=7, max_len=64)
    snapshot = validated.get("content_snapshot")
    if snapshot is not None:
        if not isinstance(snapshot, str):
            raise ValidationError("invalid_content_snapshot")
        if len(snapshot.encode("utf-8")) > settings.max_request_snapshot_bytes:
            raise ValidationError("content_snapshot_too_large")
    return validated


def validate_vault_markdown_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("file_path_required")
    path = value.strip()
    if "\\" in path or path.startswith("/") or path.startswith("~"):
        raise ValidationError("invalid_file_path")
    if len(path.encode("utf-8")) > 512:
        raise ValidationError("file_path_too_long")
    pure = PurePosixPath(path)
    if pure.is_absolute():
        raise ValidationError("invalid_file_path")
    parts = pure.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValidationError("invalid_file_path")
    if any(part.startswith(".") for part in parts):
        raise ValidationError("file_path_not_allowed")
    if parts[0] == "sources":
        raise ValidationError("file_path_not_allowed")
    normalized = pure.as_posix()
    if not normalized.endswith(".md"):
        raise ValidationError("file_path_must_be_markdown")
    return normalized


def validate_attachment_metadata(file_name: object, content_type: object, data: bytes, settings: Settings) -> tuple[str, str]:
    if len(data) > settings.max_attachment_bytes:
        raise HTTPException(status_code=413, detail="attachment_too_large")
    if not isinstance(file_name, str) or not file_name.strip():
        raise HTTPException(status_code=422, detail="invalid_attachment_file_name")
    name = file_name.strip()
    if "/" in name or "\\" in name or name in {".", ".."} or any(ord(char) < 32 for char in name):
        raise HTTPException(status_code=422, detail="invalid_attachment_file_name")
    if len(name.encode("utf-8")) > 255:
        raise HTTPException(status_code=422, detail="attachment_file_name_too_long")
    media_type = content_type if isinstance(content_type, str) and content_type.strip() else "application/octet-stream"
    media_type = media_type.strip()
    if len(media_type) > 100 or any(ord(char) < 32 for char in media_type):
        raise HTTPException(status_code=422, detail="invalid_attachment_content_type")
    return name, media_type


def validation_detail(exc: ValueError) -> str:
    return str(exc) or "validation_error"


def _validate_optional_hex(
    value: object,
    detail: str,
    *,
    expected_len: int | None = None,
    min_len: int | None = None,
    max_len: int | None = None,
) -> None:
    if value is None or value == "":
        return
    if not isinstance(value, str) or not HEX_RE.fullmatch(value):
        raise ValidationError(detail)
    if expected_len is not None and len(value) != expected_len:
        raise ValidationError(detail)
    if min_len is not None and len(value) < min_len:
        raise ValidationError(detail)
    if max_len is not None and len(value) > max_len:
        raise ValidationError(detail)
