# app/common/media/encrypted_media.py
from typing import Optional, Tuple
import imghdr
from config.media_config import settings
from .storage import get_backend
from .utils import validate_upload, sanitize_segment
from app.common.security.encryption import encrypt_bytes, decrypt_bytes

_backend = get_backend()

def _deterministic_key(prefix: str, item_id: int | str) -> str:
    """
    Deterministic path so updates overwrite the same object (no history kept).
    """
    pfx = sanitize_segment(prefix)
    return f"{pfx}/{item_id}/image.enc"

def store_or_replace_encrypted_image(
    *,
    file_bytes: bytes,
    filename: str,
    key_prefix: str,
    item_id: int | str,
    content_type: Optional[str] = None,
    old_img_key: Optional[str] = None,
) -> str:
    """
    Encrypts and uploads image bytes, ensuring only one image per record.
    Returns the img_key to persist in model.img_key.
    """
    ok, err = validate_upload(filename, len(file_bytes))
    if not ok:
        raise ValueError(err or "Invalid upload")

    ciphertext = encrypt_bytes(file_bytes)
    new_key = _deterministic_key(key_prefix, item_id)
    _backend.upload(new_key, ciphertext, content_type or "application/octet-stream")

    if old_img_key and old_img_key != new_key:
        try:
            _backend.delete(old_img_key)
        except Exception:
            pass
    return new_key

def _sniff_image_mime(raw: bytes) -> str:
    kind = imghdr.what(None, raw)
    return {
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
    }.get(kind or "", "application/octet-stream")

def download_and_decrypt(img_key: str) -> Tuple[bytes, str]:
    """
    Downloads ciphertext and returns (raw_bytes, mime) after decryption.
    """
    data = _backend.download(img_key)
    raw = decrypt_bytes(data)
    return raw, _sniff_image_mime(raw)

def image_url_from_key(img_key: str, *, external_base: Optional[str] = None) -> str:
    """
    Returns a URL that points to our decryption endpoint for a specific key.
    """
    base = (external_base or "").rstrip("/")
    # This URL will be used in HTML <img src="..."> tags.
    return f"{base}/api/media/img/{img_key}"