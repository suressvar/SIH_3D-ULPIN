"""Original objects are immutable and private; local storage is development-only."""

import hashlib
import io
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.config import Config

from app.config import get_settings


def put_bytes(content: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(content).hexdigest()
    key = f"sources/{uuid4()}/{digest}"
    settings = get_settings()
    if settings.storage_backend == "r2":
        r2().put_object(
            Bucket=settings.r2_bucket,
            Key=key,
            Body=content,
            ContentType="application/octet-stream",
        )
    else:
        path = local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as out:
            out.write(content)
    return key, digest


def local_path(key: str) -> Path:
    root = get_settings().storage_root.resolve()
    target = (root / key).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Invalid object key")
    return target


def r2():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
    )


def read_bytes(key: str) -> bytes:
    settings = get_settings()
    if settings.storage_backend == "r2":
        with r2().get_object(Bucket=settings.r2_bucket, Key=key)["Body"] as body:
            return body.read(settings.max_upload_bytes + 1)
    return local_path(key).read_bytes()


def download_stream(key: str):
    return io.BytesIO(read_bytes(key))
