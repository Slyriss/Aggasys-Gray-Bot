from __future__ import annotations


DEFAULT_JOB_FAILURE_LIMIT = 3


def should_pause_failed_job(current_failures: int, failure_limit: int = DEFAULT_JOB_FAILURE_LIMIT) -> bool:
    if failure_limit < 1:
        failure_limit = 1
    return current_failures + 1 >= failure_limit
