"""Rate limiting against a real Redis cache backend.

Every other test in this suite runs against ``LocMemCache``, which is
explicitly documented (``CacheRateLimitBackend``'s docstring) as correct
only *within one process* -- it can't prove the cross-process claim the
docs make about Redis. This module does, against Django's own
``django.core.cache.backends.redis.RedisCache`` (no third-party cache
library needed).

Skipped entirely -- not failed -- whenever Redis isn't available: no
``redis`` package installed (the common case for local development; it's
intentionally not a dependency of this package or its ``test`` extra), or
no server reachable at ``REDIS_URL``. CI provides both, via a ``redis``
service container and a one-off ``pip install redis`` in that job only --
see ``.github/workflows/test.yml``.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import pytest

redis = pytest.importorskip("redis", reason="redis package not installed")

from django_tenant_apikeys.ratelimit import CacheRateLimitBackend, check_rate_limit  # noqa: E402
from tests.models import Tenant, TenantAPIKey  # noqa: E402

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/1")


def _redis_reachable() -> bool:
    try:
        redis.Redis.from_url(_REDIS_URL, socket_connect_timeout=0.5).ping()
    except Exception:
        return False
    return True


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        not _redis_reachable(), reason=f"no Redis reachable at {_REDIS_URL}"
    ),
]

_REDIS_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": _REDIS_URL,
    }
}


@pytest.fixture(autouse=True)
def _redis_cache(settings: Any) -> None:
    # The `settings` fixture (pytest-django) reverts this after the test,
    # same effect as override_settings but usable on a plain pytest class --
    # override_settings itself only decorates Django's own TestCase classes.
    from django.core.cache import caches

    settings.CACHES = _REDIS_CACHE
    caches["default"].clear()
    yield
    caches["default"].clear()


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


class TestRedisBackedRateLimit:
    def test_does_not_warn_or_raise_at_construction(self) -> None:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            CacheRateLimitBackend()

    def test_enforces_the_configured_limit(self, tenant: Tenant) -> None:
        key = TenantAPIKey.generate_key(name="k", tenant=tenant, rate_limit=3)[0]
        results = [check_rate_limit(key).allowed for _ in range(4)]
        assert results == [True, True, True, False]

    def test_separate_keys_are_counted_independently(self, tenant: Tenant) -> None:
        key_a = TenantAPIKey.generate_key(name="a", tenant=tenant, rate_limit=1)[0]
        key_b = TenantAPIKey.generate_key(name="b", tenant=tenant, rate_limit=1)[0]
        assert check_rate_limit(key_a).allowed is True
        assert check_rate_limit(key_a).allowed is False
        assert check_rate_limit(key_b).allowed is True

    def test_counts_correctly_across_concurrent_threads(self, tenant: Tenant) -> None:
        # This is the test LocMemCache structurally cannot pass across
        # *processes* -- it's only meaningful against a real shared cache.
        # Threads stand in for separate worker processes sharing one Redis.
        key = TenantAPIKey.generate_key(name="k", tenant=tenant, rate_limit=50)[0]
        allowed: list[bool] = []
        lock = threading.Lock()

        def worker() -> None:
            result = check_rate_limit(key).allowed
            with lock:
                allowed.append(result)

        threads = [threading.Thread(target=worker) for _ in range(80)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert allowed.count(True) == 50
        assert allowed.count(False) == 30
