# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) —
while it's pre-1.0, that means the public API can still change between minor
versions if a `0.x` release note says so.

## [Unreleased]

No unreleased changes yet.

## [0.4.0] - 2026-09-06

### Added

- `AbstractTenantAPIKey.rate_limit` / `.rate_limit_window` -- optional
  per-key rate limiting. `rate_limit_window` is one of `"second"`,
  `"minute"`, `"hour"`, `"day"` (default `"minute"`); a key with no
  `rate_limit` set is never throttled. `django_tenant_apikeys.ratelimit`
  has the framework-agnostic core: `check_rate_limit()`, a
  `RateLimitResult` (`allowed`/`limit`/`remaining`/`reset_at`/`retry_after`),
  and `CacheRateLimitBackend`, the default storage backend -- a fixed-window
  counter on top of Django's cache framework using `cache.add()`/`cache.incr()`
  rather than a get-then-set round trip, so concurrent requests against the
  same key can't race each other into an incorrect count. Swappable via the
  new `TENANT_API_KEY_RATE_LIMIT_BACKEND` setting.
- `AbstractTenantAPIKey.allowed_ips` -- optional IP/CIDR allowlist (IPv4 and
  IPv6, individual addresses or networks), parsed with the standard library
  `ipaddress` module. A key with an empty `allowed_ips` accepts any IP, same
  as before this release. `AbstractTenantAPIKey.is_ip_allowed(client_ip)`
  checks it. `django_tenant_apikeys.ip.get_client_ip()` resolves the
  request's client IP -- `REMOTE_ADDR` only, unless the new
  `TENANT_API_KEY_TRUSTED_PROXY_HEADER` setting explicitly names a header to
  trust instead (never trusted implicitly, since `X-Forwarded-For` and
  similar headers are trivially spoofable by any client).
- `AbstractTenantAPIKey.metadata` -- an optional `JSONField` (default `{}`)
  for arbitrary application-defined data. Not interpreted by this library at
  all; it's just carried on the row.
- `AbstractTenantAPIKey.environment` -- `"production"` (default),
  `"staging"`, `"development"`, or `"test"`. Authoritative for application
  code, unlike the key's prefix. `generate_key()`/`generate_api_key()` still
  encode a coarser `_live_`/`_test_` segment into the prefix from this value
  (production and staging both get `_live_`; development and test both get
  `_test_`) for a quick eyeball in a log line, but the database column is
  what actually governs behavior.
- `django_tenant_apikeys.permissions.HasAllowedIP` and `.WithinRateLimit` --
  DRF permission classes enforcing the two policies above, meant to sit
  alongside the existing `HasAPIKeyScope` in `permission_classes`.
  `WithinRateLimit` raises DRF's `Throttled` (429, with `Retry-After`) once
  the limit is hit, and sets `X-RateLimit-Limit`/`X-RateLimit-Remaining`/
  `X-RateLimit-Reset` on the response either way.
- Django Ninja has no permission-class system to hook these into, so
  `is_ip_allowed()` and `check_rate_limit()` are meant to be called inline
  in a view, exactly like scope checks already are -- see the updated
  `TenantAPIKeyAuth` docstring and the README.
- Django admin: `environment` in `list_display` and `list_filter`, plus
  `expires_at` in `list_filter`. `rate_limit`, `rate_limit_window`,
  `allowed_ips`, and `metadata` are all plain editable fields on the change
  form, same as `scopes`.

### Changed

- `generate_api_key()` and `AbstractTenantAPIKey.generate_key()` now accept
  `environment`, `rate_limit`, `rate_limit_window`, `allowed_ips`, and
  `metadata`, all optional. `generate_key()` validates `allowed_ips` (must
  parse as IPs/CIDR networks) and `rate_limit`/`rate_limit_window`
  (positive integer, valid window) up front, the same way it's already
  validated `scopes`.
- `rotate()` now also carries `environment`, `rate_limit`,
  `rate_limit_window`, `allowed_ips`, and `metadata` over to the new key
  (independent copies for the JSON fields, same as `scopes` already was),
  unless overridden.

### Security

- `HasAllowedIP` and `get_client_ip()` never trust `X-Forwarded-For` or
  similar headers unless `TENANT_API_KEY_TRUSTED_PROXY_HEADER` opts in
  explicitly -- see the README's IP restrictions section for why.
- `CacheRateLimitBackend`'s counter uses `cache.add()`/`cache.incr()`, both
  atomic on any real cache backend, instead of a get-then-set pair that
  concurrent requests could race.
- Rate-limit cache keys are scoped by the concrete key model's class name in
  addition to its primary key, so two different `AbstractTenantAPIKey`
  subclasses can never collide on the same counter.

### Compatibility

`environment`, `rate_limit`, `rate_limit_window`, `allowed_ips`, and
`metadata` are new fields on `AbstractTenantAPIKey`; run
`manage.py makemigrations` after upgrading, same as any other schema change
to an abstract base class. Every new field has a backward-compatible
default (`environment="production"`, `rate_limit=None`,
`rate_limit_window="minute"`, `allowed_ips=[]`, `metadata={}`), so existing
keys keep authenticating exactly as before -- none of this release's
policies apply unless you explicitly set them on a key.
`OrganizationAPIKey.generate_key(name=..., tenant=...)` and everything else
from 0.1-0.3 (scopes, rotation, revocation, the management commands) is
unchanged.

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

[Unreleased]: https://github.com/stackadnan/django-tenant-apikeys/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/stackadnan/django-tenant-apikeys/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/stackadnan/django-tenant-apikeys/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/stackadnan/django-tenant-apikeys/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/stackadnan/django-tenant-apikeys/releases/tag/v0.1.0
