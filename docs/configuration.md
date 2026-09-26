# Configuration

Every setting the package reads, what it's for, and what happens if you
leave it unset.

## `TENANT_API_KEY_MODEL`

```python
TENANT_API_KEY_MODEL = "myapp.OrganizationAPIKey"
```

**Required**, unless you avoid the generic model resolution entirely (see
below). A `"app_label.ModelName"` string pointing at your concrete
`AbstractTenantAPIKey` subclass. Read by `get_api_key_model()`, which
`TenantAPIKeyAuthentication.get_model()` and `TenantAPIKeyAuth.get_model()`
both call by default, and by both management commands.

Unset or pointing at a model that isn't installed raises
`ImproperlyConfigured` with a specific message for each case (missing vs.
malformed vs. not found) — not a generic Django error.

You can skip this setting entirely by subclassing the authentication class
with an explicit `model` attribute instead:

```python
class PartnerAPIKeyAuthentication(TenantAPIKeyAuthentication):
    model = PartnerAPIKey
```

Useful if you have more than one key model in the same project (a
`PartnerAPIKey` and an `OrganizationAPIKey`, say) — `TENANT_API_KEY_MODEL`
can only point at one.

## `TENANT_API_KEY_TRUSTED_PROXY_HEADER`

```python
TENANT_API_KEY_TRUSTED_PROXY_HEADER = "HTTP_X_FORWARDED_FOR"
```

**Optional, unset by default.** Names a `request.META` key that
`get_client_ip()` should trust for the client's IP instead of `REMOTE_ADDR`.
Only relevant if you're using [IP restrictions](ip-restrictions.md).

Leave this unset unless a reverse proxy you control is the one setting (and
stripping any client-supplied copy of) that header before Django ever sees
the request. See [IP restrictions](ip-restrictions.md#trusting-a-proxy-header)
for why this defaults to off.

## `TENANT_API_KEY_TRUSTED_PROXY_COUNT`

```python
TENANT_API_KEY_TRUSTED_PROXY_COUNT = 2
```

**Optional, default `1`.** How many trusted proxies sit between the client
and Django. `get_client_ip()` takes that many entries from the **right** of
`TENANT_API_KEY_TRUSTED_PROXY_HEADER` (entries to the left were written by
the client and are never used). Ignored unless the header setting is set.
See [IP restrictions](ip-restrictions.md#trusting-a-proxy-header).

## `TENANT_API_KEY_RATE_LIMIT_CACHE`

```python
TENANT_API_KEY_RATE_LIMIT_CACHE = "default"
```

**Optional**, defaults to `"default"`. The `CACHES` alias
`CacheRateLimitBackend` (the default [rate limiting](rate-limiting.md)
backend) counts requests in. Point it at a dedicated cache if you don't want
rate-limit counters sharing space with your project's general-purpose cache.

## `TENANT_API_KEY_RATE_LIMIT_BACKEND`

```python
TENANT_API_KEY_RATE_LIMIT_BACKEND = "myapp.ratelimit.RedisRateLimitBackend"
```

**Optional, unset by default** (uses `CacheRateLimitBackend`). A dotted path
to a class implementing the `RateLimitBackend` protocol — one method,
`hit(key, limit, window_seconds)`. See
[Rate limiting: a custom backend](rate-limiting.md#a-custom-backend) if you
need something the default cache-backed counter doesn't give you.

## Settings this package does not have

There's no `TENANT_API_KEY_ENABLE_RATE_LIMITING` or similar feature flag —
[rate limiting](rate-limiting.md), [IP restrictions](ip-restrictions.md),
[environments](environments.md), and [metadata](metadata.md) are all
per-key, not global. A key with no `rate_limit` set is never rate-limited; a
key with no `allowed_ips` accepts any IP. There's nothing to switch on at
the project level, and nothing that changes behavior for keys that don't
opt in.
