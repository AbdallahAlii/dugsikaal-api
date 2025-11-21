# application_data_import/runner/jobs.py
from __future__ import annotations
from typing import Any
import os

from ..runner.pipeline import run_import
from config.redis_config import get_redis_raw


def enqueue_import_job(data_import_id: int) -> Any:
    """
    Enqueue a data-import job.

    - On Windows (os.name == "nt"): run synchronously (inline) because RQ's default
      worker uses os.fork(), which is not available on Windows.
    - On other platforms: try to enqueue to RQ "data-imports" queue; if that fails,
      fall back to inline execution.

    Returns an object with an `id` attribute for compatibility with existing code.
    """

    # 🔹 Windows: always run inline to avoid os.fork() issues.
    if os.name == "nt":
        class _InlineJob:
            id = "inline"

        # Run import immediately in the current process
        run_import(data_import_id)
        return _InlineJob()

    # 🔹 Non-Windows: use RQ queue, with inline fallback
    try:
        from rq import Queue
        q = Queue("data-imports", connection=get_redis_raw())
        job = q.enqueue(run_import, data_import_id, job_timeout=60 * 60)
        return job
    except Exception:
        # Fallback: run inline (still OK for dev / resilience)
        class _InlineJob:
            id = "inline"

        run_import(data_import_id)
        return _InlineJob()
