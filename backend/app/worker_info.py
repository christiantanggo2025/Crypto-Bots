"""
In-memory metadata for the lab background worker (single Railway/container process).

Closing your laptop does NOT affect this — only this server process does.
"""
from __future__ import annotations

from datetime import datetime

process_boot_at: datetime | None = None
scheduler_interval_seconds: int | None = None
lab_worker_disabled: bool = False


def mark_worker_boot(*, interval_seconds: int, disabled: bool = False) -> None:
    global process_boot_at, scheduler_interval_seconds, lab_worker_disabled
    from app.time_toronto import utc_now

    process_boot_at = utc_now()
    scheduler_interval_seconds = interval_seconds
    lab_worker_disabled = disabled
