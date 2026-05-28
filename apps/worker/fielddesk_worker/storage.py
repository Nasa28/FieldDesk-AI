from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from minio import Minio
from minio.error import S3Error

from fielddesk_worker.config import load_settings


def _strip_scheme(endpoint: str) -> str:
    endpoint = endpoint.strip()
    for prefix in ("http://", "https://"):
        if endpoint.startswith(prefix):
            endpoint = endpoint[len(prefix):]
    return endpoint.rstrip("/")


@lru_cache(maxsize=1)
def get_client() -> Minio:
    s = load_settings()
    if not s.s3_endpoint or not s.s3_access_key_id or not s.s3_secret_access_key:
        raise RuntimeError(
            "S3_ENDPOINT, S3_ACCESS_KEY_ID, and S3_SECRET_ACCESS_KEY must be set"
        )
    return Minio(
        endpoint=_strip_scheme(s.s3_endpoint),
        access_key=s.s3_access_key_id,
        secret_key=s.s3_secret_access_key,
        secure=s.s3_use_ssl,
        region=s.s3_region,
    )


@dataclass(frozen=True)
class ObjectInfo:
    exists: bool
    size: int = 0
    content_type: str | None = None
    etag: str | None = None


def stat_object(key: str) -> ObjectInfo:
    s = load_settings()
    try:
        info = get_client().stat_object(s.s3_bucket, key)
        etag = (getattr(info, "etag", None) or "").strip('"') or None
        return ObjectInfo(
            exists=True,
            size=int(info.size or 0),
            content_type=getattr(info, "content_type", None),
            etag=etag,
        )
    except S3Error as e:
        # NoSuchKey is the canonical "not found"; older MinIO returns generic.
        if e.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
            return ObjectInfo(exists=False)
        raise


def object_exists(key: str) -> bool:
    return stat_object(key).exists


def get_object_bytes(key: str) -> bytes:
    s = load_settings()
    response = get_client().get_object(s.s3_bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
