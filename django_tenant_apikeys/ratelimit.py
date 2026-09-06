"""Per-key rate limiting, shared by the DRF and Ninja integrations.

The default backend counts requests in Django's cache framework (whatever
``CACHES["default"]`` -- or ``TENANT_API_KEY_RATE_LIMIT_CACHE`` -- points
at). That's deliberately not Redis-only: it works out of the box with
LocMemCache, and transparently gets cross-process correctness for free if
the project's cache is already Memcached or a shared Redis. See
``CacheRateLimitBackend`` for the concurrency approach and its limits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from django.conf import settings
from django.core.cache import BaseCache
from django.core.cache import caches as _caches
from django.utils.module_loading import import_string

if TYPE_CHECKING:
    from .models import AbstractTenantAPIKey

__all__ = [
    "CacheRateLimitBackend",
    "RateLimitBackend",
    "RateLimitResult",
    "check_rate_limit",
    "get_rate_limit_backend",
]

_WINDOW_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 60 * 60,
    "day": 60 * 60 * 24,
}


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a rate-limit check. ``limit``/``remaining``/``reset_at``
    are ``None`` when the key has no ``rate_limit`` configured -- there's
    nothing meaningful to report, and no ``X-RateLimit-*`` headers should
    be sent for that request.

    ``reset_at`` is a Unix timestamp (seconds), matching the convention
    used by ``X-RateLimit-Reset`` in other APIs (e.g. GitHub's). ``retry_after``
    is seconds until that reset, for the standard ``Retry-After`` header --
    only set when ``allowed`` is False.
    """

    allowed: bool
    limit: int | None
    remaining: int | None
    reset_at: int | None
    retry_after: int | None


class RateLimitBackend(Protocol):
    """What a rate-limit storage backend needs to implement. Swap it via
    ``TENANT_API_KEY_RATE_LIMIT_BACKEND`` -- e.g. for a future Redis-backed
    sliding-window implementation -- without touching ``check_rate_limit()``
    or either framework integration."""

    def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Record one request against ``key`` and report whether it's
        within ``limit`` for a ``window_seconds``-long window."""
        ...


class CacheRateLimitBackend:
    """Fixed-window counter stored in a Django cache.

    Uses ``cache.add()`` (atomic set-if-absent) to seed the window's counter
    and ``cache.incr()`` (atomic increment) to count the request, rather
    than a get-then-set round trip -- two requests racing to initialize the
    same window can't both reset the count to 1, and two requests racing to
    increment it can't both read the same starting value and stomp on each
    other. Both operations are atomic *for the cache backend in use*: with
    the default LocMemCache that's only true within a single process, so
    multiple worker processes each enforce the limit independently rather
    than sharing one count. Point ``TENANT_API_KEY_RATE_LIMIT_CACHE`` (or
    ``CACHES["default"]``) at Memcached or a shared Redis for a limit that
    holds across processes -- the counting logic here doesn't change.

    Being a fixed window rather than a sliding one, a key can burst up to
    ~2x its limit across a window boundary (e.g. a full minute's quota just
    before :00, then another full minute's quota just after). That trade-off
    is deliberate: a sliding window needs to store a timestamp per request
    rather than a single counter, which is real complexity this default
    doesn't need to carry.
    """

    def __init__(self, cache: BaseCache | None = None) -> None:
        if cache is None:
            cache_alias = getattr(settings, "TENANT_API_KEY_RATE_LIMIT_CACHE", "default")
            cache = _caches[cache_alias]
        self.cache = cache

    def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.time()
        window_start = int(now // window_seconds) * window_seconds
        reset_at = window_start + window_seconds
        cache_key = f"{key}:{window_start}"

        self.cache.add(cache_key, 0, timeout=window_seconds)
        try:
            count = self.cache.incr(cache_key)
        except ValueError:
            # The key expired between add() and incr() -- the window rolled
            # over at exactly the wrong moment. Treat this request as the
            # first one in the new window rather than failing it outright.
            self.cache.add(cache_key, 1, timeout=window_seconds)
            count = 1

        allowed = count <= limit
        remaining = max(limit - count, 0)
        retry_after = int(reset_at - now) if not allowed else None
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after,
        )


def get_rate_limit_backend() -> RateLimitBackend:
    """Resolve ``TENANT_API_KEY_RATE_LIMIT_BACKEND`` (a dotted path to a
    zero-argument callable/class), defaulting to ``CacheRateLimitBackend``.
    Not memoized -- construction is cheap, and this keeps ``override_settings``
    in tests working without a cache-invalidation signal to wire up."""
    path = getattr(settings, "TENANT_API_KEY_RATE_LIMIT_BACKEND", None)
    if not path:
        return CacheRateLimitBackend()
    backend_cls: type[RateLimitBackend] = import_string(path)
    return backend_cls()


def check_rate_limit(api_key: AbstractTenantAPIKey) -> RateLimitResult:
    """Record one request against ``api_key`` and check it against its
    configured ``rate_limit``/``rate_limit_window``. Always ``allowed=True``
    with no other fields set if the key has no ``rate_limit`` configured.

    The cache key includes the concrete model's name alongside the key's
    pk, not just the pk -- two different concrete ``AbstractTenantAPIKey``
    subclasses (e.g. two tenant types in the same project) could otherwise
    collide on the same primary key value and share a counter that belongs
    to a different tenant's key entirely.
    """
    if api_key.rate_limit is None:
        return RateLimitResult(
            allowed=True, limit=None, remaining=None, reset_at=None, retry_after=None
        )
    window_seconds = _WINDOW_SECONDS[api_key.rate_limit_window]
    cache_key = f"tenant_api_key_ratelimit:{type(api_key).__name__}:{api_key.pk}"
    backend = get_rate_limit_backend()
    return backend.hit(cache_key, api_key.rate_limit, window_seconds)
