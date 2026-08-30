"""Tests for DRF API key header parsing, expiration, and tenant resolution."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from django_tenant_apikeys.authentication import TenantAPIKeyAuthentication, get_api_key_model
from tests.models import Tenant, TenantAPIKey, UnlinkedAPIKey

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()


def build_request(auth_header: str | None = None) -> Request:
    extra = {"HTTP_AUTHORIZATION": auth_header} if auth_header is not None else {}
    return Request(_factory.get("/", **extra))


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


@pytest.fixture
def api_key(tenant: Tenant) -> tuple[TenantAPIKey, str]:
    return TenantAPIKey.generate_key(name="test key", tenant=tenant, scopes=["*"])


class TestGetApiKeyModel:
    def test_resolves_configured_model(self) -> None:
        assert get_api_key_model() is TenantAPIKey

    def test_raises_when_unset(self) -> None:
        with override_settings(TENANT_API_KEY_MODEL=None):
            with pytest.raises(ImproperlyConfigured, match="not set"):
                get_api_key_model()

    def test_raises_when_path_has_no_dot(self) -> None:
        with override_settings(TENANT_API_KEY_MODEL="not-a-valid-path"):
            with pytest.raises(ImproperlyConfigured, match="not been installed"):
                get_api_key_model()

    def test_raises_when_model_does_not_exist(self) -> None:
        with override_settings(TENANT_API_KEY_MODEL="tests.NoSuchModel"):
            with pytest.raises(ImproperlyConfigured, match="not been installed"):
                get_api_key_model()


class TestAuthenticate:
    def test_no_header_returns_none(self) -> None:
        request = build_request()
        assert TenantAPIKeyAuthentication().authenticate(request) is None

    def test_wrong_scheme_returns_none(self) -> None:
        request = build_request("Bearer sometoken")
        assert TenantAPIKeyAuthentication().authenticate(request) is None

    def test_missing_credentials_raises(self) -> None:
        request = build_request("Api-Key")
        with pytest.raises(AuthenticationFailed, match="No credentials provided"):
            TenantAPIKeyAuthentication().authenticate(request)

    def test_spaces_in_key_raise(self) -> None:
        request = build_request("Api-Key abc def")
        with pytest.raises(AuthenticationFailed, match="should not contain spaces"):
            TenantAPIKeyAuthentication().authenticate(request)

    def test_invalid_key_encoding_raises(self) -> None:
        request = build_request("Api-Key \xff\xfe")
        with pytest.raises(AuthenticationFailed, match="invalid characters"):
            TenantAPIKeyAuthentication().authenticate(request)

    def test_scheme_is_case_insensitive(self, api_key: tuple[TenantAPIKey, str]) -> None:
        instance, raw_key = api_key
        request = build_request(f"api-key {raw_key}")
        user, returned_key = TenantAPIKeyAuthentication().authenticate(request)  # type: ignore[misc]
        assert user is None
        assert returned_key.pk == instance.pk

    def test_valid_key_returns_none_user_and_key_instance(
        self, api_key: tuple[TenantAPIKey, str]
    ) -> None:
        instance, raw_key = api_key
        request = build_request(f"Api-Key {raw_key}")
        user, returned_key = TenantAPIKeyAuthentication().authenticate(request)  # type: ignore[misc]
        assert user is None
        assert returned_key.pk == instance.pk

    def test_unknown_prefix_raises(self) -> None:
        request = build_request("Api-Key tak_live_doesnotexist.secret")
        with pytest.raises(AuthenticationFailed, match="Invalid API key"):
            TenantAPIKeyAuthentication().authenticate(request)

    def test_tampered_secret_raises(self, api_key: tuple[TenantAPIKey, str]) -> None:
        instance, _raw_key = api_key
        request = build_request(f"Api-Key {instance.prefix}.tamperedsecret")
        with pytest.raises(AuthenticationFailed, match="Invalid API key"):
            TenantAPIKeyAuthentication().authenticate(request)

    def test_inactive_key_raises(self, tenant: Tenant) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)
        request = build_request(f"Api-Key {raw_key}")
        with pytest.raises(AuthenticationFailed, match="deactivated"):
            TenantAPIKeyAuthentication().authenticate(request)

    def test_expired_key_raises(self, tenant: Tenant) -> None:
        _instance, raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() - timedelta(days=1)
        )
        request = build_request(f"Api-Key {raw_key}")
        with pytest.raises(AuthenticationFailed, match="expired"):
            TenantAPIKeyAuthentication().authenticate(request)

    def test_non_expiring_key_succeeds(self, tenant: Tenant) -> None:
        instance, raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, expires_at=None)
        request = build_request(f"Api-Key {raw_key}")
        _user, returned_key = TenantAPIKeyAuthentication().authenticate(request)  # type: ignore[misc]
        assert returned_key.pk == instance.pk

    def test_successful_authentication_records_usage(
        self, tenant: Tenant, api_key: tuple[TenantAPIKey, str]
    ) -> None:
        instance, raw_key = api_key
        assert instance.last_used_at is None

        request = build_request(f"Api-Key {raw_key}")
        TenantAPIKeyAuthentication().authenticate(request)

        instance.refresh_from_db()
        assert instance.last_used_at is not None

    def test_failed_authentication_does_not_record_usage(self, tenant: Tenant) -> None:
        instance, raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)
        request = build_request(f"Api-Key {raw_key}")
        with pytest.raises(AuthenticationFailed):
            TenantAPIKeyAuthentication().authenticate(request)

        instance.refresh_from_db()
        assert instance.last_used_at is None

    def test_tenant_is_attached_to_request(
        self, tenant: Tenant, api_key: tuple[TenantAPIKey, str]
    ) -> None:
        _instance, raw_key = api_key
        request = build_request(f"Api-Key {raw_key}")
        TenantAPIKeyAuthentication().authenticate(request)
        assert request.tenant == tenant  # type: ignore[attr-defined]

    def test_no_tenant_relation_is_not_attached(self) -> None:
        _instance, raw_key = UnlinkedAPIKey.generate_key(name="k")
        request = build_request(f"Api-Key {raw_key}")
        auth = TenantAPIKeyAuthentication()
        auth.model = UnlinkedAPIKey
        auth.authenticate(request)
        assert not hasattr(request, "tenant")

    def test_authenticate_header(self) -> None:
        request = build_request()
        assert TenantAPIKeyAuthentication().authenticate_header(request) == 'Api-Key realm="api"'


class TestAuthenticateCredentials:
    def test_without_request_skips_tenant_attachment(
        self, api_key: tuple[TenantAPIKey, str]
    ) -> None:
        instance, raw_key = api_key
        user, returned_key = TenantAPIKeyAuthentication().authenticate_credentials(raw_key)
        assert user is None
        assert returned_key.pk == instance.pk
