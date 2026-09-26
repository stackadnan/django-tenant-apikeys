"""Rate limiting as a real throttle in both frameworks: DRF's ``BaseThrottle``
and Ninja's, through each framework's actual request flow, so the 429 and
``Retry-After`` come from the framework, not from a permission class."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from ninja import NinjaAPI
from ninja.testing import TestClient
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from django_tenant_apikeys.authentication import TenantAPIKeyAuthentication
from django_tenant_apikeys.ninja import TenantAPIKeyAuth, TenantAPIKeyThrottle
from django_tenant_apikeys.throttling import TenantAPIKeyThrottle as DRFThrottle
from tests.models import Tenant, TenantAPIKey

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()


class ThrottledView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes: list[Any] = []
    throttle_classes = [DRFThrottle]

    def get(self, request: Any) -> Response:
        return Response({"ok": True})


class SessionOnlyView(APIView):
    """No API key involved at all."""

    authentication_classes: list[Any] = []
    permission_classes: list[Any] = []
    throttle_classes = [DRFThrottle]

    def get(self, request: Any) -> Response:
        return Response({"ok": True})


ninja_api = NinjaAPI(
    auth=TenantAPIKeyAuth(), throttle=[TenantAPIKeyThrottle()], urls_namespace="throttling"
)


@ninja_api.get("/orders")
def ninja_orders(request):  # type: ignore[no-untyped-def]
    return {"ok": True}


ninja_client = TestClient(ninja_api)


def via_drf(raw_key: str) -> Response:
    return ThrottledView.as_view()(  # type: ignore[no-any-return]
        _factory.get("/", HTTP_AUTHORIZATION=f"Api-Key {raw_key}")
    )


def via_ninja(raw_key: str) -> Any:
    return ninja_client.get("/orders", headers={"Authorization": f"Api-Key {raw_key}"})


@pytest.fixture(params=["drf", "ninja"])
def call(request: pytest.FixtureRequest) -> Any:
    return {"drf": via_drf, "ninja": via_ninja}[request.param]


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


def retry_after(response: Any) -> int:
    return int(response["Retry-After"])


class TestBothFrameworks:
    def test_requests_within_the_limit_succeed(self, call: Any, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, rate_limit=3)
        assert [call(raw).status_code for _ in range(3)] == [200, 200, 200]

    def test_the_request_over_the_limit_is_429(self, call: Any, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, rate_limit=2)
        assert [call(raw).status_code for _ in range(4)] == [200, 200, 429, 429]

    def test_429_carries_retry_after(self, call: Any, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, rate_limit=1, rate_limit_window="hour"
        )
        call(raw)
        response = call(raw)
        assert response.status_code == 429
        assert 0 < retry_after(response) <= 3600

    def test_a_key_without_a_limit_is_never_throttled(self, call: Any, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert {call(raw).status_code for _ in range(20)} == {200}

    def test_keys_are_counted_independently(self, call: Any, tenant: Tenant) -> None:
        _a, raw_a = TenantAPIKey.generate_key(name="a", tenant=tenant, rate_limit=1)
        _b, raw_b = TenantAPIKey.generate_key(name="b", tenant=tenant, rate_limit=1)
        assert call(raw_a).status_code == 200
        assert call(raw_a).status_code == 429
        assert call(raw_b).status_code == 200

    def test_a_rejected_key_is_not_counted_against_anything(
        self, call: Any, tenant: Tenant
    ) -> None:
        # 401s come from authentication, before the throttle ever runs.
        assert call("tak_live_00000000.nope").status_code == 401


class TestDrfSpecifics:
    def test_rate_limit_headers_are_set_on_success_and_on_429(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, rate_limit=1)
        ok = via_drf(raw)
        assert ok["X-RateLimit-Limit"] == "1"
        assert ok["X-RateLimit-Remaining"] == "0"
        assert ok["X-RateLimit-Reset"].isdigit()
        limited = via_drf(raw)
        assert limited.status_code == 429
        assert limited["X-RateLimit-Limit"] == "1"

    def test_no_headers_for_a_key_without_a_limit(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert "X-RateLimit-Limit" not in via_drf(raw)

    def test_a_request_not_authenticated_by_an_api_key_is_allowed(self) -> None:
        response = SessionOnlyView.as_view()(_factory.get("/"))
        assert response.status_code == 200

    def test_wait_is_none_before_a_check(self) -> None:
        assert DRFThrottle().wait() is None


class TestNinjaSpecifics:
    def test_a_request_without_an_api_key_auth_is_allowed(self) -> None:
        request = type("Req", (), {"auth": None})()
        assert TenantAPIKeyThrottle().allow_request(request) is True  # type: ignore[arg-type]

    def test_wait_is_none_before_a_check(self) -> None:
        assert TenantAPIKeyThrottle().wait() is None

    def test_one_instance_shared_across_threads_keeps_results_apart(
        self, tenant: Tenant
    ) -> None:
        # Ninja shares a single throttle instance across requests; the last
        # result must not leak from one thread to another.
        import threading

        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, rate_limit=1, rate_limit_window="hour"
        )
        limited_key = TenantAPIKey.objects.get(prefix=raw.partition(".")[0])
        throttle = TenantAPIKeyThrottle()
        request = type("Req", (), {"auth": limited_key})()
        assert throttle.allow_request(request) is True  # type: ignore[arg-type]
        assert throttle.allow_request(request) is False  # type: ignore[arg-type]
        seen: list[float | None] = []
        thread = threading.Thread(target=lambda: seen.append(throttle.wait()))
        thread.start()
        thread.join()
        assert seen == [None]  # a different thread has no result of its own
        assert throttle.wait() is not None
