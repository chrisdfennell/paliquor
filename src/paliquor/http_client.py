"""A deliberately polite HTTP client for catalog (product-page) fetches.

Design goals, in priority order:
  1. Be a good citizen: one honest identity, low rate, cache aggressively.
  2. Be resilient: retry transient errors with backoff.
  3. Be cheap: never re-fetch a page we already have within its TTL.

This client is only used for the publicly-served product pages (which return
200 to a normal client). The Akamai-gated JSON API is intentionally NOT used
here; per-store inventory goes through a real browser (see inventory.py).
"""
from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import CACHE_DIR, get_settings

# Paths disallowed by the site's robots.txt. We refuse to fetch these.
ROBOTS_DISALLOW = (
    "/cart", "/checkout", "/profile", "/searchresults",
    "/confirmation", "/wishlist", "/wishlist_settings",
)


class RobotsDisallowed(Exception):
    """Raised when a URL path is disallowed by robots.txt."""


def _is_disallowed(url: str) -> bool:
    path = urlparse(url).path.lower()
    # robots lists both bare and /en/ prefixed variants; check both shapes.
    return any(path == d or path.startswith(d + "/") or path.startswith("/en" + d)
               for d in ROBOTS_DISALLOW)


class PoliteClient:
    """Throttled, caching, self-identifying HTTP client (singleton-friendly)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._client = httpx.Client(
            headers={
                "User-Agent": self.settings.user_agent,
                # Realistic Accept headers — what a normal browser sends.
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=self.settings.request_timeout,
            follow_redirects=True,
        )

    # -- caching ---------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:24]
        return CACHE_DIR / f"{digest}.html"

    def _cached(self, url: str, ttl: timedelta) -> str | None:
        p = self._cache_path(url)
        if not p.exists():
            return None
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(
            p.stat().st_mtime, tz=timezone.utc
        )
        return p.read_text(encoding="utf-8") if age < ttl else None

    # -- throttle --------------------------------------------------------
    def _throttle(self) -> None:
        with self._lock:
            wait = self.settings.min_request_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    # -- fetch -----------------------------------------------------------
    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _get(self, url: str) -> str:
        self._throttle()
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.text

    def get(self, url: str, ttl: timedelta | None = None, use_cache: bool = True) -> str:
        """Fetch ``url`` as text, honoring robots, cache, and throttle."""
        if _is_disallowed(url):
            raise RobotsDisallowed(url)
        ttl = ttl or timedelta(hours=self.settings.catalog_ttl_hours)
        if use_cache:
            hit = self._cached(url, ttl)
            if hit is not None:
                return hit
        body = self._get(url)
        self._cache_path(url).write_text(body, encoding="utf-8")
        return body

    def close(self) -> None:
        self._client.close()


_client: PoliteClient | None = None


def client() -> PoliteClient:
    global _client
    if _client is None:
        _client = PoliteClient()
    return _client
