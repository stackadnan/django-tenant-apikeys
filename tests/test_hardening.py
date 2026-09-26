"""Regression tests for correctness/security fixes in 0.4.1.

Each test pins a behavior that was previously wrong (or unverified) rather
than just exercising a line: malformed data reaching ``has_scope`` /
``is_ip_allowed`` through paths other than ``generate_key()``, non-idempotent
revocation, and ``rotate()`` on stale instances.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db import connection
from django.http import HttpRequest
from django.test import RequestFactory
from django.utils import timezone

from django_tenant_apikeys.admin import TenantAPIKeyAdmin
from tests.models import Tenant, TenantAPIKey

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


def raw_create(tenant: Tenant, **kwargs: object) -> TenantAPIKey:
    """Bypass generate_key() the way a fixture, a data migration, or a raw
    ORM call would -- no validation, arbitrary field values."""
    return TenantAPIKey.objects.create(
        name="raw", tenant=tenant, prefix=f"raw_live_{TenantAPIKey.objects.count():08x}",
        hashed_key="0" * 64, **kwargs,
    )


class TestScopesFailClosedOnMalformedData:
    @pytest.mark.parametrize("probe", ["orders", "ord", ":", "r", "orders:read", "*"])
    def test_bare_string_scopes_grant_nothing(self, tenant: Tenant, probe: str) -> None:
        # ``"orders" in "orders:read"`` is a substring test; a string written
        # past generate_key()'s validation must not over-grant.
        key = raw_create(tenant, scopes="orders:read")
        assert key.has_scope(probe) is False

    @pytest.mark.parametrize("bad", [None, 5, {"orders:read": True}])
    def test_non_list_scopes_grant_nothing(self, tenant: Tenant, bad: object) -> None:
        key = raw_create(tenant)
        key.scopes = bad
        assert key.has_scope("orders:read") is False

    def test_no_substring_over_grant_on_a_valid_list(self, tenant: Tenant) -> None:
        key = raw_create(tenant, scopes=["orders:read"])
        assert key.has_scope("orders") is False
        assert key.has_scope("orders:read") is True
        assert key.has_scope("orders:re") is False

    def test_empty_scopes_grant_nothing(self, tenant: Tenant) -> None:
        assert raw_create(tenant, scopes=[]).has_scope("orders:read") is False


class TestAllowedIpsFailClosedOnMalformedData:
    def test_bare_string_allowlist_denies_everyone(self, tenant: Tenant) -> None:
        key = raw_create(tenant, allowed_ips="203.0.113.5")
        assert key.is_ip_allowed("203.0.113.5") is False

    def test_non_string_entries_are_skipped_not_raised(self, tenant: Tenant) -> None:
        key = raw_create(tenant, allowed_ips=[5, None, "203.0.113.5"])
        assert key.is_ip_allowed("203.0.113.5") is True
        assert key.is_ip_allowed("203.0.113.6") is False

    def test_ipv4_mapped_ipv6_client_matches_an_ipv4_entry(self, tenant: Tenant) -> None:
        # A dual-stack socket reports IPv4 peers as ::ffff:a.b.c.d.
        key = raw_create(tenant, allowed_ips=["203.0.113.0/24"])
        assert key.is_ip_allowed("::ffff:203.0.113.9") is True
        assert key.is_ip_allowed("::ffff:198.51.100.9") is False

    def test_ipv6_entries_still_match_ipv6_clients(self, tenant: Tenant) -> None:
        key = raw_create(tenant, allowed_ips=["2001:db8::/32"])
        assert key.is_ip_allowed("2001:db8::1") is True
        assert key.is_ip_allowed("2001:db9::1") is False

    def test_all_malformed_entries_deny_everyone(self, tenant: Tenant) -> None:
        key = raw_create(tenant, allowed_ips=["not-an-ip"])
        assert key.is_ip_allowed("203.0.113.5") is False


class TestModelClean:
    def make(self, tenant: Tenant, **kwargs: object) -> TenantAPIKey:
        return TenantAPIKey(name="k", tenant=tenant, prefix="p_live_00000000", hashed_key="h",
                            **kwargs)

    def test_valid_data_passes(self, tenant: Tenant) -> None:
        self.make(tenant, scopes=["a:b"], allowed_ips=["10.0.0.0/8"], rate_limit=5).clean()

    def test_string_scopes_rejected(self, tenant: Tenant) -> None:
        with pytest.raises(ValidationError) as excinfo:
            self.make(tenant, scopes="orders:read").clean()
        assert "scopes" in excinfo.value.message_dict

    def test_bad_allowed_ips_rejected(self, tenant: Tenant) -> None:
        with pytest.raises(ValidationError) as excinfo:
            self.make(tenant, allowed_ips=["nope"]).clean()
        assert "allowed_ips" in excinfo.value.message_dict

    def test_zero_rate_limit_rejected(self, tenant: Tenant) -> None:
        with pytest.raises(ValidationError) as excinfo:
            self.make(tenant, rate_limit=0).clean()
        assert "rate_limit" in excinfo.value.message_dict

    def test_reports_every_bad_field_at_once(self, tenant: Tenant) -> None:
        with pytest.raises(ValidationError) as excinfo:
            self.make(tenant, scopes="x", allowed_ips="y").clean()
        assert set(excinfo.value.message_dict) == {"scopes", "allowed_ips"}


class TestAdminGoesThroughTheSameValidation:
    """Drives the admin's real ModelForm plus ``save_model``, not just the
    model method -- that's the path a staff user actually takes."""

    @pytest.fixture
    def model_admin(self) -> TenantAPIKeyAdmin:
        return TenantAPIKeyAdmin(model=TenantAPIKey, admin_site=AdminSite())

    @pytest.fixture
    def request_(self) -> HttpRequest:
        from django.contrib.messages.middleware import MessageMiddleware
        from django.contrib.sessions.middleware import SessionMiddleware

        request = RequestFactory().post("/admin/")
        SessionMiddleware(lambda r: None).process_request(request)
        MessageMiddleware(lambda r: None).process_request(request)
        return request

    def form_data(self, tenant: Tenant, **overrides: str) -> dict[str, str]:
        data = {
            "name": "from admin",
            "tenant": str(tenant.pk),
            "scopes": "[]",
            "environment": "production",
            "rate_limit_window": "minute",
            "allowed_ips": "[]",
            "metadata": "{}",
            "is_active": "on",
        }
        data.update(overrides)
        return data

    def test_string_scopes_are_rejected_by_the_admin_form(
        self, model_admin: TenantAPIKeyAdmin, request_: HttpRequest, tenant: Tenant
    ) -> None:
        form = model_admin.get_form(request_)(self.form_data(tenant, scopes='"orders:read"'))
        assert form.is_valid() is False
        assert "scopes" in form.errors

    def test_invalid_allowed_ips_are_rejected_by_the_admin_form(
        self, model_admin: TenantAPIKeyAdmin, request_: HttpRequest, tenant: Tenant
    ) -> None:
        form = model_admin.get_form(request_)(self.form_data(tenant, allowed_ips='["nope"]'))
        assert form.is_valid() is False
        assert "allowed_ips" in form.errors

    @pytest.mark.parametrize(
        ("environment", "segment"),
        [("production", "_live_"), ("staging", "_live_"), ("development", "_test_"),
         ("test", "_test_")],
    )
    def test_created_key_prefix_matches_the_chosen_environment(
        self, model_admin: TenantAPIKeyAdmin, request_: HttpRequest, tenant: Tenant,
        environment: str, segment: str,
    ) -> None:
        form = model_admin.get_form(request_)(self.form_data(tenant, environment=environment))
        assert form.is_valid(), form.errors
        obj = form.save(commit=False)
        model_admin.save_model(request_, obj, form, change=False)
        assert segment in obj.prefix
        assert obj.environment == environment

    def test_hashed_key_is_not_rendered_in_the_admin(
        self, model_admin: TenantAPIKeyAdmin, request_: HttpRequest
    ) -> None:
        assert "hashed_key" not in model_admin.get_fields(request_)
        assert "hashed_key" not in model_admin.readonly_fields

    def test_unchecking_is_active_records_the_revocation(
        self, model_admin: TenantAPIKeyAdmin, request_: HttpRequest, tenant: Tenant
    ) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        data = self.form_data(tenant, name="k")
        del data["is_active"]
        form = model_admin.get_form(request_, key)(data, instance=key)
        assert form.is_valid(), form.errors
        model_admin.save_model(request_, form.save(commit=False), form, change=True)
        key.refresh_from_db()
        assert key.is_active is False
        assert key.revoked_at is not None
        assert key.revoked_reason == "deactivated via admin"

    def test_rechecking_is_active_clears_the_revocation(
        self, model_admin: TenantAPIKeyAdmin, request_: HttpRequest, tenant: Tenant
    ) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        key.revoke(reason="compromised")
        form = model_admin.get_form(request_, key)(self.form_data(tenant, name="k"), instance=key)
        assert form.is_valid(), form.errors
        model_admin.save_model(request_, form.save(commit=False), form, change=True)
        key.refresh_from_db()
        assert key.is_active is True
        assert key.revoked_at is None
        assert key.revoked_reason == ""


    def test_deactivating_keeps_an_existing_revocation_record(
        self, model_admin: TenantAPIKeyAdmin, request_: HttpRequest, tenant: Tenant
    ) -> None:
        # An inconsistent row (active, yet carrying an old revoked_at): the
        # original audit values must survive being deactivated again.
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        when = timezone.now() - timedelta(days=3)
        TenantAPIKey.objects.filter(pk=key.pk).update(revoked_at=when, revoked_reason="earlier")
        key.refresh_from_db()
        data = self.form_data(tenant, name="k")
        del data["is_active"]
        form = model_admin.get_form(request_, key)(data, instance=key)
        assert form.is_valid(), form.errors
        model_admin.save_model(request_, form.save(commit=False), form, change=True)
        key.refresh_from_db()
        assert key.is_active is False
        assert key.revoked_at == when
        assert key.revoked_reason == "earlier"


class TestRevokeIsIdempotent:
    def test_repeat_revoke_keeps_the_original_reason_and_timestamp(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        key.revoke(reason="compromised")
        first_at = key.revoked_at

        key.revoke(reason="oops")

        key.refresh_from_db()
        assert key.revoked_reason == "compromised"
        assert key.revoked_at == first_at

    def test_revoking_an_admin_deactivated_key_still_records_the_revocation(
        self, tenant: Tenant
    ) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)
        key.revoke(reason="confirmed")
        assert key.revoked_at is not None
        assert key.revoked_reason == "confirmed"

    def test_reactivate_then_revoke_records_a_fresh_revocation(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        key.revoke(reason="first")
        key.reactivate()
        key.revoke(reason="second")
        assert key.revoked_reason == "second"


class TestExpiryBoundary:
    def test_is_expired_agrees_with_get_usable_keys_at_the_boundary(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        now = timezone.now()
        TenantAPIKey.objects.filter(pk=key.pk).update(expires_at=now)
        key.refresh_from_db()
        # Frozen clock: expires_at == now must count as expired everywhere.
        with mock.patch("django_tenant_apikeys.models.timezone.now", return_value=now):
            assert key.is_expired is True
            assert TenantAPIKey.objects.get_usable_keys().filter(pk=key.pk).exists() is False


class TestRotateHardening:
    def test_stale_instance_cannot_rotate_an_already_rotated_key(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        stale_a = TenantAPIKey.objects.get(pk=key.pk)
        stale_b = TenantAPIKey.objects.get(pk=key.pk)

        stale_a.rotate()
        with pytest.raises(ValueError, match="inactive or expired"):
            stale_b.rotate()

        assert TenantAPIKey.objects.filter(is_active=True).count() == 1

    def test_stale_instance_cannot_rotate_a_key_revoked_elsewhere(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        stale = TenantAPIKey.objects.get(pk=key.pk)
        key.revoke(reason="compromised")

        with pytest.raises(ValueError, match="inactive or expired"):
            stale.rotate()

        assert TenantAPIKey.objects.filter(is_active=True).count() == 0

    def test_rotation_copies_current_row_values_not_stale_ones(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant, scopes=["a:read"])
        stale = TenantAPIKey.objects.get(pk=key.pk)
        TenantAPIKey.objects.filter(pk=key.pk).update(scopes=["a:read", "a:write"])

        new, _raw2 = stale.rotate()

        assert new.scopes == ["a:read", "a:write"]

    def test_custom_prefix_survives_rotation(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant, prefix="acme")
        new, _raw2 = key.rotate()
        assert new.prefix.startswith("acme_live_")

    def test_custom_prefix_and_environment_survive_together(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, prefix="my_app", environment="test"
        )
        new, _raw2 = key.rotate()
        assert new.prefix.startswith("my_app_test_")

    def test_explicit_prefix_overrides_the_preserved_one(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant, prefix="acme")
        new, _raw2 = key.rotate(prefix="other")
        assert new.prefix.startswith("other_live_")

    def test_unrecognisable_stored_prefix_falls_back_to_the_default(self, tenant: Tenant) -> None:
        key = raw_create(tenant)
        TenantAPIKey.objects.filter(pk=key.pk).update(prefix="weird")
        key.refresh_from_db()
        new, _raw = key.rotate()
        assert new.prefix.startswith("tak_live_")

    def test_callers_instance_reflects_the_revocation(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        key.rotate()
        assert key.is_active is False
        assert key.revoked_reason == "rotated"

    def test_failed_rotation_leaves_the_original_untouched(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        with pytest.raises(ValueError, match="rate_limit"):
            key.rotate(rate_limit=-1)
        key.refresh_from_db()
        assert key.is_active is True
        assert TenantAPIKey.objects.count() == 1

    def test_reactivating_a_rotated_key_is_a_supported_rollback(self, tenant: Tenant) -> None:
        # Documented behaviour, not an accident: undoing a rotation that
        # didn't deploy is a legitimate use of reactivate().
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        new, _raw2 = key.rotate()
        key.reactivate()
        new.revoke(reason="rollback")
        assert key.is_valid is True
        assert new.is_valid is False

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="needs real row locks: SQLite ignores select_for_update()",
    )
    def test_concurrent_rotations_yield_one_replacement(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def worker() -> None:
            try:
                stale = TenantAPIKey.objects.get(pk=key.pk)
                barrier.wait()
                stale.rotate()
                outcomes.append("rotated")
            except ValueError:
                outcomes.append("refused")
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(outcomes) == ["refused", "rotated"]
        assert TenantAPIKey.objects.filter(is_active=True).count() == 1
