"""End-to-end tests for the IP allowlist, rate limit, and scope permissions
running together through a real APIView -- DRF's actual authenticate() ->
check_permissions() -> check_throttles() request flow, not the individual
classes in isolation (see test_permissions.py for those)."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from django_tenant_apikeys.authentication import TenantAPIKeyAuthentication
from django_tenant_apikeys.permissions import HasAllowedIP, HasAPIKeyScope, WithinRateLimit
from tests.models import Tenant, TenantAPIKey

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()


class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAllowedIP, WithinRateLimit, HasAPIKeyScope]
    required_scopes = ["orders:read"]

    def get(self, request: object) -> Response:
        return Response({"ok": True})


def call(raw_key: str, remote_addr: str = "203.0.113.10") -> Response:
    request = _factory.get(
        "/", HTTP_AUTHORIZATION=f"Api-Key {raw_key}", REMOTE_ADDR=remote_addr
    )
    return OrdersView.as_view()(request)  # type: ignore[return-value]


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
        assert response["X-RateLimit-Limit"] == "5"
        assert response["X-RateLimit-Remaining"] == "4"

    def test_no_policies_configured_succeeds_like_before_0_4_0(self, tenant: Tenant) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"]
        )
        response = call(raw_key)
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response

    def test_wrong_ip_is_rejected_before_rate_limit_or_scope_are_checked(
        self, tenant: Tenant
    ) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(
            name="k",
            tenant=tenant,
            scopes=["orders:read"],
            allowed_ips=["198.51.100.1"],
            rate_limit=1,
        )

        response = call(raw_key, remote_addr="203.0.113.10")

        assert response.status_code == 403
        # Rejected on IP, so the rate limiter was never consulted.
        assert "X-RateLimit-Limit" not in response

    def test_rate_limit_exceeded_returns_429_with_retry_after(self, tenant: Tenant) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"], rate_limit=1
        )

        first = call(raw_key)
        second = call(raw_key)

        assert first.status_code == 200
        assert second.status_code == 429
        assert "Retry-After" in second

    def test_missing_scope_is_rejected_only_after_ip_and_rate_limit_pass(
        self, tenant: Tenant
    ) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=[], allowed_ips=["203.0.113.10"], rate_limit=5
        )

        response = call(raw_key)

        assert response.status_code == 403
        # The rate limiter ran (and set headers) before the scope check denied it.
        assert response["X-RateLimit-Remaining"] == "4"

    def test_invalid_key_never_reaches_the_permission_chain(self) -> None:
        response = call("tak_live_doesnotexist.secret")
        assert response.status_code == 401

    def test_revoked_key_never_reaches_the_permission_chain(self, tenant: Tenant) -> None:
        instance, raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"], rate_limit=5
        )
        instance.revoke()

        response = call(raw_key)

        assert response.status_code == 401
        assert "X-RateLimit-Limit" not in response

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
        assert call(raw_b).status_code == 200  # unaffected by tenant A's request

    def test_two_tenants_with_overlapping_allowed_ip_ranges_are_independent(
        self, tenant: Tenant
    ) -> None:
        tenant_b = Tenant.objects.create(name="Beta Inc.")
        _key_a, raw_a = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"], allowed_ips=["203.0.113.0/24"]
        )
        _key_b, raw_b = TenantAPIKey.generate_key(
            name="k",
            tenant=tenant_b,
            scopes=["orders:read"],
            allowed_ips=["203.0.113.0/24"],
        )

        assert call(raw_a, remote_addr="203.0.113.5").status_code == 200
        assert call(raw_b, remote_addr="203.0.113.5").status_code == 200
