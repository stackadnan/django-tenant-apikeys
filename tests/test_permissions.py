"""Tests for the DRF permission classes: scopes, IP allowlist, rate limit."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.exceptions import Throttled

from django_tenant_apikeys.permissions import HasAllowedIP, HasAPIKeyScope, WithinRateLimit
from tests.models import Tenant, TenantAPIKey

pytestmark = pytest.mark.django_db


class DummyRequest:
    """Minimal stand-in for a DRF Request: these permissions only read
    `.auth` and, for the IP check, `.META`."""

    def __init__(self, auth: Any, remote_addr: str = "203.0.113.10") -> None:
        self.auth = auth
        self.META = {"REMOTE_ADDR": remote_addr}


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


def make_key(tenant: Tenant, scopes: list[str] | None = None, **kwargs: Any) -> TenantAPIKey:
    instance, _raw_key = TenantAPIKey.generate_key(
        name="k", tenant=tenant, scopes=scopes or [], **kwargs
    )
    return instance


class TestHasAPIKeyScope:
    def test_denies_when_auth_is_none(self) -> None:
        permission = HasAPIKeyScope()
        request = DummyRequest(auth=None)
        view = SimpleNamespace(required_scopes=["orders:read"])
        assert permission.has_permission(request, view) is False  # type: ignore[arg-type]

    def test_denies_when_auth_is_some_other_object(self) -> None:
        permission = HasAPIKeyScope()
        request = DummyRequest(auth="not-an-api-key")
        view = SimpleNamespace(required_scopes=["orders:read"])
        assert permission.has_permission(request, view) is False  # type: ignore[arg-type]

    def test_allows_when_view_has_no_required_scopes_attribute(self, tenant: Tenant) -> None:
        permission = HasAPIKeyScope()
        request = DummyRequest(auth=make_key(tenant, scopes=[]))
        view = SimpleNamespace()
        assert permission.has_permission(request, view) is True  # type: ignore[arg-type]

    def test_allows_when_required_scopes_is_empty(self, tenant: Tenant) -> None:
        permission = HasAPIKeyScope()
        request = DummyRequest(auth=make_key(tenant, scopes=[]))
        view = SimpleNamespace(required_scopes=[])
        assert permission.has_permission(request, view) is True  # type: ignore[arg-type]

    def test_allows_exact_scope_match(self, tenant: Tenant) -> None:
        permission = HasAPIKeyScope()
        request = DummyRequest(auth=make_key(tenant, scopes=["orders:read"]))
        view = SimpleNamespace(required_scopes=["orders:read"])
        assert permission.has_permission(request, view) is True  # type: ignore[arg-type]

    def test_denies_missing_scope(self, tenant: Tenant) -> None:
        permission = HasAPIKeyScope()
        request = DummyRequest(auth=make_key(tenant, scopes=["orders:read"]))
        view = SimpleNamespace(required_scopes=["orders:write"])
        assert permission.has_permission(request, view) is False  # type: ignore[arg-type]

    def test_allows_global_wildcard(self, tenant: Tenant) -> None:
        permission = HasAPIKeyScope()
        request = DummyRequest(auth=make_key(tenant, scopes=["*"]))
        view = SimpleNamespace(required_scopes=["orders:read", "billing:write", "anything"])
        assert permission.has_permission(request, view) is True  # type: ignore[arg-type]

    def test_allows_namespaced_wildcard(self, tenant: Tenant) -> None:
        permission = HasAPIKeyScope()
        request = DummyRequest(auth=make_key(tenant, scopes=["orders:*"]))
        view = SimpleNamespace(required_scopes=["orders:read", "orders:write"])
        assert permission.has_permission(request, view) is True  # type: ignore[arg-type]

    def test_namespaced_wildcard_does_not_leak_to_other_namespace(self, tenant: Tenant) -> None:
        permission = HasAPIKeyScope()
        request = DummyRequest(auth=make_key(tenant, scopes=["orders:*"]))
        view = SimpleNamespace(required_scopes=["billing:read"])
        assert permission.has_permission(request, view) is False  # type: ignore[arg-type]

    def test_requires_all_scopes_when_multiple_are_listed(self, tenant: Tenant) -> None:
        permission = HasAPIKeyScope()
        request = DummyRequest(auth=make_key(tenant, scopes=["orders:read"]))
        view = SimpleNamespace(required_scopes=["orders:read", "orders:write"])
        assert permission.has_permission(request, view) is False  # type: ignore[arg-type]

    def test_message_is_defined(self) -> None:
        assert HasAPIKeyScope.message


class TestHasAllowedIP:
    def test_denies_when_auth_is_none(self) -> None:
        permission = HasAllowedIP()
        request = DummyRequest(auth=None)
        assert permission.has_permission(request, SimpleNamespace()) is False  # type: ignore[arg-type]

    def test_allows_unrestricted_key(self, tenant: Tenant) -> None:
        permission = HasAllowedIP()
        request = DummyRequest(auth=make_key(tenant), remote_addr="203.0.113.10")
        assert permission.has_permission(request, SimpleNamespace()) is True  # type: ignore[arg-type]

    def test_allows_matching_ip(self, tenant: Tenant) -> None:
        permission = HasAllowedIP()
        key = make_key(tenant, allowed_ips=["203.0.113.10"])
        request = DummyRequest(auth=key, remote_addr="203.0.113.10")
        assert permission.has_permission(request, SimpleNamespace()) is True  # type: ignore[arg-type]

    def test_denies_non_matching_ip(self, tenant: Tenant) -> None:
        permission = HasAllowedIP()
        key = make_key(tenant, allowed_ips=["203.0.113.10"])
        request = DummyRequest(auth=key, remote_addr="198.51.100.1")
        assert permission.has_permission(request, SimpleNamespace()) is False  # type: ignore[arg-type]

    def test_message_is_defined(self) -> None:
        assert HasAllowedIP.message


class TestWithinRateLimit:
    def test_denies_when_auth_is_none(self) -> None:
        permission = WithinRateLimit()
        request = DummyRequest(auth=None)
        view = SimpleNamespace(headers={})
        assert permission.has_permission(request, view) is False  # type: ignore[arg-type]

    def test_allows_key_with_no_rate_limit_configured(self, tenant: Tenant) -> None:
        permission = WithinRateLimit()
        request = DummyRequest(auth=make_key(tenant))
        view = SimpleNamespace(headers={})
        assert permission.has_permission(request, view) is True  # type: ignore[arg-type]
        assert view.headers == {}

    def test_allows_and_sets_headers_within_the_limit(self, tenant: Tenant) -> None:
        permission = WithinRateLimit()
        key = make_key(tenant, rate_limit=5, rate_limit_window="minute")
        request = DummyRequest(auth=key)
        view = SimpleNamespace(headers={})

        assert permission.has_permission(request, view) is True  # type: ignore[arg-type]

        assert view.headers["X-RateLimit-Limit"] == "5"
        assert view.headers["X-RateLimit-Remaining"] == "4"
        assert "X-RateLimit-Reset" in view.headers

    def test_raises_throttled_once_the_limit_is_exceeded(self, tenant: Tenant) -> None:
        permission = WithinRateLimit()
        key = make_key(tenant, rate_limit=1, rate_limit_window="minute")
        request = DummyRequest(auth=key)
        view = SimpleNamespace(headers={})

        assert permission.has_permission(request, view) is True  # type: ignore[arg-type]
        with pytest.raises(Throttled):
            permission.has_permission(request, view)  # type: ignore[arg-type]

        assert view.headers["X-RateLimit-Remaining"] == "0"

    def test_message_is_defined(self) -> None:
        assert WithinRateLimit.message
