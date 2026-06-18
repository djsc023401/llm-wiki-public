from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import mimetypes
from pathlib import Path
import re
import uuid

import boto3

from .config import Settings, load_settings


def _client(settings: Settings):
    if not settings.s3_endpoint or not settings.s3_access_key_id or not settings.s3_secret_access_key:
        raise RuntimeError("S3 configuration is incomplete")
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )


def safe_name(name: str) -> str:
    stem = Path(name).name.lower()
    stem = re.sub(r"[^a-z0-9._-]+", "-", stem).strip("-")
    return stem or "attachment.bin"


def object_key(prefix: str, file_name: str) -> str:
    now = datetime.now(timezone.utc)
    return f"{prefix.strip('/')}/{now:%Y/%m/%d}/{uuid.uuid4().hex}-{safe_name(file_name)}"


def upload_bytes(
    data: bytes,
    *,
    file_name: str,
    content_type: str | None = None,
    prefix: str = "raw",
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    key = object_key(prefix, file_name)
    sha256 = hashlib.sha256(data).hexdigest()
    final_content_type = content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    _client(resolved).put_object(
        Bucket=resolved.s3_bucket,
        Key=key,
        Body=data,
        ContentType=final_content_type,
        Metadata={"sha256": sha256},
    )
    return {
        "id": f"att_{uuid.uuid4().hex}",
        "bucket": resolved.s3_bucket,
        "object_key": key,
        "object_ref": f"s3://{resolved.s3_bucket}/{key}",
        "file_name": file_name,
        "content_type": final_content_type,
        "size_bytes": len(data),
        "sha256": sha256,
    }


def head_object(key: str, settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    response = _client(resolved).head_object(Bucket=resolved.s3_bucket, Key=key)
    metadata = response.get("Metadata") or {}
    return {
        "bucket": resolved.s3_bucket,
        "object_key": key,
        "object_ref": f"s3://{resolved.s3_bucket}/{key}",
        "content_type": response.get("ContentType"),
        "size_bytes": response.get("ContentLength"),
        "sha256": metadata.get("sha256"),
        "etag": (response.get("ETag") or "").strip('"') or None,
        "last_modified": response.get("LastModified"),
    }


def get_object_bytes(key: str, settings: Settings | None = None) -> tuple[bytes, dict]:
    resolved = settings or load_settings()
    response = _client(resolved).get_object(Bucket=resolved.s3_bucket, Key=key)
    data = response["Body"].read()
    metadata = response.get("Metadata") or {}
    return data, {
        "bucket": resolved.s3_bucket,
        "object_key": key,
        "object_ref": f"s3://{resolved.s3_bucket}/{key}",
        "content_type": response.get("ContentType"),
        "size_bytes": len(data),
        "sha256": metadata.get("sha256"),
        "etag": (response.get("ETag") or "").strip('"') or None,
        "last_modified": response.get("LastModified"),
    }
