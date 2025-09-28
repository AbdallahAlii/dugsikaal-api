# app/common/media/storage.py
import os
import logging
from typing import Optional, Protocol, Tuple

from config.media_config import settings

logger = logging.getLogger(__name__)

# Optional S3 deps
try:
    import boto3
    from botocore.client import Config as BotoConfig
    from botocore.exceptions import NoCredentialsError
except Exception:
    boto3 = None
    BotoConfig = None
    NoCredentialsError = Exception

class StorageBackend(Protocol):
    def upload(self, key: str, data: bytes, content_type: Optional[str]) -> None: ...
    def download(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def signed_url(self, key: str, ttl: int) -> str: ...
    def get_public_url(self, key: str) -> Optional[str]: ...

class S3Backend:
    def __init__(self):
        if not boto3:
            raise RuntimeError("boto3 not installed; cannot use S3 backend")
        cfg = BotoConfig(signature_version="s3v4") if BotoConfig else None
        self._cli = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            region_name=settings.S3_REGION or None,
            aws_access_key_id=settings.S3_ACCESS_KEY or None,
            aws_secret_access_key=settings.S3_SECRET_KEY or None,
            config=cfg,
        )
        self._bucket = settings.S3_BUCKET

    def upload(self, key: str, data: bytes, content_type: Optional[str]) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._cli.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

    def download(self, key: str) -> bytes:
        obj = self._cli.get_object(Bucket=self._bucket, Key=key)
        return obj["Body"].read()

    def delete(self, key: str) -> None:
        self._cli.delete_object(Bucket=self._bucket, Key=key)

    def signed_url(self, key: str, ttl: int) -> str:
        return self._cli.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=ttl or settings.S3_SIGNED_URL_TTL,
        )

    def get_public_url(self, key: str) -> Optional[str]:
        if settings.S3_PUBLIC_BASE:
            return f"{settings.S3_PUBLIC_BASE.rstrip('/')}/{key}"
        return None

class LocalBackend:
    def __init__(self):
        os.makedirs(settings.LOCAL_MEDIA_ROOT, exist_ok=True)

    def _path(self, key: str) -> str:
        # normalize and ensure we stay under the media root
        root = os.path.abspath(settings.LOCAL_MEDIA_ROOT)
        p = os.path.abspath(os.path.join(root, key))
        if not p.startswith(root + os.sep) and p != root:
            raise FileNotFoundError("Invalid media key path")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def upload(self, key: str, data: bytes, content_type: Optional[str]) -> None:
        with open(self._path(key), "wb") as f:
            f.write(data)

    def download(self, key: str) -> bytes:
        with open(self._path(key), "rb") as f:
            return f.read()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if os.path.exists(p):
            os.remove(p)

    def signed_url(self, key: str, ttl: int) -> str:
        return self.get_public_url(key) or f"{settings.LOCAL_PUBLIC_BASE.rstrip('/')}/{key}"

    def get_public_url(self, key: str) -> Optional[str]:
        return f"{settings.LOCAL_PUBLIC_BASE.rstrip('/')}/{key}"

_backend_singleton: Optional[StorageBackend] = None

def _can_use_s3() -> bool:
    if (settings.MEDIA_BACKEND or "").lower() != "s3":
        return False
    if not boto3:
        return False
    if settings.S3_ACCESS_KEY and settings.S3_SECRET_KEY:
        return True
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return True
    if os.environ.get("AWS_PROFILE"):
        return True
    return False

def get_backend() -> StorageBackend:
    global _backend_singleton
    if _backend_singleton:
        return _backend_singleton
    if _can_use_s3():
        try:
            _backend_singleton = S3Backend()
            logger.info("Media backend: S3")
            return _backend_singleton
        except Exception as e:
            logger.warning("S3 backend requested but unavailable (%s). Falling back to local.", e)
    _backend_singleton = LocalBackend()
    logger.info("Media backend: LOCAL")
    return _backend_singleton