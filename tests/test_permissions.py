"""Tests for scope permission checks (wildcards and explicit scopes)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from django_tenant_apikeys.permissions import HasAPIKeyScope
from tests.models import Tenant, TenantAPIKey

pytestmark = pytest.mark.django_db


class DummyRequest:
    """Minimal stand-in for a DRF Request: HasAPIKeyScope only reads `.auth`."""

    def __init__(self, auth: Any) -> None:
        self.auth = auth


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


def make_key(tenant: Tenant, scopes: list[str]) -> TenantAPIKey:
    instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, scopes=scopes)
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
