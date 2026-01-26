
# application_data_import/runner/jobs.py
from __future__ import annotations
from typing import Any
import os

from ..runner.pipeline import run_import
from config.redis_config import get_redis_raw


def enqueue_import_job(data_import_id: int, only_failed: bool = False) -> Any:
    """
    Enqueue a data-import job.

    - On Windows: run synchronously (inline).
    - On other platforms: enqueue to RQ "data-imports" queue.
    - `only_failed=True` means "retry failed rows only".
    """

    if os.name == "nt":
        class _InlineJob:
            id = "inline"

        # Run import immediately in the current process
        run_import(data_import_id, only_failed=only_failed)
        return _InlineJob()

    try:
        from rq import Queue
        q = Queue("data-imports", connection=get_redis_raw())
        job = q.enqueue(run_import, data_import_id, only_failed, job_timeout=60 * 60)
        return job
    except Exception:
        class _InlineJob:
            id = "inline"

        run_import(data_import_id, only_failed=only_failed)
        return _InlineJob()
