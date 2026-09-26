"""Rotation semantics: ``rotated_from`` lineage, grace periods, and the
lifecycle signals ``generate_key()``/``revoke()``/``rotate()`` send."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from django_tenant_apikeys.signals import (
    api_key_created,
    api_key_revoked,
    api_key_rotated,
)
from tests.models import Tenant, TenantAPIKey

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


class TestRotatedFrom:
    def test_new_key_points_back_at_the_old_one(self, tenant: Tenant) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        new, _raw2 = old.rotate()
        new.refresh_from_db()
        assert new.rotated_from_id == old.pk

    def test_reverse_accessor_lists_replacements(self, tenant: Tenant) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        new, _raw2 = old.rotate()
        assert list(old.rotated_to.all()) == [new]  # type: ignore[attr-defined]

    def test_a_fresh_key_has_no_lineage(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert key.rotated_from is None

    def test_lineage_cannot_be_overridden(self, tenant: Tenant) -> None:
        other, _raw = TenantAPIKey.generate_key(name="other", tenant=tenant)
        old, _raw2 = TenantAPIKey.generate_key(name="k", tenant=tenant)
        new, _raw3 = old.rotate(rotated_from=other)
        assert new.rotated_from == old

    def test_a_chain_of_rotations_is_walkable(self, tenant: Tenant) -> None:
        gen1, _r1 = TenantAPIKey.generate_key(name="k", tenant=tenant)
        gen2, _r2 = gen1.rotate()
        gen3, _r3 = gen2.rotate()
        assert gen3.rotated_from == gen2
        assert gen3.rotated_from.rotated_from == gen1  # type: ignore[union-attr]

    def test_deleting_the_old_row_keeps_the_new_key(self, tenant: Tenant) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        new, _raw2 = old.rotate()
        old.delete()
        new.refresh_from_db()
        assert new.rotated_from is None
        assert new.is_valid

    def test_rotation_does_not_copy_usage_state(self, tenant: Tenant) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        TenantAPIKey.objects.filter(pk=old.pk).update(
            last_used_at=timezone.now(), last_used_ip="203.0.113.9"
        )
        old.refresh_from_db()
        new, _raw2 = old.rotate()
        assert new.last_used_at is None
        assert new.last_used_ip is None


class TestGracePeriod:
    def test_old_key_stays_valid_and_expires_at_the_end_of_the_grace(
        self, tenant: Tenant
    ) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        before = timezone.now()
        new, _raw2 = old.rotate(grace_period=timedelta(days=7))
        after = timezone.now()

        old.refresh_from_db()
        assert old.is_active is True
        assert old.is_valid is True
        assert old.revoked_at is None
        assert old.expires_at is not None
        assert before + timedelta(days=7) <= old.expires_at <= after + timedelta(days=7)
        assert new.is_valid is True

    def test_callers_instance_reflects_the_new_expiry(self, tenant: Tenant) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        old.rotate(grace_period=timedelta(days=1))
        assert old.expires_at is not None
        assert old.is_active is True

    def test_grace_never_extends_a_key_that_expires_sooner(self, tenant: Tenant) -> None:
        soon = timezone.now() + timedelta(hours=2)
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant, expires_at=soon)
        old.rotate(grace_period=timedelta(days=30))
        old.refresh_from_db()
        assert old.expires_at == soon

    def test_new_key_inherits_the_original_expiry_not_the_grace_cutoff(
        self, tenant: Tenant
    ) -> None:
        later = timezone.now() + timedelta(days=90)
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant, expires_at=later)
        new, _raw2 = old.rotate(grace_period=timedelta(days=1))
        assert new.expires_at == later

    def test_the_old_key_stops_at_the_end_of_the_grace(self, tenant: Tenant) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        old.rotate(grace_period=timedelta(days=1))
        TenantAPIKey.objects.filter(pk=old.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        old.refresh_from_db()
        assert old.is_valid is False

    @pytest.mark.parametrize("bad", [timedelta(0), timedelta(days=-1)])
    def test_a_non_positive_grace_period_is_rejected(self, tenant: Tenant, bad: timedelta) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        with pytest.raises(ValueError, match="grace_period"):
            old.rotate(grace_period=bad)
        assert TenantAPIKey.objects.count() == 1

    def test_a_key_with_a_live_replacement_cannot_be_rotated_again(
        self, tenant: Tenant
    ) -> None:
        # Otherwise a second rotate() during the grace window would leave
        # *two* live replacements of the same key.
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        old.rotate(grace_period=timedelta(days=7))
        stale = TenantAPIKey.objects.get(pk=old.pk)
        with pytest.raises(ValueError, match="live replacement"):
            stale.rotate(grace_period=timedelta(days=7))
        assert TenantAPIKey.objects.filter(rotated_from=old).count() == 1

    def test_rotating_again_is_allowed_once_the_replacement_is_gone(
        self, tenant: Tenant
    ) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        first, _raw2 = old.rotate(grace_period=timedelta(days=7))
        first.revoke(reason="rolled back")
        second, _raw3 = old.rotate(grace_period=timedelta(days=7))
        assert second.pk != first.pk
        assert second.rotated_from == old

    def test_rotating_after_the_replacement_expired_is_allowed(self, tenant: Tenant) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        first, _raw2 = old.rotate(grace_period=timedelta(days=7))
        TenantAPIKey.objects.filter(pk=first.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        second, _raw3 = old.rotate()
        assert second.rotated_from == old

    def test_immediate_rotation_is_unchanged(self, tenant: Tenant) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        old.rotate()
        old.refresh_from_db()
        assert old.is_active is False
        assert old.revoked_reason == "rotated"
        assert old.expires_at is None


class SignalRecorder:
    def __init__(self, *signals: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._signals = signals
        self._receivers: list[Any] = []

    def __enter__(self) -> SignalRecorder:
        for signal in self._signals:
            def receiver(sender: type, _signal: Any = signal, **kwargs: Any) -> None:
                self.calls.append((self._name(_signal), {"sender": sender, **kwargs}))

            signal.connect(receiver, weak=False)
            self._receivers.append((signal, receiver))
        return self

    def __exit__(self, *exc: object) -> None:
        for signal, receiver in self._receivers:
            signal.disconnect(receiver)

    @staticmethod
    def _name(signal: Any) -> str:
        return {
            id(api_key_created): "created",
            id(api_key_revoked): "revoked",
            id(api_key_rotated): "rotated",
        }[id(signal)]

    @property
    def names(self) -> list[str]:
        return [name for name, _kwargs in self.calls]


class TestLifecycleSignals:
    def test_generate_key_sends_created(self, tenant: Tenant) -> None:
        with SignalRecorder(api_key_created) as recorder:
            key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert recorder.names == ["created"]
        assert recorder.calls[0][1]["api_key"].pk == key.pk
        assert recorder.calls[0][1]["sender"] is TenantAPIKey

    def test_a_failed_generate_key_sends_nothing(self, tenant: Tenant) -> None:
        with SignalRecorder(api_key_created) as recorder:
            with pytest.raises(ValueError):
                TenantAPIKey.generate_key(name="k", tenant=tenant, scopes="nope")
        assert recorder.calls == []

    def test_revoke_sends_revoked_with_the_reason(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        with SignalRecorder(api_key_revoked) as recorder:
            key.revoke(reason="compromised")
        assert recorder.names == ["revoked"]
        assert recorder.calls[0][1]["reason"] == "compromised"

    def test_a_repeat_revoke_sends_nothing(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        key.revoke(reason="compromised")
        with SignalRecorder(api_key_revoked) as recorder:
            key.revoke(reason="again")
        assert recorder.calls == []

    def test_immediate_rotation_sends_created_revoked_and_rotated(self, tenant: Tenant) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        with SignalRecorder(api_key_created, api_key_revoked, api_key_rotated) as recorder:
            new, _raw2 = old.rotate()
        assert recorder.names == ["created", "revoked", "rotated"]
        rotated = recorder.calls[-1][1]
        assert rotated["old_key"].pk == old.pk
        assert rotated["new_key"].pk == new.pk
        assert rotated["grace_period"] is None

    def test_a_graceful_rotation_revokes_nothing(self, tenant: Tenant) -> None:
        old, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
        with SignalRecorder(api_key_created, api_key_revoked, api_key_rotated) as recorder:
            old.rotate(grace_period=timedelta(days=3))
        assert recorder.names == ["created", "rotated"]
        assert recorder.calls[-1][1]["grace_period"] == timedelta(days=3)

    def test_a_refused_rotation_sends_nothing(self, tenant: Tenant) -> None:
        key, _raw = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)
        with SignalRecorder(api_key_created, api_key_revoked, api_key_rotated) as recorder:
            with pytest.raises(ValueError):
                key.rotate()
        assert recorder.calls == []

    def test_a_broken_receiver_cannot_break_key_operations(
        self, tenant: Tenant, caplog: pytest.LogCaptureFixture
    ) -> None:
        def broken(sender: type, **kwargs: Any) -> None:
            raise RuntimeError("audit sink is down")

        api_key_created.connect(broken, weak=False)
        api_key_revoked.connect(broken, weak=False)
        try:
            key, raw = TenantAPIKey.generate_key(name="k", tenant=tenant)
            key.revoke()
        finally:
            api_key_created.disconnect(broken)
            api_key_revoked.disconnect(broken)
        assert key.verify_key(raw)
        assert key.is_active is False
        assert "audit sink is down" in caplog.text
