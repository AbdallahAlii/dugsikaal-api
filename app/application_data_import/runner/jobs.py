# application_data_import/runner/jobs.py
from __future__ import annotations

import os
from typing import Any

from ..runner.pipeline import run_import
from app.common.cache.redis_client import redis_raw


def enqueue_import_job(data_import_id: int, only_failed: bool = False) -> Any:
    """
    Enqueue a data-import job.

    - On Windows: run synchronously (inline).
    - On other platforms: enqueue to RQ "data-imports" queue.
    - `only_failed=True` means "retry failed rows only".
    """

    # Windows dev UX: run inline (no Redis/RQ needed)
    if os.name == "nt":
        class _InlineJob:
            id = "inline"

        run_import(data_import_id, only_failed=only_failed)
        return _InlineJob()

    # Linux/macOS: try RQ, fallback to inline if Redis/RQ not available
    try:
        from rq import Queue

        # rq expects a real redis-py client. SafeRedis exposes it via _client().
        # decode_responses=False is correct for rq.
        q = Queue("data-imports", connection=redis_raw._client())  # noqa: SLF001 (intentional internal access)
        job = q.enqueue(run_import, data_import_id, only_failed, job_timeout=60 * 60)
        return job

    except Exception:
        class _InlineJob:
            id = "inline"

        run_import(data_import_id, only_failed=only_failed)
        return _InlineJob()