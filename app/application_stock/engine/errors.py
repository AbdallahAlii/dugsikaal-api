# stock/engine/errors.py
class StockValidationError(Exception):
    """Business/field validation failed (qty/rate/date/warehouse)."""


class StockOperationError(Exception):
    """SLE write / Bin derive / Handler build-intent failed."""


class ReplayError(Exception):
    """Repost/replay pipeline failed."""


class LockError(Exception):
    """Concurrency/advisory lock acquisition failed."""
