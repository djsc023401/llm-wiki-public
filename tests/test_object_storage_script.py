from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_create_bucket_module():
    module_path = ROOT / "scripts" / "object_storage" / "create_bucket.py"
    spec = importlib.util.spec_from_file_location("create_bucket_script", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeS3Client:
    def __init__(self) -> None:
        self.head_buckets: list[str] = []
        self.put_keys: list[str] = []

    def head_bucket(self, *, Bucket: str) -> None:
        self.head_buckets.append(Bucket)

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        assert Bucket
        assert Body == b""
        self.put_keys.append(Key)


def test_create_bucket_uses_standard_s3_env_names(monkeypatch, capsys) -> None:
    module = _load_create_bucket_module()
    client = FakeS3Client()
    captured: dict = {}

    def fake_client(service_name: str, **kwargs):
        captured.update({"service_name": service_name, **kwargs})
        return client

    monkeypatch.setattr(module.boto3, "client", fake_client)
    monkeypatch.setenv("S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("S3_BUCKET", "standard-bucket")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "standard-access")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "standard-secret")
    monkeypatch.setenv("S3_REGION", "ap-northeast-2")

    assert module.main() == 0

    assert captured["service_name"] == "s3"
    assert captured["endpoint_url"] == "http://minio:9000"
    assert captured["aws_access_key_id"] == "standard-access"
    assert captured["aws_secret_access_key"] == "standard-secret"
    assert captured["region_name"] == "ap-northeast-2"
    assert client.head_buckets == ["standard-bucket"]
    assert client.put_keys == ["raw/.keep", "assets/.keep", "extracted/.keep", "archive/.keep"]
    assert "bucket_status=exists bucket=standard-bucket" in capsys.readouterr().out


def test_create_bucket_keeps_legacy_s3_env_aliases(monkeypatch) -> None:
    module = _load_create_bucket_module()
    client = FakeS3Client()
    captured: dict = {}

    def fake_client(service_name: str, **kwargs):
        captured.update({"service_name": service_name, **kwargs})
        return client

    monkeypatch.setattr(module.boto3, "client", fake_client)
    monkeypatch.setenv("S3_ENDPOINT", "https://s3.example.com")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setenv("S3_BUCKET_NAME", "legacy-bucket")
    monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.setenv("S3_ACCESS_KEY", "legacy-access")
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setenv("S3_SECRET_KEY", "legacy-secret")

    assert module.main() == 0

    assert captured["aws_access_key_id"] == "legacy-access"
    assert captured["aws_secret_access_key"] == "legacy-secret"
    assert captured["region_name"] == "us-east-1"
    assert client.head_buckets == ["legacy-bucket"]
