"""Tests for the per-key rate limiter: the cache-backed default backend,
check_rate_limit()'s integration with it, and backend pluggability."""

from __future__ import annotations

import threading
from unittest import mock

import pytest
from django.core.cache import cache, caches
from django.test import override_settings

from django_tenant_apikeys.ratelimit import (
    CacheRateLimitBackend,
    RateLimitResult,
    check_rate_limit,
    get_rate_limit_backend,
)
from tests.models import Tenant, TenantAPIKey

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


class TestCheckRateLimitNoLimitConfigured:
    def test_unlimited_key_is_always_allowed(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        for _ in range(5):
            result = check_rate_limit(instance)
            assert result.allowed is True
            assert result.limit is None
            assert result.remaining is None
            assert result.reset_at is None
            assert result.retry_after is None


class TestCheckRateLimitWithLimit:
    def test_requests_below_the_limit_are_allowed(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, rate_limit=5, rate_limit_window="minute"
        )
        for expected_remaining in (4, 3, 2):
            result = check_rate_limit(instance)
            assert result.allowed is True
            assert result.remaining == expected_remaining

    def test_request_exactly_at_the_limit_is_allowed(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, rate_limit=3, rate_limit_window="minute"
        )
        results = [check_rate_limit(instance) for _ in range(3)]
        assert all(r.allowed for r in results)
        assert results[-1].remaining == 0

    def test_request_exceeding_the_limit_is_denied(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, rate_limit=2, rate_limit_window="minute"
        )
        check_rate_limit(instance)
        check_rate_limit(instance)
        result = check_rate_limit(instance)

        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after is not None
        assert result.retry_after > 0

    def test_denied_result_reports_the_configured_limit(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, rate_limit=1)
        check_rate_limit(instance)
        result = check_rate_limit(instance)
        assert result.limit == 1

    def test_window_reset_allows_new_requests(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, rate_limit=1, rate_limit_window="second"
        )
        assert check_rate_limit(instance).allowed is True
        assert check_rate_limit(instance).allowed is False

        with mock.patch("django_tenant_apikeys.ratelimit.time.time") as mock_time:
            mock_time.return_value = 10_000.0  # far enough ahead to land in a new window
            result = check_rate_limit(instance)

        assert result.allowed is True

    def test_separate_keys_have_separate_limits(self, tenant: Tenant) -> None:
        first, _raw1 = TenantAPIKey.generate_key(name="a", tenant=tenant, rate_limit=1)
        second, _raw2 = TenantAPIKey.generate_key(name="b", tenant=tenant, rate_limit=1)

        assert check_rate_limit(first).allowed is True
        assert check_rate_limit(second).allowed is True  # not affected by first's usage
        assert check_rate_limit(first).allowed is False
        assert check_rate_limit(second).allowed is False

    def test_separate_tenants_have_independent_rate_limit_state(self, tenant: Tenant) -> None:
        tenant_b = Tenant.objects.create(name="Beta Inc.")
        key_a, _raw_a = TenantAPIKey.generate_key(name="k", tenant=tenant, rate_limit=1)
        key_b, _raw_b = TenantAPIKey.generate_key(name="k", tenant=tenant_b, rate_limit=1)

        assert check_rate_limit(key_a).allowed is True
        assert check_rate_limit(key_b).allowed is True

    def test_concurrent_requests_do_not_overcount_or_undercount(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, rate_limit=50)
        results: list[RateLimitResult] = []
        lock = threading.Lock()

        def hit() -> None:
            result = check_rate_limit(instance)
            with lock:
                results.append(result)

        threads = [threading.Thread(target=hit) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        allowed_count = sum(1 for r in results if r.allowed)
        assert allowed_count == 50
        assert {r.remaining for r in results} == set(range(50))


class TestCacheRateLimitBackend:
    def test_uses_the_default_cache_when_none_given(self) -> None:
        backend = CacheRateLimitBackend()
        assert backend.cache is caches["default"]

    def test_accepts_an_explicit_cache(self) -> None:
        explicit_cache = caches["default"]
        backend = CacheRateLimitBackend(cache=explicit_cache)
        assert backend.cache is explicit_cache

    @override_settings(TENANT_API_KEY_RATE_LIMIT_CACHE="default")
    def test_resolves_cache_alias_from_settings(self) -> None:
        backend = CacheRateLimitBackend()
        assert backend.cache is caches["default"]

    def test_key_expiring_between_add_and_incr_still_counts_the_request(self) -> None:
        backend = CacheRateLimitBackend()
        with mock.patch.object(backend.cache, "incr", side_effect=ValueError):
            result = backend.hit("ratelimit:test", limit=5, window_seconds=60)

        assert result.allowed is True
        assert result.remaining == 4


class TestGetRateLimitBackend:
    def test_defaults_to_cache_backend(self) -> None:
        assert isinstance(get_rate_limit_backend(), CacheRateLimitBackend)

    @override_settings(
        TENANT_API_KEY_RATE_LIMIT_BACKEND="tests.test_ratelimit.AllowAllBackend"
    )
    def test_resolves_a_custom_backend_from_settings(self) -> None:
        assert isinstance(get_rate_limit_backend(), AllowAllBackend)

    @override_settings(
        TENANT_API_KEY_RATE_LIMIT_BACKEND="tests.test_ratelimit.AllowAllBackend"
    )
    def test_custom_backend_is_actually_consulted(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, rate_limit=1)
        check_rate_limit(instance)
        result = check_rate_limit(instance)
        assert result.allowed is True  # AllowAllBackend never denies


class AllowAllBackend:
    """A trivial custom backend, used only to prove TENANT_API_KEY_RATE_LIMIT_BACKEND
    is actually respected -- exactly the kind of drop-in replacement (e.g. a future
    Redis-backed implementation) the RateLimitBackend protocol exists for."""

    def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        return RateLimitResult(
            allowed=True, limit=limit, remaining=limit, reset_at=None, retry_after=None
        )
