# src/common/encryption.py

import random
from typing import Optional
from cryptography.fernet import InvalidToken
# Import the single Fernet instance configured from your .env
from config.settings import FERNET_INSTANCE


def generate_password() -> str:
    """
    Generate an 8-digit numeric password.
    """
    return ''.join(random.choices('0123456789', k=8))


# -------- Bytes APIs (use these for files/media) --------

def encrypt_bytes(data: bytes) -> bytes:
    """
    Encrypt raw bytes -> ciphertext bytes (Fernet token).
    """
    if data is None:
        raise ValueError("encrypt_bytes: data cannot be None")
    return FERNET_INSTANCE.encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    """
    Decrypt ciphertext bytes (Fernet token) -> raw bytes.
    Raises InvalidToken if the ciphertext or key is wrong.
    """
    if token is None:
        raise ValueError("decrypt_bytes: token cannot be None")
    return FERNET_INSTANCE.decrypt(token)


# -------- Text helpers (optional, convenient) --------

def encrypt_text(text: str, encoding: str = "utf-8") -> bytes:
    """
    Encrypt a text string and return ciphertext bytes.
    """
    if text is None:
        raise ValueError("encrypt_text: text cannot be None")
    return encrypt_bytes(text.encode(encoding))


def decrypt_text(token: bytes, encoding: str = "utf-8") -> str:
    """
    Decrypt ciphertext bytes and return a decoded string.
    """
    if token is None:
        raise ValueError("decrypt_text: token cannot be None")
    return decrypt_bytes(token).decode(encoding)

# Removed password-specific Fernet functions to avoid confusion.
# `encrypt_password` and `decrypt_password` are no longer needed here.