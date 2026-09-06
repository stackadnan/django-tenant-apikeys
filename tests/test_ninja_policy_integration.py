"""End-to-end tests for the IP allowlist and rate limit checks running
inline in a Django Ninja view, on top of TenantAPIKeyAuth -- the same
shared django_tenant_apikeys.ip/ratelimit functions the DRF permission
classes use (see test_drf_policy_integration.py), exercised through a real
NinjaAPI request instead of called directly."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.http import JsonResponse
from ninja import NinjaAPI
from ninja.testing import TestClient

from django_tenant_apikeys.ip import get_client_ip
from django_tenant_apikeys.ninja import TenantAPIKeyAuth
from django_tenant_apikeys.ratelimit import check_rate_limit
from tests.models import Tenant, TenantAPIKey

pytestmark = pytest.mark.django_db

api = NinjaAPI(auth=TenantAPIKeyAuth())


@api.get("/orders")
def list_orders(request):  # type: ignore[no-untyped-def]
    if not request.auth.is_ip_allowed(get_client_ip(request)):
        return JsonResponse({"detail": "IP not allowed"}, status=403)
    result = check_rate_limit(request.auth)
    if not result.allowed:
        return JsonResponse(
            {"detail": "rate limit exceeded", "retry_after": result.retry_after}, status=429
        )
    if not request.auth.has_scope("orders:read"):
        return JsonResponse({"detail": "missing required scope"}, status=403)
    return {"ok": True}


client = TestClient(api)


def call(raw_key: str, remote_addr: str = "203.0.113.10"):  # type: ignore[no-untyped-def]
    return client.get(
        "/orders",
        headers={"Authorization": f"Api-Key {raw_key}"},
        META={"REMOTE_ADDR": remote_addr},
    )


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


class TestPolicyChain:
    def test_valid_key_valid_ip_within_limit_and_scope_succeeds(self, tenant: Tenant) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(
            name="k",
            tenant=tenant,
            scopes=["orders:read"],
            allowed_ips=["203.0.113.10"],
            rate_limit=5,
        )
        response = call(raw_key)
        assert response.status_code == 200

    def test_wrong_ip_is_rejected(self, tenant: Tenant) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"], allowed_ips=["198.51.100.1"]
        )
        response = call(raw_key, remote_addr="203.0.113.10")
        assert response.status_code == 403

    def test_rate_limit_exceeded_returns_429(self, tenant: Tenant) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"], rate_limit=1
        )
        first = call(raw_key)
        second = call(raw_key)
        assert first.status_code == 200
        assert second.status_code == 429
        assert second.json()["retry_after"] is not None

    def test_missing_scope_is_rejected_only_after_ip_and_rate_limit_pass(
        self, tenant: Tenant
    ) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=[], allowed_ips=["203.0.113.10"], rate_limit=5
        )
        response = call(raw_key)
        assert response.status_code == 403
        assert response.json()["detail"] == "missing required scope"

    def test_invalid_key_never_reaches_the_view(self) -> None:
        response = call("tak_live_doesnotexist.secret")
        assert response.status_code == 401

    def test_two_tenants_with_identical_rate_limits_are_independent(
        self, tenant: Tenant
    ) -> None:
        tenant_b = Tenant.objects.create(name="Beta Inc.")
        _key_a, raw_a = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"], rate_limit=1
        )
        _key_b, raw_b = TenantAPIKey.generate_key(
            name="k", tenant=tenant_b, scopes=["orders:read"], rate_limit=1
        )
        assert call(raw_a).status_code == 200
        assert call(raw_b).status_code == 200
