"""Tests for the tenant_api_key_revoke and tenant_api_key_rotate commands."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.models import Tenant, TenantAPIKey

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


class TestTenantApiKeyRevoke:
    def test_revokes_the_key(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)

        call_command("tenant_api_key_revoke", instance.prefix)

        instance.refresh_from_db()
        assert instance.is_active is False

    def test_stores_the_given_reason(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)

        call_command("tenant_api_key_revoke", instance.prefix, reason="compromised")

        instance.refresh_from_db()
        assert instance.revoked_reason == "compromised"

    def test_prints_a_confirmation(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        out = StringIO()

        call_command("tenant_api_key_revoke", instance.prefix, stdout=out)

        assert instance.prefix in out.getvalue()
        assert "Revoked" in out.getvalue()

    def test_never_prints_the_hash(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        out = StringIO()

        call_command("tenant_api_key_revoke", instance.prefix, stdout=out)

        assert instance.hashed_key not in out.getvalue()

    def test_unknown_prefix_raises_command_error(self) -> None:
        with pytest.raises(CommandError, match="No API key found"):
            call_command("tenant_api_key_revoke", "tak_live_doesnotexist")


class TestTenantApiKeyRotate:
    def test_rotates_the_key(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)

        call_command("tenant_api_key_rotate", instance.prefix)

        instance.refresh_from_db()
        assert instance.is_active is False
        assert TenantAPIKey.objects.filter(tenant=tenant, is_active=True).count() == 1

    def test_prints_a_working_new_raw_key(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        out = StringIO()

        call_command("tenant_api_key_rotate", instance.prefix, stdout=out)

        new_key = TenantAPIKey.objects.get(tenant=tenant, is_active=True)
        printed_raw_key = out.getvalue().strip().splitlines()[-1]
        assert new_key.prefix in out.getvalue()
        assert new_key.verify_key(printed_raw_key) is True

    def test_never_prints_the_old_hash(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        out = StringIO()

        call_command("tenant_api_key_rotate", instance.prefix, stdout=out)

        assert instance.hashed_key not in out.getvalue()

    def test_unknown_prefix_raises_command_error(self) -> None:
        with pytest.raises(CommandError, match="No API key found"):
            call_command("tenant_api_key_rotate", "tak_live_doesnotexist")

    def test_rotating_an_inactive_key_raises_command_error(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)

        with pytest.raises(CommandError, match="inactive or expired"):
            call_command("tenant_api_key_rotate", instance.prefix)
