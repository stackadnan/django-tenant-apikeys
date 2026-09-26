# Troubleshooting

## `ImproperlyConfigured: TENANT_API_KEY_MODEL is not set`

`get_api_key_model()` (and anything that calls it — the default
`TenantAPIKeyAuthentication.get_model()`, `TenantAPIKeyAuth.get_model()`,
both management commands) needs `settings.TENANT_API_KEY_MODEL` to be a
`"app_label.ModelName"` string. Set it, or subclass the authentication
class with an explicit `model` attribute if you'd rather not rely on the
setting — see [Configuration](configuration.md#tenant_api_key_model).

## `ImproperlyConfigured: ... has not been installed`

`TENANT_API_KEY_MODEL` points at a model that either isn't in
`INSTALLED_APPS` yet, or isn't a valid `app_label.ModelName` string (a typo,
missing dot, wrong casing). Check the app is installed and the string
matches your model's actual app label and class name.

## A key I just created won't authenticate

Almost always one of two things:

- **You're comparing against `instance.hashed_key` instead of the raw key.**
  `generate_key()` returns `(instance, raw_key)` — `raw_key` is what a
  client sends in the `Authorization` header. `instance.hashed_key` is what
  ends up in the database and is never usable as a credential itself.
- **The key is inactive or expired.** Check `instance.is_valid` — it's
  `is_active and not is_expired`. A freshly created key defaults to
  `is_active=True` and `expires_at=None` (never expires), so if it's
  failing, something explicitly set one of those.

## `request.tenant` isn't set

`TenantAPIKeyAuthentication`/`TenantAPIKeyAuth` only attach `request.tenant`
if your concrete model has an attribute named exactly `tenant`
(`hasattr(api_key, "tenant")`). A differently-named relation
(`organization`, `account`, ...) won't be picked up automatically — read
`request.auth.<your field name>` instead, or rename the field. See
[Multi-tenancy](multi-tenancy.md#how-requesttenant-gets-set).

## Scopes/IP restriction/rate limit aren't being enforced

For DRF, each policy is its own permission class, and none of them run
unless it's actually in `permission_classes`:

```python
permission_classes = [HasAllowedIP, WithinRateLimit, HasAPIKeyScope]
```

Forgetting one of them for a given view means that check simply doesn't
run for that view — there's no global switch that turns policies on for
every endpoint at once. See
[How the policies interact](django-rest-framework.md#how-the-policies-interact).

For Django Ninja, there's no permission-class system at all — every check
is an explicit `if` statement you write in the view body. If you didn't
write the check, it doesn't happen. See [Django Ninja](django-ninja.md).

Also worth checking: is the field actually set on the key? A key with
`allowed_ips=[]` or `rate_limit=None` is unrestricted by design — that's
the backward-compatible default, not a bug.

## Rate limiting seems to reset unexpectedly, or allows more than the configured limit

Two common causes:

- **Multiple worker processes, default cache.** `CacheRateLimitBackend`
  with Django's default `LocMemCache` counts requests **per process**. If
  you're running gunicorn/uWSGI with more than one worker, each worker
  enforces the limit independently — a `rate_limit=100` effectively becomes
  `100 × number of workers`. Point `CACHES["default"]` (or
  `TENANT_API_KEY_RATE_LIMIT_CACHE`) at Memcached or a shared Redis to fix
  this. See
  [Rate limiting: how the default backend counts requests](rate-limiting.md#how-the-default-backend-counts-requests).
- **Fixed-window boundary burst.** A key can legitimately use up to ~2x its
  limit across a window rollover (a full window's quota right before
  `:00`, another full window's quota right after). This is a known
  characteristic of the fixed-window algorithm, not a bug — see the same
  section above.

## `TENANT_API_KEY_TRUSTED_PROXY_HEADER` doesn't seem to work, or seems too permissive

If it's unset, `get_client_ip()` always reads `REMOTE_ADDR` — this is
intentional; the setting is opt-in. If it's set but the header isn't
present on the request, `get_client_ip()` falls back to `REMOTE_ADDR`
rather than erroring.

If every legitimate client is suddenly rejected by `allowed_ips` after
setting it, you probably have more than one trusted proxy: `get_client_ip()`
takes the rightmost entry by default, which is then a proxy's address, not
the client's. Set `TENANT_API_KEY_TRUSTED_PROXY_COUNT` to the number of
proxy hops. Client-supplied entries on the left of the header are never
used, so a client can't claim an allowed IP by sending its own
`X-Forwarded-For`. See
[IP restrictions: trusting a proxy header](ip-restrictions.md#trusting-a-proxy-header).

## `makemigrations` wants to create a migration after upgrading

Expected, if the new release adds fields to `AbstractTenantAPIKey` (this
happens whenever a new policy or lifecycle field is added — see the
[changelog](https://github.com/stackadnan/django-tenant-apikeys/blob/main/CHANGELOG.md)).
Since it's abstract, Django doesn't ship a migration for it — your concrete
subclass's app needs one:

```bash
python manage.py makemigrations myapp
python manage.py migrate
```

Every field added since 0.2.0 has a backward-compatible default, so
existing rows and existing code keep working once the migration runs — you
don't need to backfill anything by hand.

## `mypy`/`ruff` failures when contributing

See [Testing](testing.md) for the exact commands CI runs, and
`CONTRIBUTING.md` in the repository for the full contribution workflow.

## Still stuck

Open a GitHub issue with a minimal reproduction:
<https://github.com/stackadnan/django-tenant-apikeys/issues>. For anything
security-related, use the
[private reporting form](https://github.com/stackadnan/django-tenant-apikeys/security/advisories/new)
instead — see [Security](security.md).
