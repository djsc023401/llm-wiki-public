#!/usr/bin/env python3
"""Create the llm-wiki object storage bucket and marker prefixes.

Required environment variables:
  S3_ENDPOINT
  S3_ACCESS_KEY_ID
  S3_SECRET_ACCESS_KEY

Optional environment variables:
  S3_BUCKET, defaults to llm-wiki
  S3_REGION, defaults to us-east-1

Legacy aliases:
  S3_ACCESS_KEY
  S3_SECRET_KEY
  S3_BUCKET_NAME
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


PREFIX_MARKERS = ("raw/.keep", "assets/.keep", "extracted/.keep", "archive/.keep")


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"missing_env={name}", file=sys.stderr)
        raise SystemExit(2)
    return value.strip()


def first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return None


def required_any(*names: str) -> str:
    value = first_env(*names)
    if value:
        return value
    print(f"missing_env={names[0]}", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    endpoint = required_env("S3_ENDPOINT")
    access_key = required_any("S3_ACCESS_KEY_ID", "S3_ACCESS_KEY")
    secret_key = required_any("S3_SECRET_ACCESS_KEY", "S3_SECRET_KEY")
    bucket = (first_env("S3_BUCKET", "S3_BUCKET_NAME") or "llm-wiki").strip()
    region = os.environ.get("S3_REGION", "us-east-1").strip()

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2}),
    )

    try:
        s3.head_bucket(Bucket=bucket)
        print(f"bucket_status=exists bucket={bucket}")
    except BotoCoreError as exc:
        print(f"bucket_status=endpoint_unreachable bucket={bucket} error={exc}", file=sys.stderr)
        return 1
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 404 or code in {"404", "NoSuchBucket", "NotFound"}:
            s3.create_bucket(Bucket=bucket)
            print(f"bucket_status=created bucket={bucket}")
        else:
            print(f"bucket_status=error bucket={bucket} code={code or status}", file=sys.stderr)
            return 1

    for key in PREFIX_MARKERS:
        s3.put_object(Bucket=bucket, Key=key, Body=b"")
        print(f"prefix_marker=ok key={key}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
