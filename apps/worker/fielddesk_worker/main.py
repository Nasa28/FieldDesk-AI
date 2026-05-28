from __future__ import annotations

import signal
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import structlog

from fielddesk_worker.config import load_settings
from fielddesk_worker.db import init_pool
from fielddesk_worker.jobs.queue import process_one

log = structlog.get_logger()
_running = True


def _handle_signal(signum: int, _frame: Any) -> None:
    global _running
    log.info("worker_signal_received", signum=signum)
    _running = False


def run() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    settings = load_settings()
    log.info(
        "worker_starting",
        poll_interval=settings.poll_interval_seconds,
        max_retries=settings.max_retries,
        max_concurrent_jobs=settings.max_concurrent_jobs,
    )

    max_workers = max(1, int(settings.max_concurrent_jobs))
    init_pool(settings.database_url, max_size=max(8, max_workers * 2 + 2))

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while _running:
            futures = [executor.submit(process_one) for _ in range(max_workers)]
            processed = 0
            for future in as_completed(futures):
                try:
                    processed += future.result()
                except Exception as exc:  # noqa: BLE001
                    log.error("worker_loop_error", error=str(exc), error_class=type(exc).__name__)
            if processed == 0:
                time.sleep(settings.poll_interval_seconds)

    log.info("worker_stopped")


if __name__ == "__main__":
    run()


__all__ = ["run"]
