"""Unit tests for key generation, hashing, and scope verification."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from unittest import mock

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from django_tenant_apikeys.models import generate_api_key, hash_key
from tests.models import Tenant, TenantAPIKey, UnlinkedAPIKey

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Acme Inc.")


class TestHashKey:
    def test_returns_sha256_hex_digest(self) -> None:
        assert hash_key("hello") == hashlib.sha256(b"hello").hexdigest()

    def test_is_deterministic(self) -> None:
        assert hash_key("same-input") == hash_key("same-input")

    def test_different_inputs_differ(self) -> None:
        assert hash_key("input-a") != hash_key("input-b")


class TestGenerateAPIKey:
    def test_returns_three_values(self) -> None:
        assert len(generate_api_key()) == 3

    def test_full_key_format(self) -> None:
        full_key, key_prefix, _hashed_key = generate_api_key()
        assert full_key.startswith("tak_live_")
        assert full_key.startswith(key_prefix + ".")

    def test_custom_prefix(self) -> None:
        full_key, key_prefix, _hashed_key = generate_api_key(prefix="acme")
        assert full_key.startswith("acme_live_")
        assert key_prefix.startswith("acme_live_")

    def test_hashed_key_matches_full_key(self) -> None:
        full_key, _key_prefix, hashed_key = generate_api_key()
        assert hashed_key == hash_key(full_key)

    def test_prefix_is_the_portion_before_the_dot(self) -> None:
        full_key, key_prefix, _hashed_key = generate_api_key()
        assert full_key.split(".", 1)[0] == key_prefix

    def test_keys_are_unique_across_calls(self) -> None:
        first = generate_api_key()
        second = generate_api_key()
        assert first[0] != second[0]
        assert first[1] != second[1]
        assert first[2] != second[2]

    def test_prefix_fits_within_model_field_length(self) -> None:
        # 18 chars is the longest input prefix that still fits within the
        # model's prefix field (max_length=32) once "_live_<8 hex chars>"
        # (14 chars) is appended.
        _full_key, key_prefix, _hashed_key = generate_api_key(prefix="a" * 18)
        assert len(key_prefix) == 32

    def test_prefix_too_long_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="19 characters long"):
            generate_api_key(prefix="a" * 19)


class TestGenerateKeyClassmethod:
    def test_saves_and_returns_instance_and_raw_key(self, tenant: Tenant) -> None:
        instance, raw_key = TenantAPIKey.generate_key(name="CI key", tenant=tenant)
        assert instance.pk is not None
        assert instance.name == "CI key"
        assert instance.verify_key(raw_key) is True

    def test_does_not_persist_raw_key(self, tenant: Tenant) -> None:
        instance, raw_key = TenantAPIKey.generate_key(name="CI key", tenant=tenant)
        instance.refresh_from_db()
        assert raw_key not in instance.hashed_key
        assert instance.hashed_key == hash_key(raw_key)

    def test_accepts_custom_prefix(self, tenant: Tenant) -> None:
        instance, raw_key = TenantAPIKey.generate_key(name="CI key", tenant=tenant, prefix="acme")
        assert instance.prefix.startswith("acme_live_")
        assert raw_key.startswith("acme_live_")

    def test_default_scopes_is_empty_list(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="CI key", tenant=tenant)
        assert instance.scopes == []


class TestScopeValidation:
    def test_rejects_a_bare_string_instead_of_a_list(self, tenant: Tenant) -> None:
        with pytest.raises(ValueError, match="must be a list"):
            TenantAPIKey.generate_key(name="k", tenant=tenant, scopes="orders:read")

    def test_rejects_a_non_string_element(self, tenant: Tenant) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            TenantAPIKey.generate_key(name="k", tenant=tenant, scopes=[123])

    def test_rejects_an_empty_string_element(self, tenant: Tenant) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            TenantAPIKey.generate_key(name="k", tenant=tenant, scopes=[""])

    def test_accepts_a_tuple_of_scopes(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=("orders:read",)
        )
        assert instance.has_scope("orders:read") is True

    def test_accepts_duplicate_scopes(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read", "orders:read"]
        )
        assert instance.has_scope("orders:read") is True


class TestVerifyKey:
    def test_correct_key_verifies(self, tenant: Tenant) -> None:
        instance, raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert instance.verify_key(raw_key) is True

    def test_incorrect_key_fails(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert instance.verify_key("tak_live_wrong.wrong") is False

    def test_uses_constant_time_comparison(self, tenant: Tenant) -> None:
        instance, raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        with mock.patch("django_tenant_apikeys.models.secrets.compare_digest") as compare:
            compare.return_value = True
            assert instance.verify_key(raw_key) is True
            compare.assert_called_once_with(instance.hashed_key, hash_key(raw_key))


class TestIsExpired:
    def test_none_expires_at_is_never_expired(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert instance.expires_at is None
        assert instance.is_expired is False

    def test_future_expires_at_is_not_expired(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() + timedelta(days=1)
        )
        assert instance.is_expired is False

    def test_past_expires_at_is_expired(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() - timedelta(days=1)
        )
        assert instance.is_expired is True


class TestIsValid:
    def test_active_and_unexpired_is_valid(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert instance.is_valid is True

    def test_inactive_is_invalid(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)
        assert instance.is_valid is False

    def test_expired_is_invalid(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() - timedelta(days=1)
        )
        assert instance.is_valid is False


class TestRevoke:
    def test_deactivates_the_key(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        instance.revoke()
        assert instance.is_active is False
        assert instance.is_valid is False

    def test_sets_revoked_at(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert instance.revoked_at is None
        instance.revoke()
        assert instance.revoked_at is not None

    def test_records_the_given_reason(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        instance.revoke(reason="compromised")
        assert instance.revoked_reason == "compromised"

    def test_reason_defaults_to_empty_string(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        instance.revoke()
        assert instance.revoked_reason == ""

    def test_persists_to_the_database(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        instance.revoke(reason="compromised")

        instance.refresh_from_db()
        assert instance.is_active is False
        assert instance.revoked_at is not None
        assert instance.revoked_reason == "compromised"


class TestReactivate:
    def test_reverses_a_revocation(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        instance.revoke(reason="compromised")

        instance.reactivate()

        assert instance.is_active is True
        assert instance.is_valid is True

    def test_clears_revoked_at_and_reason(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        instance.revoke(reason="compromised")

        instance.reactivate()

        assert instance.revoked_at is None
        assert instance.revoked_reason == ""

    def test_persists_to_the_database(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        instance.revoke()
        instance.reactivate()

        instance.refresh_from_db()
        assert instance.is_active is True
        assert instance.revoked_at is None

    def test_does_not_override_expiration(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() - timedelta(days=1)
        )
        instance.revoke()

        instance.reactivate()

        assert instance.is_active is True
        assert instance.is_expired is True
        assert instance.is_valid is False


class TestRotate:
    def test_returns_a_new_instance_and_raw_key(self, tenant: Tenant) -> None:
        old_instance, _old_raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)

        new_instance, new_raw_key = old_instance.rotate()

        assert new_instance.pk != old_instance.pk
        assert new_instance.verify_key(new_raw_key) is True

    def test_old_key_becomes_unusable(self, tenant: Tenant) -> None:
        old_instance, old_raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)

        old_instance.rotate()

        old_instance.refresh_from_db()
        assert old_instance.is_active is False
        assert old_instance.verify_key(old_raw_key) is True  # hash still checks out...
        assert old_instance.is_valid is False  # ...but the key can no longer authenticate

    def test_old_key_is_revoked_with_reason(self, tenant: Tenant) -> None:
        old_instance, _old_raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)

        old_instance.rotate()

        assert old_instance.revoked_reason == "rotated"
        assert old_instance.revoked_at is not None

    def test_old_row_is_retained_not_deleted(self, tenant: Tenant) -> None:
        old_instance, _old_raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        old_pk = old_instance.pk

        old_instance.rotate()

        assert TenantAPIKey.objects.filter(pk=old_pk).exists()

    def test_tenant_is_preserved(self, tenant: Tenant) -> None:
        old_instance, _old_raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)

        new_instance, _new_raw_key = old_instance.rotate()

        assert new_instance.tenant == tenant

    def test_scopes_are_preserved_by_default(self, tenant: Tenant) -> None:
        old_instance, _old_raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"]
        )

        new_instance, _new_raw_key = old_instance.rotate()

        assert new_instance.scopes == ["orders:read"]

    def test_scopes_are_an_independent_list_not_shared_with_the_old_row(
        self, tenant: Tenant
    ) -> None:
        old_instance, _old_raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"]
        )

        new_instance, _new_raw_key = old_instance.rotate()
        new_instance.scopes.append("orders:write")

        assert old_instance.scopes == ["orders:read"]

    def test_scopes_can_be_overridden(self, tenant: Tenant) -> None:
        old_instance, _old_raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"]
        )

        new_instance, _new_raw_key = old_instance.rotate(scopes=["orders:*"])

        assert new_instance.scopes == ["orders:*"]

    def test_expiration_is_preserved_by_default(self, tenant: Tenant) -> None:
        expires_at = timezone.now() + timedelta(days=30)
        old_instance, _old_raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=expires_at
        )

        new_instance, _new_raw_key = old_instance.rotate()

        assert new_instance.expires_at == expires_at

    def test_expiration_can_be_overridden(self, tenant: Tenant) -> None:
        old_instance, _old_raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() + timedelta(days=30)
        )
        new_expiry = timezone.now() + timedelta(days=90)

        new_instance, _new_raw_key = old_instance.rotate(expires_at=new_expiry)

        assert new_instance.expires_at == new_expiry

    def test_name_is_preserved(self, tenant: Tenant) -> None:
        old_instance, _old_raw_key = TenantAPIKey.generate_key(name="CI deploy key", tenant=tenant)

        new_instance, _new_raw_key = old_instance.rotate()

        assert new_instance.name == "CI deploy key"

    def test_new_prefix_differs_from_old(self, tenant: Tenant) -> None:
        old_instance, _old_raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)

        new_instance, _new_raw_key = old_instance.rotate()

        assert new_instance.prefix != old_instance.prefix

    def test_raw_secret_is_not_persisted(self, tenant: Tenant) -> None:
        old_instance, _old_raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)

        new_instance, new_raw_key = old_instance.rotate()

        assert new_raw_key not in new_instance.hashed_key
        assert new_instance.hashed_key == hash_key(new_raw_key)

    def test_repeated_rotation(self, tenant: Tenant) -> None:
        gen1, _raw1 = TenantAPIKey.generate_key(name="k", tenant=tenant)
        gen2, raw2 = gen1.rotate()

        gen3, raw3 = gen2.rotate()

        gen1.refresh_from_db()
        gen2.refresh_from_db()
        assert gen1.is_valid is False
        assert gen2.is_valid is False
        assert gen3.is_valid is True
        assert gen3.verify_key(raw3) is True
        assert gen3.verify_key(raw2) is False

    def test_rotating_an_inactive_key_raises(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, is_active=False)

        with pytest.raises(ValueError, match="inactive or expired"):
            instance.rotate()

    def test_rotating_an_expired_key_raises(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, expires_at=timezone.now() - timedelta(days=1)
        )

        with pytest.raises(ValueError, match="inactive or expired"):
            instance.rotate()


class TestRecordUsage:
    def test_sets_last_used_at_when_previously_unset(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        assert instance.last_used_at is None

        instance.record_usage()

        assert instance.last_used_at is not None

    def test_persists_to_the_database_not_just_the_instance(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)

        instance.record_usage()

        instance.refresh_from_db()
        assert instance.last_used_at is not None

    def test_within_threshold_does_not_overwrite(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        instance.record_usage()
        first_seen = instance.last_used_at
        assert first_seen is not None

        instance.record_usage()

        assert instance.last_used_at == first_seen

    def test_updates_once_threshold_has_elapsed(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        stale = timezone.now() - instance.LAST_USED_THRESHOLD - timedelta(seconds=1)
        TenantAPIKey.objects.filter(pk=instance.pk).update(last_used_at=stale)
        instance.refresh_from_db()

        instance.record_usage()

        assert instance.last_used_at is not None
        assert instance.last_used_at > stale

    def test_default_threshold_is_five_minutes(self) -> None:
        assert TenantAPIKey.LAST_USED_THRESHOLD == timedelta(minutes=5)


class TestHasScope:
    def test_no_scopes_denies_everything(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, scopes=[])
        assert instance.has_scope("orders:read") is False

    def test_exact_scope_match(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:read"]
        )
        assert instance.has_scope("orders:read") is True
        assert instance.has_scope("orders:write") is False

    def test_global_wildcard_grants_everything(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, scopes=["*"])
        assert instance.has_scope("orders:read") is True
        assert instance.has_scope("anything:at-all") is True

    def test_namespaced_wildcard_grants_within_namespace(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:*"]
        )
        assert instance.has_scope("orders:read") is True
        assert instance.has_scope("orders:write") is True
        assert instance.has_scope("billing:read") is False

    def test_namespaced_wildcard_does_not_match_bare_namespace(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(
            name="k", tenant=tenant, scopes=["orders:*"]
        )
        assert instance.has_scope("orders") is False


class TestManager:
    def test_get_from_key_finds_matching_row(self, tenant: Tenant) -> None:
        instance, raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        found = TenantAPIKey.objects.get_from_key(raw_key)
        assert found.pk == instance.pk

    def test_get_from_key_raises_does_not_exist_for_unknown_prefix(self) -> None:
        with pytest.raises(TenantAPIKey.DoesNotExist):
            TenantAPIKey.objects.get_from_key("tak_live_doesnotexist.secret")

    def test_get_usable_keys_excludes_inactive(self, tenant: Tenant) -> None:
        active, _raw_key = TenantAPIKey.generate_key(name="active", tenant=tenant)
        TenantAPIKey.generate_key(name="inactive", tenant=tenant, is_active=False)
        assert list(TenantAPIKey.objects.get_usable_keys()) == [active]

    def test_get_usable_keys_excludes_expired(self, tenant: Tenant) -> None:
        active, _raw_key = TenantAPIKey.generate_key(name="active", tenant=tenant)
        TenantAPIKey.generate_key(
            name="expired", tenant=tenant, expires_at=timezone.now() - timedelta(days=1)
        )
        assert list(TenantAPIKey.objects.get_usable_keys()) == [active]

    def test_get_usable_keys_includes_never_expiring(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant, expires_at=None)
        assert instance in TenantAPIKey.objects.get_usable_keys()


class TestModelMeta:
    def test_str_includes_name_and_prefix(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="CI key", tenant=tenant)
        assert str(instance) == f"CI key ({instance.prefix})"

    def test_repr_does_not_leak_hashed_key(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="CI key", tenant=tenant)
        assert instance.hashed_key not in repr(instance)

    def test_prefix_is_unique(self, tenant: Tenant) -> None:
        instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                TenantAPIKey.objects.create(
                    name="dup",
                    tenant=tenant,
                    prefix=instance.prefix,
                    hashed_key="x" * 64,
                )

    def test_ordering_meta_is_newest_first(self) -> None:
        assert TenantAPIKey._meta.ordering == ("-created_at",)


class TestUnlinkedAPIKey:
    def test_works_without_a_tenant_relation(self) -> None:
        instance, raw_key = UnlinkedAPIKey.generate_key(name="no tenant")
        assert instance.verify_key(raw_key) is True
        assert not hasattr(instance, "tenant")
