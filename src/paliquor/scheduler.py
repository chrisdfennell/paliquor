"""In-process daily catalog refresh.

When ``SCHEDULER_ENABLED=true``, the API process runs a background task that
re-scrapes the catalog once a day at ``REFRESH_HOUR`` (local time). This is what
makes price history accrue and restock / price-drop alerts fire on their own.

The scrape runs in a worker thread (``asyncio.to_thread``) so it never blocks
the web server, and it reuses the polite, cached HTTP client — so a nightly run
is cheap (mostly cache hits) and well-behaved.

For heavier/production setups, prefer an OS scheduler (Task Scheduler / cron)
calling ``python -m paliquor.cli refresh-catalog`` — see scripts/refresh.ps1.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from .config import get_settings

log = logging.getLogger("paliquor.scheduler")


def _seconds_until(hour: int) -> float:
    now = datetime.now()
    nxt = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def _run_refresh() -> None:
    # Imported here so a failure in the scrape stack can't stop the API booting.
    from .scraper import refresh_catalog
    s = get_settings()
    cats = s.scheduled_categories
    log.info("scheduled refresh starting for categories %s", cats)
    stats = refresh_catalog(cats)
    log.info("scheduled refresh done: %s", stats)


async def _loop() -> None:
    s = get_settings()
    while True:
        wait = _seconds_until(s.refresh_hour)
        log.info("next scheduled refresh in %.1f h (at %02d:00 local)",
                 wait / 3600, s.refresh_hour)
        await asyncio.sleep(wait)
        try:
            await asyncio.to_thread(_run_refresh)
        except Exception as exc:  # never let one failure kill the scheduler
            log.warning("scheduled refresh failed: %s", exc)
        await asyncio.sleep(60)  # avoid double-firing within the same minute


_task: asyncio.Task | None = None


def start() -> None:
    global _task
    if not get_settings().scheduler_enabled:
        log.info("scheduler disabled (set SCHEDULER_ENABLED=true to enable)")
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
        log.info("nightly refresh scheduler started")


def stop() -> None:
    if _task and not _task.done():
        _task.cancel()
