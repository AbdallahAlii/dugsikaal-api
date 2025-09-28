# src/common/security/password_rules.py
from typing import Optional
from werkzeug.exceptions import UnprocessableEntity

_ASC = "0123456789"
_DESC = "9876543210"


def _is_seq_numeric(pw: str) -> bool:
    """
    True if pw is a simple ascending/descending numeric sequence (len >= 6).
    Examples that return True: 123456, 0123456, 987654, 9876543210
    """
    if not pw.isdigit() or len(pw) < 6:
        return False

    L = len(pw)
    for i in range(len(_ASC) - L + 1):
        if pw == _ASC[i : i + L]:
            return True
    for i in range(len(_DESC) - L + 1):
        if pw == _DESC[i : i + L]:
            return True
    return False


def _is_all_same_char(pw: str) -> bool:
    """True if pw has length >= 6 and all chars are the same (e.g., 000000, aaaaaa)."""
    return len(pw) >= 6 and len(set(pw)) == 1


def check_password_rules(pw: str) -> Optional[str]:
    """
    Return None if OK; otherwise return a FRIENDLY error message string.

    Rules:
      - at least 6 chars
      - if all digits: must NOT be a simple numeric sequence (asc/desc) or all same digit
        (allows 582693, blocks 123456, 0123456789, 987654, 000000, etc.)
    """
    if not pw or len(pw) < 6:
        return "Password must be at least 6 characters."

    if pw.isdigit():
        if _is_seq_numeric(pw):
            return "Please avoid simple numeric sequences like 123456 or 987654."
        if _is_all_same_char(pw):
            return "Password cannot be a single repeated digit (e.g., 000000)."

    # (optional) add more rules later if you want
    return None


def ensure_password_ok(pw: str) -> None:
    """
    Service-layer guard for Flask apps.
    Raises a 422 Unprocessable Entity with a friendly message if invalid.

    Usage:
        ensure_password_ok(password)
        # if invalid -> raises UnprocessableEntity (422)
    """
    msg = check_password_rules(pw)
    if msg:
        # Flask will convert this into a 422 response; customize via error handlers if needed.
        raise UnprocessableEntity(description=msg)
