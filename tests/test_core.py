"""Tests for django_tenant_apikeys.core.authenticate_key -- the single
authentication path both the DRF and Django Ninja backends use."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import pytest
from django.test import override_settings
from django.utils import timezone

from django_tenant_apikeys.core import (
    APIKeyRejected,
    RejectionReason,
    authenticate_key,
    client_message,
    split_raw_key,
)
from django_tenant_apikeys.signals import api_key_rejected
from tests.models import Tenant, TenantAPIKey, UnlinkedAPIKey

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


def rejection(raw_key: str, **kwargs: Any) -> APIKeyRejected:
    with pytest.raises(APIKeyRejected) as excinfo:
        authenticate_key(raw_key, model=TenantAPIKey, **kwargs)
    return excinfo.value


class TestSplitRawKey:
    def test_splits_a_generated_key(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        parts = split_raw_key(raw)
        assert parts is not None
        assert raw == f"{parts[0]}.{parts[1]}"

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "nodot",
            ".secret",
            "prefix.",
            "a" * 33 + ".secret",  # prefix longer than the column
            "tak_live_00000000." + "s" * 200,  # implausibly long
            "tak_live_00000000.sec\x00ret",  # NUL
            "tak_live_00000000.sec\nret",  # control character / whitespace
            "tak_live_00000000.sec ret",
            "tak_live_00000000.sec​ret",  # zero-width space is not printable
        ],
    )
    def test_rejects_anything_that_cannot_be_a_generated_key(self, bad: str) -> None:
        assert split_raw_key(bad) is None

    def test_malformed_input_never_reaches_the_database(
        self, django_assert_num_queries: Any
    ) -> None:
        with django_assert_num_queries(0):
            assert rejection("no-dot-here").reason is RejectionReason.MALFORMED
            assert rejection("x" * 500).reason is RejectionReason.MALFORMED


class TestRejectionMatrix:
    def test_valid_key_authenticates(self, tenant: Tenant) -> None:
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert authenticate_key(raw, model=TenantAPIKey).pk == key.pk

    def test_unknown_prefix(self) -> None:
        exc = rejection("tak_live_00000000.doesnotexist")
        assert exc.reason is RejectionReason.UNKNOWN_KEY
        assert exc.api_key is None

    def test_wrong_secret(self, tenant: Tenant) -> None:
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        exc = rejection(raw[:-1] + ("A" if raw[-1] != "A" else "B"))
        assert exc.reason is RejectionReason.BAD_SECRET
        assert exc.api_key is not None
        assert exc.api_key.pk == key.pk

    def test_inactive_key(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)
        assert rejection(raw).reason is RejectionReason.INACTIVE

    def test_revoked_key(self, tenant: Tenant) -> None:
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        key.revoke(reason="compromised")
        assert rejection(raw).reason is RejectionReason.INACTIVE

    def test_expired_key(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert rejection(raw).reason is RejectionReason.EXPIRED

    def test_secret_is_checked_before_state(self, tenant: Tenant) -> None:
        # A revoked key with a wrong secret must look like any wrong secret,
        # not reveal that it exists and was revoked.
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        key.revoke()
        assert rejection(raw + "x").reason is RejectionReason.BAD_SECRET

    def test_wrong_ip(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["203.0.113.0/24"]
        )
        exc = rejection(raw, client_ip="198.51.100.1")
        assert exc.reason is RejectionReason.IP_NOT_ALLOWED
        assert exc.is_policy_violation is True

    def test_allowed_ip(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["203.0.113.0/24"]
        )
        assert authenticate_key(raw, model=TenantAPIKey, client_ip="203.0.113.9")

    def test_unknown_ip_fails_closed_for_a_restricted_key(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(
            name="k", tenant=tenant, allowed_ips=["203.0.113.0/24"]
        )
        assert rejection(raw).reason is RejectionReason.IP_NOT_ALLOWED

    def test_unrestricted_key_needs_no_ip(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert authenticate_key(raw, model=TenantAPIKey, client_ip="")

    def test_authentication_failures_are_not_policy_violations(self) -> None:
        assert rejection("tak_live_00000000.x").is_policy_violation is False

    def test_suspended_tenant(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        tenant.is_active = False
        tenant.save()
        exc = rejection(raw)
        assert exc.reason is RejectionReason.TENANT_NOT_ALLOWED
        assert exc.is_policy_violation is True


class TestEnvironmentEnforcement:
    def test_no_setting_means_no_enforcement(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, environment="test")
        assert authenticate_key(raw, model=TenantAPIKey)

    @override_settings(TENANT_API_KEY_ALLOWED_ENVIRONMENTS={"production"})
    def test_key_from_another_environment_is_rejected(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, environment="test")
        exc = rejection(raw)
        assert exc.reason is RejectionReason.ENVIRONMENT
        assert exc.is_policy_violation is True

    @override_settings(TENANT_API_KEY_ALLOWED_ENVIRONMENTS=["production", "staging"])
    def test_any_listed_environment_is_accepted(self, tenant: Tenant) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, environment="staging")
        assert authenticate_key(raw, model=TenantAPIKey)

    @override_settings(TENANT_API_KEY_ALLOWED_ENVIRONMENTS=[])
    def test_an_empty_list_rejects_everything(self, tenant: Tenant) -> None:
        # An empty allowlist is "nothing is allowed", not "unset".
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert rejection(raw).reason is RejectionReason.ENVIRONMENT


class TestModelResolution:
    def test_defaults_to_the_configured_model(self, tenant: Tenant) -> None:
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert authenticate_key(raw).pk == key.pk

    def test_a_model_without_a_tenant_relation_works(self) -> None:
        key, raw = UnlinkedAPIKey.generate_key(name="k")
        assert authenticate_key(raw, model=UnlinkedAPIKey).pk == key.pk

    def test_tenant_is_joined_into_the_lookup(
        self, tenant: Tenant, django_assert_num_queries: Any
    ) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        # 1 SELECT (with the tenant joined in) + 1 UPDATE for last_used_at --
        # reading ``.tenant`` afterwards costs nothing.
        with django_assert_num_queries(2):
            api_key = authenticate_key(raw, model=TenantAPIKey)
            assert api_key.tenant.name == "Acme Inc."


class TestRecordIp:
    def test_not_recorded_by_default(self, tenant: Tenant) -> None:
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        authenticate_key(raw, model=TenantAPIKey, client_ip="203.0.113.9")
        key.refresh_from_db()
        assert key.last_used_at is not None
        assert key.last_used_ip is None

    @override_settings(TENANT_API_KEY_RECORD_IP=True)
    def test_recorded_when_enabled(self, tenant: Tenant) -> None:
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        authenticate_key(raw, model=TenantAPIKey, client_ip="203.0.113.9")
        key.refresh_from_db()
        assert key.last_used_ip == "203.0.113.9"

    @override_settings(TENANT_API_KEY_RECORD_IP=True)
    def test_a_changed_ip_is_written_immediately(self, tenant: Tenant) -> None:
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        authenticate_key(raw, model=TenantAPIKey, client_ip="203.0.113.9")
        # Well inside LAST_USED_THRESHOLD, but the address changed.
        authenticate_key(raw, model=TenantAPIKey, client_ip="203.0.113.10")
        key.refresh_from_db()
        assert key.last_used_ip == "203.0.113.10"

    @override_settings(TENANT_API_KEY_RECORD_IP=True)
    def test_an_unchanged_ip_stays_throttled(
        self, tenant: Tenant, django_assert_num_queries: Any
    ) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        authenticate_key(raw, model=TenantAPIKey, client_ip="203.0.113.9")
        with django_assert_num_queries(1):  # the SELECT only -- no write
            authenticate_key(raw, model=TenantAPIKey, client_ip="203.0.113.9")

    @override_settings(TENANT_API_KEY_RECORD_IP=True)
    def test_garbage_is_never_stored(self, tenant: Tenant) -> None:
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        authenticate_key(raw, model=TenantAPIKey, client_ip="not an ip")
        key.refresh_from_db()
        assert key.last_used_ip is None
        assert key.last_used_at is not None


class TestRejectionSignal:
    def test_sent_for_every_rejection_with_the_reason(self, tenant: Tenant) -> None:
        received: list[dict[str, Any]] = []

        def receiver(sender: type, **kwargs: Any) -> None:
            received.append({"sender": sender, **kwargs})

        api_key_rejected.connect(receiver, weak=False)
        try:
            key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
            rejection("tak_live_00000000.nope", client_ip="203.0.113.9")
            key.revoke()
            rejection(raw)
        finally:
            api_key_rejected.disconnect(receiver)

        assert [r["reason"] for r in received] == ["unknown_key", "inactive"]
        assert received[0]["sender"] is TenantAPIKey
        assert received[0]["api_key"] is None
        assert received[0]["client_ip"] == "203.0.113.9"
        assert received[1]["api_key"].pk == key.pk

    def test_a_broken_receiver_cannot_turn_a_rejection_into_a_500(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def broken(sender: type, **kwargs: Any) -> None:
            raise RuntimeError("audit sink is down")

        api_key_rejected.connect(broken, weak=False)
        try:
            with caplog.at_level(logging.ERROR, logger="django_tenant_apikeys"):
                exc = rejection("tak_live_00000000.nope")
        finally:
            api_key_rejected.disconnect(broken)

        assert exc.reason is RejectionReason.UNKNOWN_KEY  # still a clean rejection
        assert "audit sink is down" in caplog.text


class TestRejectionLogging:
    def test_logs_reason_prefix_and_ip_for_a_matched_key(
        self, tenant: Tenant, caplog: pytest.LogCaptureFixture
    ) -> None:
        key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)
        with caplog.at_level(logging.WARNING, logger="django_tenant_apikeys"):
            rejection(raw, client_ip="203.0.113.9")
        assert "reason=inactive" in caplog.text
        assert f"prefix={key.prefix}" in caplog.text
        assert "203.0.113.9" in caplog.text

    def test_never_logs_the_secret(self, tenant: Tenant, caplog: pytest.LogCaptureFixture) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        secret = raw.partition(".")[2]
        with caplog.at_level(logging.DEBUG, logger="django_tenant_apikeys"):
            rejection(raw[:-1] + ("A" if raw[-1] != "A" else "B"))  # wrong secret
            rejection(raw + "x", client_ip="203.0.113.9")
        assert secret[:-1] not in caplog.text

    def test_a_key_pasted_without_its_dot_is_not_logged_as_a_prefix(
        self, tenant: Tenant, caplog: pytest.LogCaptureFixture
    ) -> None:
        _key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        secret_only = raw.partition(".")[2]
        with caplog.at_level(logging.DEBUG, logger="django_tenant_apikeys"):
            rejection(secret_only)
        assert secret_only not in caplog.text
        assert "prefix=-" in caplog.text

    def test_unknown_key_text_is_never_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="django_tenant_apikeys"):
            rejection("attacker_supplied_text.abc")
        assert "attacker_supplied_text" not in caplog.text

    def test_a_hostile_client_ip_cannot_forge_log_lines(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        hostile = "1.2.3.4\nWARNING forged: reason=admin_login " + "x" * 200
        with caplog.at_level(logging.DEBUG, logger="django_tenant_apikeys"):
            rejection("tak_live_00000000.nope", client_ip=hostile)
        assert "\n" not in caplog.records[0].getMessage()
        assert len(caplog.records[0].getMessage()) < 200


class TestClientMessages:
    @pytest.mark.parametrize(
        "reason",
        [RejectionReason.MALFORMED, RejectionReason.UNKNOWN_KEY, RejectionReason.BAD_SECRET],
    )
    def test_guessing_reasons_all_read_the_same(self, reason: RejectionReason) -> None:
        assert client_message(reason) == "Invalid API key."

    def test_state_reasons_are_specific(self) -> None:
        assert "deactivated" in client_message(RejectionReason.INACTIVE)
        assert "expired" in client_message(RejectionReason.EXPIRED)
