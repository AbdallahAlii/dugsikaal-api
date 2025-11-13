# app/common/media/service.py
from __future__ import annotations

import io
import os
import time
import uuid
from contextlib import contextmanager
from typing import Optional
from werkzeug.datastructures import FileStorage

from app.application_media.storage import get_backend
from app.application_media.utils import validate_upload, sanitize_segment
from app.common.security.encryption import encrypt_bytes, decrypt_bytes
from config.media_config import settings

_backend = get_backend()

def _now_ts() -> int:
    return int(time.time())

def _ext_from(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()

def _imports_key(prefix: str, filename: str, *, deterministic: bool = False) -> str:
    """
    Build a sanitized key under imports/ prefix.
    deterministic=True => stable key for same filename (rarely desirable for uploads)
    """
    base = sanitize_segment(prefix.strip("/"))
    fname = sanitize_segment(filename or "file")
    if deterministic:
        key = f"imports/{base}/{fname}.enc"
    else:
        # random suffix to allow multiple uploads with same filename
        rand = uuid.uuid4().hex[:10]
        key = f"imports/{base}/{_now_ts()}_{rand}_{fname}.enc"
    return key

def save_encrypted_bytes(content: bytes, filename: str, *, key_prefix: str = "uploads") -> str:
    """
    Encrypts arbitrary bytes and uploads via configured backend.
    Returns the storage key.
    """
    ok, err = validate_upload(filename, len(content))
    if not ok:
        raise ValueError(err or "Invalid upload")

    ciphertext = encrypt_bytes(content)
    key = _imports_key(key_prefix, filename, deterministic=False)
    _backend.upload(key, ciphertext, content_type="application/octet-stream")
    return key

def save_encrypted_file(file: FileStorage, *, key_prefix: str = "uploads") -> str:
    """
    Reads a Flask FileStorage, encrypts its content, and stores it.
    Returns the storage key.
    """
    if not file:
        raise ValueError("No file")
    data = file.read() or b""
    filename = file.filename or "upload"
    return save_encrypted_bytes(data, filename, key_prefix=key_prefix)

@contextmanager
def open_encrypted_stream(key: str):
    """
    Context manager yielding a BytesIO of the **decrypted** content for a stored object.
    Usage:
        with open_encrypted_stream(key) as f:
            content = f.read()
    """
    blob = _backend.download(key)
    raw = decrypt_bytes(blob)
    buf = io.BytesIO(raw)
    try:
        yield buf
    finally:
        try:
            buf.close()
        except Exception:
            pass

def generate_presigned_download_url(key: str, *, ttl: Optional[int] = None) -> str:
    """
    Returns a signed URL suitable for direct download. LOCAL backend returns a public URL.
    """
    return _backend.signed_url(key, ttl or settings.S3_SIGNED_URL_TTL)
