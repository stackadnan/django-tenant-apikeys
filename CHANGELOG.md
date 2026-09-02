# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) —
while it's pre-1.0, that means the public API can still change between minor
versions if a `0.x` release note says so.

## [Unreleased]

No unreleased changes yet.

## [0.3.0] - 2026-09-03

### Added

- `AbstractTenantAPIKey.revoke(reason="")` / `.reactivate()` — an explicit
  lifecycle on top of the existing `is_active` flag. `revoked_at` and
  `revoked_reason` are new fields, audit metadata only; authentication
  still only ever checks `is_active`, so there's no second enforcement path.
- `AbstractTenantAPIKey.rotate(prefix="tak", **overrides)` — issues a
  replacement key with the same tenant/scopes/expiration (or overrides),
  revokes the original with `reason="rotated"`, and keeps the old row for
  audit history. Wrapped in `transaction.atomic()`; raises `ValueError` on
  a key that's already inactive or expired.
- `django_tenant_apikeys.ninja.TenantAPIKeyAuth` — a first-class Django
  Ninja `APIKeyHeader` backend (`[ninja]` extra), replacing the hand-rolled
  recipe previously in the README. Same rejection rules, `record_usage()`
  call, and `request.tenant` attachment as `TenantAPIKeyAuthentication`.
- `manage.py tenant_api_key_revoke <prefix> [--reason TEXT]` and
  `manage.py tenant_api_key_rotate <prefix>` management commands. Both
  resolve the model generically via `TENANT_API_KEY_MODEL`. No
  `tenant_api_key_create` — see the README's Management commands section
  for why.
- `generate_key()` now validates `scopes` (must be a list of non-empty
  strings) and raises `ValueError` immediately on a mistake like
  `scopes="orders:read"`, instead of silently misbehaving later in
  `has_scope()`.
- Django admin: a computed **Status** column (`Active`/`Revoked`/
  `Inactive`/`Expired`) and a **Revoke selected API keys** bulk action.
- CI now also runs the full test suite against PostgreSQL
  (`tests/settings_postgres.py`), in addition to the existing SQLite-backed
  matrix across Python 3.10-3.12 and Django 4.2/5.2.

### Migration required

`revoked_at` and `revoked_reason` are new fields on `AbstractTenantAPIKey`;
run `manage.py makemigrations` after upgrading, same as `last_used_at` in
0.2.0.

## [0.2.0] - 2026-08-30

### Added

- `AbstractTenantAPIKey.last_used_at` — records when a key last
  authenticated successfully. `TenantAPIKeyAuthentication` updates it
  automatically after every successful authentication; the Django Ninja
  recipe in the README does too.
- `AbstractTenantAPIKey.record_usage()` — the method behind the above,
  throttled by a new `LAST_USED_THRESHOLD` class attribute (5 minutes by
  default) so a hot endpoint doesn't turn into a database write on every
  single request. Override `LAST_USED_THRESHOLD` on a subclass to change
  the granularity.

### Migration required

`last_used_at` is a new field on `AbstractTenantAPIKey`, so every project
with an existing concrete subclass needs to run `manage.py makemigrations`
after upgrading, same as any other schema change to an abstract base class.

## [0.1.0] - 2026-08-22

Initial release.

### Added

- `AbstractTenantAPIKey` — abstract model with `name`, `prefix`,
  `hashed_key`, `scopes`, `is_active`, `created_at`, `expires_at`, plus
  `generate_key()`, `verify_key()`, `has_scope()`, `is_expired`, `is_valid`.
- `generate_api_key()` and `hash_key()` — the underlying key-generation and
  SHA-256 hashing utilities, usable independently of the model.
- `get_api_key_model()` — resolves the concrete key model from
  `settings.TENANT_API_KEY_MODEL`.
- `TenantAPIKeyManager` — adds `get_from_key()` and `get_usable_keys()`.
- `TenantAPIKeyAuthentication` — Django REST Framework authentication
  backend, with `Api-Key <key>` header parsing, expiration/deactivation
  handling, and automatic `request.tenant` attachment.
- `HasAPIKeyScope` — DRF permission class enforcing a view's
  `required_scopes` against the authenticated key's scopes.
- `TenantAPIKeyAdmin` — Django admin integration with masked key display and
  one-time raw-key reveal on creation.
- Documented recipe for Django Ninja integration (no dedicated module
  shipped — see the README).

[Unreleased]: https://github.com/stackadnan/django-tenant-apikeys/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/stackadnan/django-tenant-apikeys/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/stackadnan/django-tenant-apikeys/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/stackadnan/django-tenant-apikeys/releases/tag/v0.1.0
