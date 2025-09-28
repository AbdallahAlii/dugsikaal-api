# src/common/security/passwords.py

import bcrypt
from typing import Optional

# No need to import legacy encryption anymore
# from .encryption import decrypt_password as legacy_decrypt

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def is_bcrypt_hash(stored: Optional[str]) -> bool:
    """Return True if the stored string looks like a bcrypt hash."""
    return isinstance(stored, str) and stored.startswith(_BCRYPT_PREFIXES)


def hash_password(plain: str, *, rounds: Optional[int] = None) -> str:
    """
    Hash plaintext using bcrypt.
    - rounds: optional cost factor (e.g., 12). If None, bcrypt's default is used.
    """
    if not plain:
        raise ValueError("Password cannot be empty.")
    salt = bcrypt.gensalt(rounds) if isinstance(rounds, int) else bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, stored: Optional[str]) -> bool:
    """
    Verifies a plaintext password against a stored bcrypt hash.

    Returns:
        bool: True if the password matches, else False.
    """
    if not stored or not is_bcrypt_hash(stored):
        return False

    try:
        return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
    except Exception:
        # Fails safely if the hash is corrupted or malformed.
        return False