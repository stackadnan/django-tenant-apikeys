"""DRF <-> Django Ninja parity.

Every security-sensitive behaviour is asserted against *both* adapters
through their real request flow (an ``APIView`` and a ``NinjaAPI``), with the
same inputs and the same expected status. A rule that's enforced for one
framework and silently skipped by the other fails here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from ninja import NinjaAPI
from ninja.testing import TestClient
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from django_tenant_apikeys.authentication import TenantAPIKeyAuthentication
from django_tenant_apikeys.ninja import TenantAPIKeyAuth
from django_tenant_apikeys.permissions import HasAPIKeyScope
from tests.models import Tenant, TenantAPIKey

pytestmark = pytest.mark.django_db

Outcome = tuple[int, Any]  # (status code, response detail/body)
Caller = Callable[..., Outcome]

_factory = APIRequestFactory()
DEFAULT_IP = "203.0.113.10"


class PlainView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]

    def get(self, request: Any) -> Response:
        return Response({"tenant": request.tenant.name})


class ScopedView(PlainView):
    required_scopes = ["orders:read"]


ninja_api = NinjaAPI(auth=TenantAPIKeyAuth(), urls_namespace="parity")


@ninja_api.get("/plain")
def ninja_plain(request):  # type: ignore[no-untyped-def]
    return {"tenant": request.tenant.name}


@ninja_api.get("/scoped", auth=TenantAPIKeyAuth(scopes=["orders:read"]))
def ninja_scoped(request):  # type: ignore[no-untyped-def]
    return {"tenant": request.tenant.name}


ninja_client = TestClient(ninja_api)


def via_drf(
    authorization: str | None,
    *,
    ip: str = DEFAULT_IP,
    scoped: bool = False,
    headers: dict[str, str] | None = None,
) -> Outcome:
    extra: dict[str, str] = {"REMOTE_ADDR": ip, **(headers or {})}
    if authorization is not None:
        extra["HTTP_AUTHORIZATION"] = authorization
    view = ScopedView if scoped else PlainView
    response = view.as_view()(_factory.get("/", **extra))
    return response.status_code, response.data


def via_ninja(
    authorization: str | None,
    *,
    ip: str = DEFAULT_IP,
    scoped: bool = False,
    headers: dict[str, str] | None = None,
) -> Outcome:
    request_headers = {"Authorization": authorization} if authorization is not None else {}
    response = ninja_client.get(
        "/scoped" if scoped else "/plain",
        headers=request_headers,
        META={"REMOTE_ADDR": ip, **(headers or {})},
    )
    return response.status_code, response.json()


@pytest.fixture(params=["drf", "ninja"])
def call(request: pytest.FixtureRequest) -> Caller:
    return {"drf": via_drf, "ninja": via_ninja}[request.param]  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


def bearer(raw_key: str) -> str:
    return f"Api-Key {raw_key}"


class TestAuthentication:
    def test_valid_key_succeeds_and_resolves_the_tenant(
        self, call: Caller, tenant: Tenant
    ) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert call(bearer(raw)) == (200, {"tenant": "Acme Inc."})

    def test_no_credentials_is_401(self, call: Caller) -> None:
        assert call(None)[0] == 401

    def test_wrong_scheme_is_401(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert call(f"Bearer {raw}")[0] == 401

    @pytest.mark.parametrize(
        "raw",
        ["nodot", "tak_live_00000000.", "tak_live_00000000.wrong", "x" * 300],
    )
    def test_malformed_unknown_or_wrong_secret_is_401(self, call: Caller, raw: str) -> None:
        assert call(bearer(raw))[0] == 401

    def test_wrong_secret_for_a_real_prefix_is_401(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert call(bearer(raw + "x"))[0] == 401

    def test_guessing_failures_are_indistinguishable(self, call: Caller, tenant: Tenant) -> None:
        # unknown prefix, real prefix + wrong secret, and malformed input must
        # produce the same response body, so a prober can't tell them apart.
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        key.revoke()  # even a *revoked* real prefix must look like any other
        bodies = {
            repr(call(bearer("tak_live_00000000.unknown"))),
            repr(call(bearer(raw + "x"))),
            repr(call(bearer("malformed"))),
        }
        assert len(bodies) == 1


class TestKeyState:
    def test_inactive_key_is_401(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)
        assert call(bearer(raw))[0] == 401

    def test_revoked_key_is_401(self, call: Caller, tenant: Tenant) -> None:
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        key.revoke(reason="compromised")
        assert call(bearer(raw))[0] == 401

    def test_expired_key_is_401(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert call(bearer(raw))[0] == 401

    def test_a_key_in_its_grace_period_still_works_then_stops(
        self, call: Caller, tenant: Tenant
    ) -> None:
        old, old_raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        new, new_raw = old.rotate(grace_period=timedelta(hours=1))
        assert call(bearer(old_raw))[0] == 200
        assert call(bearer(new_raw))[0] == 200
        TenantAPIKey.objects.filter(pk=old.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert call(bearer(old_raw))[0] == 401
        assert call(bearer(new_raw))[0] == 200

    def test_immediately_rotated_key_stops_working(self, call: Caller, tenant: Tenant) -> None:
        old, old_raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        _new, new_raw = old.rotate()
        assert call(bearer(old_raw))[0] == 401
        assert call(bearer(new_raw))[0] == 200


class TestEnvironment:
    @override_settings(TENANT_API_KEY_ALLOWED_ENVIRONMENTS={"production"})
    def test_key_from_another_environment_is_403(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, environment="test")
        assert call(bearer(raw))[0] == 403

    @override_settings(TENANT_API_KEY_ALLOWED_ENVIRONMENTS={"production"})
    def test_key_from_the_allowed_environment_succeeds(
        self, call: Caller, tenant: Tenant
    ) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, environment="production")
        assert call(bearer(raw))[0] == 200

    def test_unset_setting_enforces_nothing(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, environment="test")
        assert call(bearer(raw))[0] == 200


class TestIpAllowlist:
    """Enforced during authentication itself: neither adapter needs the
    developer to remember an extra permission class or inline check."""

    def test_disallowed_ip_is_403(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["198.51.100.0/24"]
        )
        assert call(bearer(raw), ip=DEFAULT_IP)[0] == 403

    def test_allowed_ip_succeeds(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["203.0.113.0/24"]
        )
        assert call(bearer(raw), ip=DEFAULT_IP)[0] == 200

    def test_ipv4_mapped_ipv6_client_matches_an_ipv4_entry(
        self, call: Caller, tenant: Tenant
    ) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["203.0.113.0/24"]
        )
        assert call(bearer(raw), ip="::ffff:203.0.113.10")[0] == 200

    def test_malformed_client_ip_fails_closed(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["203.0.113.0/24"]
        )
        assert call(bearer(raw), ip="garbage")[0] == 403

    def test_a_forwarded_header_is_ignored_unless_trusted(
        self, call: Caller, tenant: Tenant
    ) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["203.0.113.0/24"]
        )
        spoofed = {"HTTP_X_FORWARDED_FOR": "203.0.113.50"}
        assert call(bearer(raw), ip="198.51.100.7", headers=spoofed)[0] == 403

    @override_settings(TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_FORWARDED_FOR")
    def test_a_client_supplied_forwarded_entry_cannot_claim_an_allowed_ip(
        self, call: Caller, tenant: Tenant
    ) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["203.0.113.0/24"]
        )
        # The attacker (198.51.100.7) prepends an allowed address; the proxy
        # (10.0.0.1) appends the address it actually saw.
        spoofed = {"HTTP_X_FORWARDED_FOR": "203.0.113.50, 198.51.100.7"}
        assert call(bearer(raw), ip="10.0.0.1", headers=spoofed)[0] == 403

    @override_settings(TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_FORWARDED_FOR")
    def test_the_address_the_trusted_proxy_appended_is_used(
        self, call: Caller, tenant: Tenant
    ) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["203.0.113.0/24"]
        )
        genuine = {"HTTP_X_FORWARDED_FOR": "203.0.113.50"}
        assert call(bearer(raw), ip="10.0.0.1", headers=genuine)[0] == 200

    @override_settings(TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_FORWARDED_FOR")
    def test_malformed_forwarded_value_fails_closed(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["203.0.113.0/24"]
        )
        assert call(bearer(raw), headers={"HTTP_X_FORWARDED_FOR": "203.0.113.5, junk"})[0] == 403

    def test_ip_is_enforced_without_any_permission_class(
        self, call: Caller, tenant: Tenant
    ) -> None:
        # PlainView/``/plain`` carry no HasAllowedIP and no inline check --
        # the exact fail-open-by-omission shape that used to accept the key.
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["198.51.100.0/24"]
        )
        assert call(bearer(raw), scoped=False)[0] == 403


class TestTenant:
    def test_suspended_tenant_is_403(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        Tenant.objects.filter(pk=tenant.pk).update(is_active=False)
        assert call(bearer(raw))[0] == 403

    def test_each_key_resolves_its_own_tenant(self, call: Caller, tenant: Tenant) -> None:
        other = Tenant.objects.create(name="Beta Inc.")
        _a, raw_a = TenantAPIKey.generate_key(name="a", tenant=tenant)
        _b, raw_b = TenantAPIKey.generate_key(name="b", tenant=other)
        assert call(bearer(raw_a))[1] == {"tenant": "Acme Inc."}
        assert call(bearer(raw_b))[1] == {"tenant": "Beta Inc."}


class TestScopes:
    def test_required_scope_present_succeeds(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, scopes=["orders:read"])
        assert call(bearer(raw), scoped=True)[0] == 200

    def test_required_scope_missing_is_403(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, scopes=["orders:write"])
        assert call(bearer(raw), scoped=True)[0] == 403

    def test_no_scopes_is_403(self, call: Caller, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert call(bearer(raw), scoped=True)[0] == 403

    def test_wildcards_grant(self, call: Caller, tenant: Tenant) -> None:
        _a, raw_a = TenantAPIKey.generate_key(name="a", tenant=tenant, scopes=["*"])
        _b, raw_b = TenantAPIKey.generate_key(name="b", tenant=tenant, scopes=["orders:*"])
        assert call(bearer(raw_a), scoped=True)[0] == 200
        assert call(bearer(raw_b), scoped=True)[0] == 200

    def test_a_shorter_scope_does_not_grant_a_longer_one(
        self, call: Caller, tenant: Tenant
    ) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, scopes=["orders"])
        assert call(bearer(raw), scoped=True)[0] == 403

    def test_a_malformed_string_scopes_row_grants_nothing(
        self, call: Caller, tenant: Tenant
    ) -> None:
        # Written past generate_key() (fixture / raw ORM / old admin): a bare
        # string must not be substring-matched into access.
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        TenantAPIKey.objects.filter(pk=key.pk).update(scopes="orders:read")
        assert call(bearer(raw), scoped=True)[0] == 403

    def test_a_missing_scope_is_reported_after_authentication_not_instead_of_it(
        self, call: Caller
    ) -> None:
        assert call(bearer("tak_live_00000000.nope"), scoped=True)[0] == 401
