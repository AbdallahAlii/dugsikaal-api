# application_accounting/engine/errors.py
from __future__ import annotations

class PostingValidationError(Exception):
    """Business validation failed while preparing accounting posting."""

class IdempotencyError(Exception):
    """Duplicate posting attempt for the same document/action."""

class AccountNotFoundError(Exception):
    """Required account not found or inactive in Chart of Accounts."""

class FiscalYearClosedError(Exception):
    """Posting date falls outside an open fiscal year."""

class TemplateNotFoundError(Exception):
    """GL template not found for the requested company/doctype/mode."""
