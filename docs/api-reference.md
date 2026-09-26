# API reference

The public surface of every module. Anything not listed here (names
prefixed with `_`) is an internal implementation detail, not covered by
this package's compatibility guarantees.

## `django_tenant_apikeys.models`

No DRF or Ninja dependency — importable with just the base package.

### `AbstractTenantAPIKey`

Abstract model. Subclass it and add a `tenant` relation (see
[Multi-tenancy](multi-tenancy.md)).

**Fields:** `name`, `prefix`, `hashed_key`, `scopes`, `environment`,
`rate_limit`, `rate_limit_window`, `allowed_ips`, `metadata`, `is_active`,
`created_at`, `expires_at`, `last_used_at`, `revoked_at`, `revoked_reason`.

**Class methods**

- `generate_key(cls, *, prefix="tak", **kwargs) -> tuple[instance, raw_key]`
  — creates and saves a new key. `**kwargs` go straight to the model
  constructor (`name`, `scopes`, `expires_at`, `environment`, `rate_limit`,
  `rate_limit_window`, `allowed_ips`, `metadata`, a `tenant` relation,
  etc). Raises `ValueError` if `scopes`/`allowed_ips` isn't a list of
  non-empty strings (each `allowed_ips` entry must also parse as an IP or
  CIDR network), if `rate_limit` isn't a positive integer, or if
  `rate_limit_window`/`environment` isn't a valid choice.

**Instance methods**

- `verify_key(self, raw_key: str) -> bool` — constant-time check against
  the stored hash.
- `has_scope(self, required_scope: str) -> bool` — see [Scopes](scopes.md).
- `is_ip_allowed(self, client_ip: str) -> bool` — see
  [IP restrictions](ip-restrictions.md).
- `record_usage(self) -> None` — updates `last_used_at`, throttled by
  `LAST_USED_THRESHOLD`. Called automatically by both framework
  integrations on every successful authentication.
- `revoke(self, *, reason: str = "") -> None`
- `reactivate(self) -> None`
- `rotate(self, *, prefix="tak", **overrides) -> tuple[instance, raw_key]`
  — raises `ValueError` if the key is already inactive or expired.

**Properties**

- `is_expired: bool`
- `is_valid: bool` — `is_active and not is_expired`

**Class attributes**

- `LAST_USED_THRESHOLD: ClassVar[timedelta]` — default `timedelta(minutes=5)`,
  overridable per subclass.

See [Key lifecycle](key-lifecycle.md) for all of the above in context.

### `TenantAPIKeyManager`

The default manager (`.objects`) on `AbstractTenantAPIKey`.

- `get_from_key(self, raw_key: str) -> AbstractTenantAPIKey` — indexed
  prefix lookup only; does **not** verify the secret. Call `verify_key()`
  on the result. Raises `DoesNotExist` if no row matches.
- `get_usable_keys(self) -> QuerySet[AbstractTenantAPIKey]` — active,
  unexpired keys only.

### `Environment`

`TextChoices`: `PRODUCTION` (default), `STAGING`, `DEVELOPMENT`, `TEST`. See
[Environments](environments.md).

### `RateLimitWindow`

`TextChoices`: `SECOND`, `MINUTE` (default), `HOUR`, `DAY`. See
[Rate limiting](rate-limiting.md).

### Module-level functions

- `generate_api_key(prefix: str = "tak", *, environment: str = "production") -> tuple[str, str, str]`
  — returns `(full_key, key_prefix, hashed_key)`. Raises `ValueError` if
  `prefix` is too long to fit `AbstractTenantAPIKey.prefix`'s
  `max_length=32`, or if `environment` isn't a valid choice.
- `hash_key(raw_key: str) -> str` — SHA-256 hex digest of `raw_key`.
- `get_api_key_model() -> type[AbstractTenantAPIKey]` — resolves
  `settings.TENANT_API_KEY_MODEL`. Raises `ImproperlyConfigured` if unset
  or invalid.

## `django_tenant_apikeys.ip`

No optional dependency required.

- `get_client_ip(request) -> str` — see
  [IP restrictions](ip-restrictions.md#resolving-the-clients-ip-from-a-request).

## `django_tenant_apikeys.ratelimit`

No optional dependency required.

- `check_rate_limit(api_key) -> RateLimitResult` — records one request and
  checks it against `api_key.rate_limit`. See
  [Rate limiting](rate-limiting.md#checking-the-limit).
- `RateLimitResult` — a frozen dataclass: `allowed: bool`, `limit: int | None`,
  `remaining: int | None`, `reset_at: int | None` (Unix timestamp),
  `retry_after: int | None` (seconds; set only when `allowed` is `False`).
  The last four are all `None` when the key has no `rate_limit` configured.
- `RateLimitBackend` — the `Protocol` a custom backend implements: one
  method, `hit(key: str, limit: int, window_seconds: int) -> RateLimitResult`.
- `CacheRateLimitBackend(cache: BaseCache | None = None)` — the default
  backend. See [Rate limiting](rate-limiting.md#how-the-default-backend-counts-requests).
- `get_rate_limit_backend() -> RateLimitBackend` — resolves
  `TENANT_API_KEY_RATE_LIMIT_BACKEND`, defaulting to `CacheRateLimitBackend`.

## `django_tenant_apikeys.authentication` (needs `[drf]`)

- `TenantAPIKeyAuthentication` — DRF `BaseAuthentication` subclass.
    - `keyword = "Api-Key"`, `model: type[AbstractTenantAPIKey] | None = None`
    - `get_model(self) -> type[AbstractTenantAPIKey]` — returns `self.model`
      or `get_api_key_model()`.
    - `authenticate(self, request) -> tuple[None, AbstractTenantAPIKey] | None`
    - `authenticate_credentials(self, raw_key, request=None) -> tuple[None, AbstractTenantAPIKey]`
      — the lower-level method `authenticate()` delegates to after parsing
      the header; `request` is optional, and tenant attachment is skipped
      if it's `None`.
    - `authenticate_header(self, request) -> str`
- `API_KEY_KEYWORD` — `"Api-Key"`, the scheme both integrations parse.

See [Django REST Framework](django-rest-framework.md).

## `django_tenant_apikeys.permissions` (needs `[drf]`)

All three are `BasePermission` subclasses with a `has_permission(self, request, view) -> bool`
method, meant to compose in `permission_classes` — see
[How the policies interact](django-rest-framework.md#how-the-policies-interact).

- `HasAPIKeyScope` — enforces the view's `required_scopes` against
  `request.auth.has_scope(...)`. See [Scopes](scopes.md).
- `HasAllowedIP` — enforces `request.auth.allowed_ips`. See
  [IP restrictions](ip-restrictions.md).
- `WithinRateLimit` — enforces `request.auth.rate_limit`; raises DRF's
  `Throttled` (429) once exceeded, and sets `X-RateLimit-*` response
  headers. See [Rate limiting](rate-limiting.md).

All three return `False` if `request.auth` isn't an `AbstractTenantAPIKey`
instance, so each is meant to be paired with `TenantAPIKeyAuthentication`,
not used alone.

## `django_tenant_apikeys.ninja` (needs `[ninja]`)

- `TenantAPIKeyAuth` — Ninja `APIKeyHeader` subclass.
    - `param_name = "Authorization"`, `openapi_scheme = "apikey"`,
      `model: type[AbstractTenantAPIKey] | None = None`
    - `get_model(self) -> type[AbstractTenantAPIKey]`
    - `authenticate(self, request, key: str | None) -> AbstractTenantAPIKey | None`

See [Django Ninja](django-ninja.md).

## `django_tenant_apikeys.admin`

- `TenantAPIKeyAdmin` — `ModelAdmin` subclass. See [Admin](admin.md) for
  `list_display`, `list_filter`, `readonly_fields`, the `masked_key`/`status`
  display methods, the `revoke_selected` action, and `save_model()`'s
  one-time key reveal.

## Management commands

Require `django_tenant_apikeys` in `INSTALLED_APPS`.

- `tenant_api_key_revoke <prefix> [--reason TEXT]`
- `tenant_api_key_rotate <prefix>`

See [Management commands](management-commands.md).

## Settings

See [Configuration](configuration.md) for the complete list:
`TENANT_API_KEY_MODEL`, `TENANT_API_KEY_TRUSTED_PROXY_HEADER`,
`TENANT_API_KEY_TRUSTED_PROXY_COUNT`,
`TENANT_API_KEY_RATE_LIMIT_CACHE`, `TENANT_API_KEY_RATE_LIMIT_BACKEND`.
