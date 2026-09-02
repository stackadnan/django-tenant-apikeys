"""Tests for the Django Ninja authentication integration."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.http import HttpRequest
from django.test import RequestFactory
from django.utils import timezone

from django_tenant_apikeys.models import get_api_key_model
from django_tenant_apikeys.ninja import TenantAPIKeyAuth
from tests.models import Tenant, TenantAPIKey, UnlinkedAPIKey

pytestmark = pytest.mark.django_db

_factory = RequestFactory()


def build_request() -> HttpRequest:
    return _factory.get("/")


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


@pytest.fixture
def api_key(tenant: Tenant) -> tuple[TenantAPIKey, str]:
    return TenantAPIKey.generate_key(name="test key", tenant=tenant, scopes=["*"])


class TestAuthenticate:
    def test_no_key_returns_none(self) -> None:
        assert TenantAPIKeyAuth().authenticate(build_request(), None) is None

    def test_empty_key_returns_none(self) -> None:
        assert TenantAPIKeyAuth().authenticate(build_request(), "") is None

    def test_wrong_scheme_returns_none(self) -> None:
        assert TenantAPIKeyAuth().authenticate(build_request(), "Bearer sometoken") is None

    def test_missing_credentials_returns_none(self) -> None:
        assert TenantAPIKeyAuth().authenticate(build_request(), "Api-Key") is None

    def test_spaces_in_key_return_none(self) -> None:
        assert TenantAPIKeyAuth().authenticate(build_request(), "Api-Key abc def") is None

    def test_scheme_is_case_insensitive(self, api_key: tuple[TenantAPIKey, str]) -> None:
        instance, raw_key = api_key
        result = TenantAPIKeyAuth().authenticate(build_request(), f"api-key {raw_key}")
        assert result is not None
        assert result.pk == instance.pk

    def test_valid_key_returns_the_key_instance(
        self, api_key: tuple[TenantAPIKey, str]
    ) -> None:
        instance, raw_key = api_key
        result = TenantAPIKeyAuth().authenticate(build_request(), f"Api-Key {raw_key}")
        assert result is not None
        assert result.pk == instance.pk

    def test_unknown_prefix_returns_none(self) -> None:
        result = TenantAPIKeyAuth().authenticate(
            build_request(), "Api-Key tak_live_doesnotexist.secret"
        )
        assert result is None

    def test_tampered_secret_returns_none(self, api_key: tuple[TenantAPIKey, str]) -> None:
        instance, _raw_key = api_key
        result = TenantAPIKeyAuth().authenticate(
            build_request(), f"Api-Key {instance.prefix}.tamperedsecret"
        )
        assert result is None

    def test_inactive_key_returns_none(self, tenant: Tenant) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)
        assert TenantAPIKeyAuth().authenticate(build_request(), f"Api-Key {raw_key}") is None

    def test_expired_key_returns_none(self, tenant: Tenant) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() - timedelta(days=1)
        )
        assert TenantAPIKeyAuth().authenticate(build_request(), f"Api-Key {raw_key}") is None

    def test_non_expiring_key_succeeds(self, tenant: Tenant) -> None:
        instance, raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, expires_at=None)
        result = TenantAPIKeyAuth().authenticate(build_request(), f"Api-Key {raw_key}")
        assert result is not None
        assert result.pk == instance.pk

    def test_successful_authentication_records_usage(
        self, api_key: tuple[TenantAPIKey, str]
    ) -> None:
        instance, raw_key = api_key
        assert instance.last_used_at is None

        TenantAPIKeyAuth().authenticate(build_request(), f"Api-Key {raw_key}")

        instance.refresh_from_db()
        assert instance.last_used_at is not None

    def test_failed_authentication_does_not_record_usage(self, tenant: Tenant) -> None:
        instance, raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)

        TenantAPIKeyAuth().authenticate(build_request(), f"Api-Key {raw_key}")

        instance.refresh_from_db()
        assert instance.last_used_at is None

    def test_tenant_is_attached_to_request(
        self, tenant: Tenant, api_key: tuple[TenantAPIKey, str]
    ) -> None:
        _instance, raw_key = api_key
        request = build_request()

        TenantAPIKeyAuth().authenticate(request, f"Api-Key {raw_key}")

        assert request.tenant == tenant  # type: ignore[attr-defined]

    def test_no_tenant_relation_is_not_attached(self) -> None:
        _instance, raw_key = UnlinkedAPIKey.generate_key(name="k")
        request = build_request()
        auth = TenantAPIKeyAuth()
        auth.model = UnlinkedAPIKey

        auth.authenticate(request, f"Api-Key {raw_key}")

        assert not hasattr(request, "tenant")

    def test_scope_check_works_on_the_returned_instance(self, tenant: Tenant) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"]
        )

        result = TenantAPIKeyAuth().authenticate(build_request(), f"Api-Key {raw_key}")

        assert result is not None
        assert result.has_scope("orders:read") is True
        assert result.has_scope("orders:write") is False


class TestGetModel:
    def test_falls_back_to_settings_when_unset(self) -> None:
        assert TenantAPIKeyAuth().get_model() is get_api_key_model()

    def test_uses_explicit_model_when_set(self) -> None:
        auth = TenantAPIKeyAuth()
        auth.model = UnlinkedAPIKey
        assert auth.get_model() is UnlinkedAPIKey
