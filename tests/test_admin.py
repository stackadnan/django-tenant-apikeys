"""Tests for TenantAPIKeyAdmin: one-time key generation and masked display.

Not listed in the original file tree, but added alongside ``tests/models.py``
because ``AbstractTenantAPIKey`` cannot be exercised without a concrete model,
and the project's 100%-coverage requirement extends to ``admin.py``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib import messages
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest
from django.test import RequestFactory
from django.utils import timezone

from django_tenant_apikeys.admin import TenantAPIKeyAdmin
from tests.models import Tenant, TenantAPIKey

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


@pytest.fixture
def admin_instance() -> TenantAPIKeyAdmin:
    return TenantAPIKeyAdmin(model=TenantAPIKey, admin_site=AdminSite())


@pytest.fixture
def admin_request() -> HttpRequest:
    request = RequestFactory().post("/admin/tests/tenantapikey/add/")
    # Message storage (FallbackStorage by default) needs a real session
    # object, not just a request -- go through the actual middleware rather
    # than hand-assembling internals that vary across Django versions.
    SessionMiddleware(lambda r: None).process_request(request)
    MessageMiddleware(lambda r: None).process_request(request)
    return request


class TestReadonlyFields:
    def test_matches_spec(self, admin_instance: TenantAPIKeyAdmin) -> None:
        assert admin_instance.readonly_fields == (
            "prefix",
            "hashed_key",
            "created_at",
            "last_used_at",
            "revoked_at",
            "revoked_reason",
        )


class TestMaskedKey:
    def test_shows_prefix_and_masks_secret(
        self, admin_instance: TenantAPIKeyAdmin, tenant: Tenant
    ) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        masked = admin_instance.masked_key(instance)
        assert masked.startswith(instance.prefix + ".")
        assert "•" in masked  # the masking character, not the raw secret


class TestStatus:
    def test_active_key(self, admin_instance: TenantAPIKeyAdmin, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert admin_instance.status(instance) == "Active"

    def test_revoked_key(self, admin_instance: TenantAPIKeyAdmin, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        instance.revoke(reason="compromised")
        assert admin_instance.status(instance) == "Revoked"

    def test_manually_deactivated_key_without_revoke(
        self, admin_instance: TenantAPIKeyAdmin, tenant: Tenant
    ) -> None:
        # is_active=False set directly (e.g. an admin unchecking the box)
        # rather than through revoke() -- no revoked_at, so it reads
        # differently from an explicit revocation.
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)
        assert admin_instance.status(instance) == "Inactive"

    def test_expired_key(self, admin_instance: TenantAPIKeyAdmin, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() - timedelta(days=1)
        )
        assert admin_instance.status(instance) == "Expired"

    def test_expired_takes_precedence_over_revoked(
        self, admin_instance: TenantAPIKeyAdmin, tenant: Tenant
    ) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() - timedelta(days=1)
        )
        instance.revoke(reason="compromised")
        assert admin_instance.status(instance) == "Expired"


class TestRevokeSelectedAction:
    def test_revokes_active_keys_in_the_queryset(
        self, admin_instance: TenantAPIKeyAdmin, admin_request: HttpRequest, tenant: Tenant
    ) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)

        admin_instance.revoke_selected(admin_request, TenantAPIKey.objects.all())

        instance.refresh_from_db()
        assert instance.is_active is False
        assert instance.revoked_reason == "revoked via admin"

    def test_skips_already_inactive_keys(
        self, admin_instance: TenantAPIKeyAdmin, admin_request: HttpRequest, tenant: Tenant
    ) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)

        admin_instance.revoke_selected(admin_request, TenantAPIKey.objects.all())

        instance.refresh_from_db()
        assert instance.revoked_reason == ""  # untouched, not re-revoked

    def test_shows_a_count_message(
        self, admin_instance: TenantAPIKeyAdmin, admin_request: HttpRequest, tenant: Tenant
    ) -> None:
        TenantAPIKey.generate_key(name="a", tenant=tenant)
        TenantAPIKey.generate_key(name="b", tenant=tenant)

        admin_instance.revoke_selected(admin_request, TenantAPIKey.objects.all())

        queued = list(admin_request._messages)  # type: ignore[attr-defined]
        assert len(queued) == 1
        assert "Revoked 2 API key(s)" in str(queued[0])


class TestSaveModel:
    def test_create_generates_prefix_and_hash(
        self, admin_instance: TenantAPIKeyAdmin, admin_request: HttpRequest, tenant: Tenant
    ) -> None:
        obj = TenantAPIKey(name="new key", tenant=tenant)
        admin_instance.save_model(admin_request, obj, form=None, change=False)

        assert obj.pk is not None
        assert obj.prefix
        assert obj.hashed_key

    def test_create_persists_only_the_hash_not_the_raw_key(
        self, admin_instance: TenantAPIKeyAdmin, admin_request: HttpRequest, tenant: Tenant
    ) -> None:
        obj = TenantAPIKey(name="new key", tenant=tenant)
        admin_instance.save_model(admin_request, obj, form=None, change=False)

        obj.refresh_from_db()
        queued = list(admin_request._messages)  # type: ignore[attr-defined]
        raw_key = str(queued[0]).split("<code>")[1].split("</code>")[0]
        assert obj.verify_key(raw_key) is True
        assert raw_key != obj.hashed_key

    def test_create_shows_one_time_warning_message(
        self, admin_instance: TenantAPIKeyAdmin, admin_request: HttpRequest, tenant: Tenant
    ) -> None:
        obj = TenantAPIKey(name="new key", tenant=tenant)
        admin_instance.save_model(admin_request, obj, form=None, change=False)

        queued = list(admin_request._messages)  # type: ignore[attr-defined]
        assert len(queued) == 1
        assert queued[0].level == messages.WARNING
        assert obj.prefix in str(queued[0])
        assert "will not be shown again" in str(queued[0])

    def test_change_does_not_regenerate_key(
        self, admin_instance: TenantAPIKeyAdmin, admin_request: HttpRequest, tenant: Tenant
    ) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        original_prefix = instance.prefix
        original_hash = instance.hashed_key

        instance.name = "renamed"
        admin_instance.save_model(admin_request, instance, form=None, change=True)

        instance.refresh_from_db()
        assert instance.name == "renamed"
        assert instance.prefix == original_prefix
        assert instance.hashed_key == original_hash

    def test_change_does_not_queue_a_message(
        self, admin_instance: TenantAPIKeyAdmin, admin_request: HttpRequest, tenant: Tenant
    ) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        admin_instance.save_model(admin_request, instance, form=None, change=True)
        assert list(admin_request._messages) == []  # type: ignore[attr-defined]
