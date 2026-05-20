"""Shared Playwright browser context.

We drive a *real* Chromium. We deliberately keep its genuine browser
User-Agent: this is an actual browser executing the site's own JavaScript, not
a forged signature. Politeness comes from low concurrency, human-like pacing,
and caching — not from disguising what we are.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from playwright.sync_api import Browser, BrowserContext, sync_playwright

from .config import BASE_URL

# A modest, human-like pause (ms) used between navigations by callers.
HUMAN_PAUSE_MS = 1500


@contextmanager
def browser_context(headless: bool = True) -> Iterator[BrowserContext]:
    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="en-US",
            viewport={"width": 1366, "height": 900},
            base_url=BASE_URL,
        )
        # Be patient rather than aggressive.
        context.set_default_timeout(45_000)
        try:
            yield context
        finally:
            context.close()
            browser.close()
